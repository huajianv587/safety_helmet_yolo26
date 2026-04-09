from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
from PIL import Image, ImageTk

try:
    import tkinter as tk
    from tkinter import ttk
except Exception as exc:  # pragma: no cover - platform specific import path
    raise RuntimeError("Tkinter is required for the real-time camera viewer.") from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import AppSettings, load_settings
from helmet_monitoring.core.schemas import DetectionRecord
from helmet_monitoring.services.detector import HelmetDetector


def _parse_source(value: str):
    cleaned = str(value).strip()
    if cleaned.lstrip("-").isdigit():
        return int(cleaned)
    return cleaned


def _default_source(settings: AppSettings) -> str:
    for camera in settings.cameras:
        if camera.enabled:
            return camera.source
    return "0"


@dataclass(slots=True)
class DetectionSnapshot:
    detections: list[DetectionRecord]
    infer_ms: float
    updated_at: float


class LatestFrameCapture:
    def __init__(self, source: str, *, width: int, height: int) -> None:
        self.source_value = source
        self.source = _parse_source(source)
        self.width = width
        self.height = height
        self.capture = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.latest_frame = None
        self.camera_fps = 0.0
        self.last_error: str | None = None
        self._last_frame_ts = 0.0

    def start(self) -> None:
        capture = self._open_capture()
        if capture is None or not capture.isOpened():
            raise RuntimeError(f"Unable to open camera source: {self.source_value}")
        self.capture = capture
        self.thread = threading.Thread(target=self._reader_loop, name="realtime-camera-reader", daemon=True)
        self.thread.start()

    def _open_capture(self):
        capture = None
        if isinstance(self.source, int) and os.name == "nt" and hasattr(cv2, "CAP_DSHOW"):
            capture = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
        if capture is None or not capture.isOpened():
            capture = cv2.VideoCapture(self.source)
        if capture is None:
            return None
        try:
            capture.set(getattr(cv2, "CAP_PROP_BUFFERSIZE", 38), 1)
        except Exception:
            pass
        if isinstance(self.source, int):
            try:
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            except Exception:
                pass
        return capture

    def _reader_loop(self) -> None:
        while not self.stop_event.is_set():
            if self.capture is None:
                self.last_error = "Camera is not initialized."
                return
            success, frame = self.capture.read()
            if not success:
                self.last_error = "Frame read failed."
                time.sleep(0.02)
                continue
            now = time.perf_counter()
            camera_fps = self.camera_fps
            if self._last_frame_ts:
                delta = now - self._last_frame_ts
                if delta > 0:
                    camera_fps = 1.0 / delta
            self._last_frame_ts = now
            with self.lock:
                self.latest_frame = frame
                self.camera_fps = camera_fps
                self.last_error = None

    def get_frame(self):
        with self.lock:
            if self.latest_frame is None:
                return None
            return self.latest_frame.copy()

    def get_camera_fps(self) -> float:
        with self.lock:
            return self.camera_fps

    def close(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.5)
        if self.capture is not None:
            self.capture.release()
            self.capture = None


class LatestDetectionWorker:
    def __init__(self, detector: HelmetDetector, capture: LatestFrameCapture, *, detect_interval_ms: int) -> None:
        self.detector = detector
        self.capture = capture
        self.detect_interval_seconds = max(0.01, detect_interval_ms / 1000.0)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="realtime-camera-detector", daemon=True)
        self.lock = threading.Lock()
        self.snapshot = DetectionSnapshot(detections=[], infer_ms=0.0, updated_at=0.0)

    def start(self) -> None:
        self.thread.start()

    def _loop(self) -> None:
        next_run_at = 0.0
        while not self.stop_event.is_set():
            now = time.perf_counter()
            if now < next_run_at:
                time.sleep(min(0.01, next_run_at - now))
                continue
            frame = self.capture.get_frame()
            if frame is None:
                time.sleep(0.01)
                continue
            detect_started = time.perf_counter()
            detections = self.detector.detect(frame)
            infer_ms = (time.perf_counter() - detect_started) * 1000.0
            with self.lock:
                self.snapshot = DetectionSnapshot(
                    detections=detections,
                    infer_ms=infer_ms,
                    updated_at=time.time(),
                )
            next_run_at = time.perf_counter() + self.detect_interval_seconds

    def latest(self) -> DetectionSnapshot:
        with self.lock:
            return DetectionSnapshot(
                detections=list(self.snapshot.detections),
                infer_ms=self.snapshot.infer_ms,
                updated_at=self.snapshot.updated_at,
            )

    def close(self) -> None:
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=0.5)


