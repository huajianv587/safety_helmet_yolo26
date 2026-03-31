from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import cv2

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.core.schemas import AlertRecord, DetectionRecord, utc_now
from helmet_monitoring.services.detector import HelmetDetector
from helmet_monitoring.services.event_engine import ViolationEventEngine
from helmet_monitoring.storage.repository import LocalAlertRepository
from helmet_monitoring.storage.snapshot_store import SnapshotStore


def main() -> None:
    settings = load_settings("configs/runtime.json")
    detector = HelmetDetector(settings.model)
    event_engine = ViolationEventEngine(settings.event_rules)
    repository = LocalAlertRepository(settings.resolve_path(settings.persistence.runtime_dir))
    snapshot_store = SnapshotStore(settings.resolve_path(settings.persistence.snapshot_dir))

    image_dir = settings.resolve_path("data/helmet_detection_dataset/images/val")
    image_path = next(image_dir.glob("*.jpg"))
    frame = cv2.imread(str(image_path))
    detections = detector.detect(frame)
    if not any(item.is_violation for item in detections):
        if detections:
            base = detections[0]
            detections = [
                DetectionRecord(
                    class_id=1,
                    label="no_helmet",
                    confidence=max(base.confidence, settings.event_rules.min_confidence_for_alert),
                    x1=base.x1,
                    y1=base.y1,
                    x2=base.x2,
                    y2=base.y2,
                    is_violation=True,
                )
            ]
        else:
            detections = [
                DetectionRecord(
                    class_id=1,
                    label="no_helmet",
                    confidence=settings.event_rules.min_confidence_for_alert,
                    x1=40,
                    y1=40,
                    x2=160,
                    y2=220,
                    is_violation=True,
                )
            ]
    observed_at = utc_now()

    alerts = []
    for _ in range(settings.event_rules.alert_frames):
        alerts = event_engine.evaluate("smoke-cam", detections, observed_at)
        observed_at = utc_now()

    annotated = detector.annotate(frame, detections)
    snapshot = snapshot_store.save("smoke-cam", annotated, uuid.uuid4().hex, utc_now())

    if alerts:
        alert = AlertRecord(
            alert_id=uuid.uuid4().hex,
            event_key=alerts[0].event_key,
            camera_id="smoke-cam",
            camera_name="Smoke Camera",
            location="Smoke Test",
            department="QA",
            violation_type="no_helmet",
            risk_level="high",
            confidence=alerts[0].confidence,
            snapshot_path=snapshot,
            snapshot_url=None,
            status="new",
            bbox=alerts[0].bbox,
            model_name=detector.model_name,
            person_id=None,
            person_name="Unknown",
            employee_id=None,
            team=None,
            role=None,
            phone=None,
            identity_status="unresolved",
            identity_source="smoke_test",
            created_at=utc_now(),
        )
        repository.insert_alert(alert.to_record())

    print(f"detections={len(detections)}")
    print(f"alerts={len(alerts)}")
    print(f"snapshot={snapshot}")
    print(f"repository={repository.backend_name}")


if __name__ == "__main__":
    main()
