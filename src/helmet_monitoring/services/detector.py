from __future__ import annotations

from typing import Any

from helmet_monitoring.core.config import ModelSettings, MonitoringSettings, TrackingSettings
from helmet_monitoring.core.schemas import DetectionRecord
from helmet_monitoring.services.inference_backends import (
    InferenceBackend,
    OnnxRuntimeInferenceBackend,
    PyTorchInferenceBackend,
    clone_detections,
)


class HelmetDetector:
    def __init__(
        self,
        settings: ModelSettings,
        tracking: TrackingSettings | None = None,
        monitoring: MonitoringSettings | None = None,
    ) -> None:
        self.settings = settings
        self.tracking = tracking or TrackingSettings()
        self.monitoring = monitoring or MonitoringSettings()
        self._frame_counter = 0
        self._last_detections: list[DetectionRecord] = []
        self._backend = self._build_backend()
        self._backend.warmup()

    def _build_backend(self) -> InferenceBackend:
        requested = str(self.settings.backend or "auto").strip().lower() or "auto"
        if requested == "pytorch":
            return PyTorchInferenceBackend(self.settings, self.tracking)
        if requested == "onnxruntime":
            return OnnxRuntimeInferenceBackend(self.settings, self.tracking)
        if str(self.settings.device).lower() == "cpu":
            try:
                return OnnxRuntimeInferenceBackend(self.settings, self.tracking)
            except Exception:
                return PyTorchInferenceBackend(self.settings, self.tracking)
        return PyTorchInferenceBackend(self.settings, self.tracking)

    @property
    def backend_name(self) -> str:
        return self._backend.name

    def metadata(self) -> dict[str, Any]:
        payload = self._backend.metadata()
        payload["keyframe_interval"] = int(self.monitoring.keyframe_interval)
        return payload

    def detect(self, frame) -> list[DetectionRecord]:
        self._frame_counter += 1
        if (
            self._backend.name == "onnxruntime"
            and self.monitoring.keyframe_interval > 1
            and self._last_detections
            and (self._frame_counter - 1) % self.monitoring.keyframe_interval != 0
        ):
            return clone_detections(self._last_detections)
        self._last_detections = self._backend.detect(frame)
        return clone_detections(self._last_detections)

    def annotate(self, frame, detections: list[DetectionRecord]):
        return self._backend.annotate(frame, detections)