def _draw_status_overlay(
    frame,
    *,
    detection_snapshot: DetectionSnapshot,
    camera_fps: float,
    display_fps: float,
) -> None:
    safe_count = sum(1 for item in detection_snapshot.detections if not item.is_violation)
    violation_count = sum(1 for item in detection_snapshot.detections if item.is_violation)
    lines = [
        f"Display FPS: {display_fps:.1f}",
        f"Camera FPS: {camera_fps:.1f}",
        f"Infer: {detection_snapshot.infer_ms:.0f} ms",
        f"Safe: {safe_count}  Warning: {violation_count}",
    ]
    for index, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (18, 30 + index * 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            (255, 255, 255),
            2,
        )
    if violation_count:
        cv2.putText(
            frame,
            "NO HELMET DETECTED",
            (18, 30 + len(lines) * 28 + 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.92,
            (0, 0, 255),
            3,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Real-time webcam viewer with green/red helmet boxes.")
    parser.add_argument(
        "--config",
        default=None,
        help="Optional runtime config path. Defaults to HELMET_CONFIG_PATH or configs/runtime.json.",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Camera source override. Use 0 for the local webcam.",
    )
    parser.add_argument("--confidence", type=float, default=None, help="Detection confidence threshold override.")
    parser.add_argument("--imgsz", type=int, default=None, help="Detection image size override.")
    parser.add_argument("--device", default=None, help="Inference device override, for example cpu.")
    parser.add_argument("--camera-width", type=int, default=1280, help="Preferred camera width.")
    parser.add_argument("--camera-height", type=int, default=720, help="Preferred camera height.")
    parser.add_argument("--display-width", type=int, default=960, help="Display width for the preview window.")
    parser.add_argument(
        "--detect-interval-ms",
        type=int,
        default=80,
        help="How often to run model inference. Lower is more responsive but heavier on CPU.",
    )
    parser.add_argument(
        "--overlay-hold-ms",
        type=int,
        default=260,
        help="How long to reuse the latest detection boxes while new frames keep arriving.",
    )
    parser.add_argument(
        "--title",
        default="Safety Helmet Real-Time Viewer",
        help="Desktop window title.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    source = str(args.source or _default_source(settings)).strip() or "0"
    model_settings = replace(
        settings.model,
        confidence=args.confidence if args.confidence is not None else settings.model.confidence,
        imgsz=args.imgsz if args.imgsz is not None else settings.model.imgsz,
        device=args.device or settings.model.device,
    )
    detector = HelmetDetector(model_settings, settings.tracking)
    capture = LatestFrameCapture(source, width=args.camera_width, height=args.camera_height)
    capture.start()
    detection_worker = LatestDetectionWorker(
        detector,
        capture,
        detect_interval_ms=args.detect_interval_ms,
    )
    detection_worker.start()

    root = tk.Tk()
    root.title(args.title)
    root.geometry(f"{max(640, args.display_width)}x760")
    root.configure(bg="#101622")

    title_var = tk.StringVar(value=f"Source: {source} | Red = no helmet | Green = helmet")
    status_var = tk.StringVar(value="Starting camera...")
    image_label = ttk.Label(root)
    image_label.pack(fill="both", expand=True, padx=12, pady=(12, 8))

    title_label = ttk.Label(root, textvariable=title_var, anchor="center")
    title_label.pack(fill="x", padx=12)
    status_label = ttk.Label(root, textvariable=status_var, anchor="center")
    status_label.pack(fill="x", padx=12, pady=(4, 12))

    loop_state = {"last_render_ts": 0.0}

    def _close() -> None:
        detection_worker.close()
        capture.close()
        root.destroy()

    def _tick() -> None:
        frame = capture.get_frame()
        if frame is None:
            status_var.set(capture.last_error or "Waiting for the first camera frame...")
            root.after(20, _tick)
            return

        detection_snapshot = detection_worker.latest()
        now = time.time()
        if detection_snapshot.detections and (now - detection_snapshot.updated_at) * 1000.0 <= args.overlay_hold_ms:
            preview_frame = detector.annotate(frame, detection_snapshot.detections)
        else:
            preview_frame = frame

        last_render_ts = loop_state["last_render_ts"]
        display_fps = 0.0
        now_perf = time.perf_counter()
        if last_render_ts:
            delta = now_perf - last_render_ts
            if delta > 0:
                display_fps = 1.0 / delta
        loop_state["last_render_ts"] = now_perf

        _draw_status_overlay(
            preview_frame,
            detection_snapshot=detection_snapshot,
            camera_fps=capture.get_camera_fps(),
            display_fps=display_fps,
        )

        rgb_frame = cv2.cvtColor(preview_frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb_frame)
        if args.display_width and image.width > args.display_width:
            scaled_height = max(1, int(image.height * (args.display_width / float(image.width))))
            image = image.resize((args.display_width, scaled_height), Image.Resampling.BILINEAR)
        tk_image = ImageTk.PhotoImage(image=image)
        image_label.configure(image=tk_image)
        image_label.image = tk_image

        snapshot_age_ms = max(0.0, (now - detection_snapshot.updated_at) * 1000.0) if detection_snapshot.updated_at else 0.0
        status_var.set(
            f"Detection every ~{args.detect_interval_ms} ms | latest boxes age {snapshot_age_ms:.0f} ms | close window to stop"
        )
        root.after(15, _tick)

    root.protocol("WM_DELETE_WINDOW", _close)
    root.bind("<Escape>", lambda _event: _close())
    root.bind("q", lambda _event: _close())
    root.after(15, _tick)
    root.mainloop()


if __name__ == "__main__":
    main()
