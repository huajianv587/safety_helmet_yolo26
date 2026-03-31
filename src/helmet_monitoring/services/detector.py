from __future__ import annotations

from pathlib import Path

import cv2
from ultralytics import YOLO

from helmet_monitoring.core.config import ModelSettings, TrackingSettings
from helmet_monitoring.core.schemas import DetectionRecord


def normalize_label(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


class HelmetDetector:
    def __init__(self, settings: ModelSettings, tracking: TrackingSettings | None = None) -> None:
        self.settings = settings
        self.tracking = tracking or TrackingSettings()
        self.model = YOLO(settings.path)
        self.model_name = Path(settings.path).name
        self.violation_labels = {normalize_label(item) for item in settings.violation_labels}
        self.safe_labels = {normalize_label(item) for item in settings.safe_labels}

    def detect(self, frame) -> list[DetectionRecord]:
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
        names = result.names
        detections: list[DetectionRecord] = []
        for box in result.boxes:
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
            is_violation = normalized in self.violation_labels or (
                class_id == 1 and normalized not in self.safe_labels
            )
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
