from __future__ import annotations

import statistics
import time
from abc import ABC, abstractmethod
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

import cv2
from ultralytics import YOLO

from helmet_monitoring.core.config import ModelSettings, TrackingSettings
from helmet_monitoring.core.schemas import DetectionRecord

onnxruntime = None
_onnxruntime_error: Exception | None = None


def _load_onnxruntime():
    global onnxruntime, _onnxruntime_error
    if onnxruntime is not None:
        return onnxruntime
    if _onnxruntime_error is not None:
        raise RuntimeError(f"onnxruntime is unavailable: {_onnxruntime_error}") from _onnxruntime_error
    try:
        sink = StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            import onnxruntime as ort  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        _onnxruntime_error = exc
        raise RuntimeError(f"onnxruntime is unavailable: {exc}") from exc
    onnxruntime = ort
    return ort


def normalize_label(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _result_to_detections(
    result: Any,
    *,
    violation_labels: set[str],
    safe_labels: set[str],
) -> list[DetectionRecord]:
    names = getattr(result, "names", {})
    detections: list[DetectionRecord] = []
    for box in getattr(result, "boxes", []) or []:
        class_id = int(box.cls[0])
        confidence = float(box.conf[0])
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        track_id = None
        if getattr(box, "id", None) is not None:
            raw_track_id = box.id[0]
            if raw_track_id is not None:
                track_id = str(int(raw_track_id))
        label_raw = names[class_id] if isinstance(names, dict) else names[class_id]
        normalized = normalize_label(str(label_raw))
        is_violation = normalized in violation_labels or (class_id == 1 and normalized not in safe_labels)
        detections.append(
            DetectionRecord(
                class_id=class_id,
                label=str(label_raw),
                confidence=confidence,
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                is_violation=is_violation,
                track_id=track_id,
            )
        )
    return detections


def clone_detections(detections: list[DetectionRecord]) -> list[DetectionRecord]:
    return [
        DetectionRecord(
            class_id=item.class_id,
            label=item.label,
            confidence=item.confidence,
            x1=item.x1,
            y1=item.y1,
            x2=item.x2,
            y2=item.y2,
            is_violation=item.is_violation,
            track_id=item.track_id,
        )
        for item in detections
    ]


class InferenceBackend(ABC):
    def __init__(self, settings: ModelSettings, tracking: TrackingSettings | None = None) -> None:
        self.settings = settings
        self.tracking = tracking or TrackingSettings()
        self.model_name = Path(settings.path).name
        self.violation_labels = {normalize_label(item) for item in settings.violation_labels}
        self.safe_labels = {normalize_label(item) for item in settings.safe_labels}
        self._latency_history_ms: list[float] = []

    def _record_latency(self, duration_ms: float) -> None:
        self._latency_history_ms.append(duration_ms)
        if len(self._latency_history_ms) > 256:
            self._latency_history_ms = self._latency_history_ms[-256:]

    def _summarize_latency(self) -> tuple[float | None, float | None]:
        if not self._latency_history_ms:
            return None, None
        ordered = sorted(self._latency_history_ms)
        p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
        return round(statistics.fmean(self._latency_history_ms), 3), round(ordered[p95_index], 3)

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def warmup(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def detect(self, frame) -> list[DetectionRecord]:
        raise NotImplementedError

    def annotate(self, frame, detections: list[DetectionRecord]):
        annotated = frame.copy()
        for detection in detections:
            color = (0, 0, 255) if detection.is_violation else (0, 180, 0)
            track_part = f" #{detection.track_id}" if detection.track_id else ""
            text = f"{detection.label}{track_part} {detection.confidence:.2f}"
            cv2.rectangle(annotated, (detection.x1, detection.y1), (detection.x2, detection.y2), color, 2)
            cv2.putText(
                annotated,
                text,
                (detection.x1, max(20, detection.y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )
        return annotated

    def metadata(self) -> dict[str, Any]:
        mean_latency_ms, p95_latency_ms = self._summarize_latency()
        return {
            "backend": self.name,
            "device": self.settings.device,
            "model_name": self.model_name,
            "mean_latency_ms": mean_latency_ms,
            "p95_latency_ms": p95_latency_ms,
            "samples": len(self._latency_history_ms),
        }


class PyTorchInferenceBackend(InferenceBackend):
    @property
    def name(self) -> str:
        return "pytorch"

    def __init__(self, settings: ModelSettings, tracking: TrackingSettings | None = None) -> None:
        super().__init__(settings, tracking=tracking)
        self.model = YOLO(settings.path)

    def warmup(self) -> None:
        if self.settings.warmup_runs <= 0:
            return
        sample = [[0] * 3 for _ in range(3)]
        for _ in range(self.settings.warmup_runs):
            try:
                self.model.predict(sample, conf=self.settings.confidence, imgsz=self.settings.imgsz, device=self.settings.device, verbose=False)
            except Exception:
                return

    def detect(self, frame) -> list[DetectionRecord]:
        started = time.perf_counter()
        if self.tracking.enabled and self.tracking.provider == "ultralytics_bytetrack":
            result = self.model.track(
                frame,
                conf=self.settings.confidence,
                imgsz=self.settings.imgsz,
                device=self.settings.device,
                verbose=False,
                persist=self.tracking.persist,
                tracker=self.tracking.tracker_config,
            )[0]
        else:
            result = self.model.predict(
                frame,
                conf=self.settings.confidence,
                imgsz=self.settings.imgsz,
                device=self.settings.device,
                verbose=False,
            )[0]
        self._record_latency((time.perf_counter() - started) * 1000.0)
        return _result_to_detections(result, violation_labels=self.violation_labels, safe_labels=self.safe_labels)


class OnnxRuntimeInferenceBackend(InferenceBackend):
    @property
    def name(self) -> str:
        return "onnxruntime"

    def __init__(self, settings: ModelSettings, tracking: TrackingSettings | None = None) -> None:
        super().__init__(settings, tracking=tracking)
        ort = _load_onnxruntime()
        self.onnx_path = self._resolve_onnx_path()
        # Validate the runtime explicitly so we fail early in CPU-first production.
        self._session = ort.InferenceSession(str(self.onnx_path), providers=["CPUExecutionProvider"])
        self.model = YOLO(str(self.onnx_path))

    def _resolve_onnx_path(self) -> Path:
        configured = str(self.settings.onnx_path or "").strip()
        if configured:
            path = Path(configured)
            if not path.is_absolute():
                path = Path(self.settings.path).resolve().parents[2] / configured
            if not path.exists():
                raise RuntimeError(f"Configured ONNX model not found: {path}")
            return path.resolve()

        source_path = Path(self.settings.path).resolve()
        cache_root = source_path.parents[2] / "artifacts" / "models" / "cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        onnx_path = cache_root / f"{source_path.stem}.onnx"
        if onnx_path.exists() and onnx_path.stat().st_mtime >= source_path.stat().st_mtime:
            return onnx_path
        raise RuntimeError(
            "No cached ONNX model is available. Configure model.onnx_path or pre-export "
            f"the model to {onnx_path} before enabling the onnxruntime backend."
        )

    def warmup(self) -> None:
        if self.settings.warmup_runs <= 0:
            return
        sample = [[0] * 3 for _ in range(3)]
        for _ in range(self.settings.warmup_runs):
            try:
                self.model.predict(sample, conf=self.settings.confidence, imgsz=self.settings.imgsz, device="cpu", verbose=False)
            except Exception:
                return

    def detect(self, frame) -> list[DetectionRecord]:
        started = time.perf_counter()
        result = self.model.predict(
            frame,
            conf=self.settings.confidence,
            imgsz=self.settings.imgsz,
            device="cpu",
            verbose=False,
        )[0]
        self._record_latency((time.perf_counter() - started) * 1000.0)
        return _result_to_detections(result, violation_labels=self.violation_labels, safe_labels=self.safe_labels)
