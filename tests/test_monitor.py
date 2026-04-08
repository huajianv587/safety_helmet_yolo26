from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import (
    AppSettings,
    CameraSettings,
    ClipSettings,
    EventRuleSettings,
    FaceRecognitionSettings,
    GovernanceSettings,
    IdentitySettings,
    LlmFallbackSettings,
    ModelSettings,
    MonitoringSettings,
    NotificationSettings,
    OcrSettings,
    PersistenceSettings,
    SecuritySettings,
    SupabaseSettings,
    TrackingSettings,
)
from helmet_monitoring.services.monitor import SafetyHelmetMonitor


def build_settings(enabled: bool = True) -> AppSettings:
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="artifacts/training_runs/helmet_project/cpu_test3/weights/best.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(
            snapshot_dir="artifacts/captures",
            runtime_dir="artifacts/runtime",
            upload_to_supabase_storage=False,
        ),
        monitoring=MonitoringSettings(camera_retry_seconds=0.0),
        identity=IdentitySettings(),
        face_recognition=FaceRecognitionSettings(enabled=False),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(),
        notifications=NotificationSettings(enabled=False, email_enabled=False),
        security=SecuritySettings(),
        supabase=SupabaseSettings(),
        cameras=(
            CameraSettings(
                camera_id="cam-1",
                camera_name="Camera 1",
                source="0",
                location="Test",
                department="QA",
                enabled=enabled,
            ),
        ),
    )


class FakeRepository:
    backend_name = "local"

    def __init__(self) -> None:
        self.camera_records: list[dict] = []

    def upsert_camera(self, camera_record: dict) -> dict:
        self.camera_records.append(camera_record)
        return camera_record

    def update_alert(self, alert_id: str, patch: dict):
        return None

    def insert_alert(self, alert_record: dict) -> dict:
        return alert_record

    def insert_audit_log(self, audit_record: dict) -> dict:
        return audit_record


class OfflineStream:
    def __init__(self, camera, retry_seconds: float) -> None:
        self.camera = camera
        self.retry_seconds = retry_seconds
        self.frames_seen = 0
        self.retry_count = 0
        self.reconnect_count = 0
        self.last_error = "Unable to open camera stream."
        self.last_frame_ts = 0.0
        self.last_fps = None

    def read(self):
        self.retry_count += 1
        self.last_error = "Unable to open camera stream."
        return False, None

    def release(self) -> None:
        return None


class OnlineStream:
    def __init__(self, camera, retry_seconds: float) -> None:
        self.camera = camera
        self.retry_seconds = retry_seconds
        self.frames_seen = 0
        self.retry_count = 0
        self.reconnect_count = 0
        self.last_error = None
        self.last_frame_ts = 1.0
        self.last_fps = 12.5

    def read(self):
        self.frames_seen += 1
        self.last_frame_ts = float(self.frames_seen)
        return True, np.zeros((48, 64, 3), dtype=np.uint8)

    def release(self) -> None:
        return None


class MonitorTest(unittest.TestCase):
    def test_monitor_requires_at_least_one_enabled_camera(self) -> None:
        with self.assertRaises(ValueError):
            SafetyHelmetMonitor(build_settings(enabled=False), repository=FakeRepository())

    def test_monitor_respects_frame_limit_when_camera_is_offline(self) -> None:
        repo = FakeRepository()
        sleep_calls = {"count": 0}

        def fake_sleep(_: float) -> None:
            sleep_calls["count"] += 1
            if sleep_calls["count"] > 5:
                raise AssertionError("Monitor exceeded the offline smoke loop budget.")

        with patch("helmet_monitoring.services.monitor.CameraStream", OfflineStream), patch(
            "helmet_monitoring.services.monitor.EvidenceStore"
        ), patch("helmet_monitoring.services.monitor.HelmetDetector"), patch(
            "helmet_monitoring.services.monitor.ViolationEventEngine"
        ), patch("helmet_monitoring.services.monitor.build_identity_resolver"), patch(
            "helmet_monitoring.services.monitor.FalsePositiveGovernance"
        ), patch("helmet_monitoring.services.monitor.ClipRecorder"), patch(
            "helmet_monitoring.services.monitor.NotificationService"
        ), patch("helmet_monitoring.services.monitor.time.sleep", side_effect=fake_sleep):
            monitor = SafetyHelmetMonitor(build_settings(enabled=True), repository=repo)
            monitor.run(max_frames=3)

        self.assertGreaterEqual(len(repo.camera_records), 1)

    def test_monitor_writes_live_preview_and_metadata(self) -> None:
        repo = FakeRepository()

        class FakeDetector:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def detect(self, _frame):
                return []

        class FakeEventEngine:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def evaluate(self, *_args, **_kwargs):
                return []

        class FakeIdentityResolver:
            def resolve(self, *_args, **_kwargs):
                return None

        class FakeGovernance:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

        class FakeClipRecorder:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def capture(self, *_args, **_kwargs):
                return []

            def start(self, *_args, **_kwargs):
                return None

        class FakeNotifier:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def send_alert_email(self, *_args, **_kwargs):
                return "skipped"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = replace(
                build_settings(enabled=True),
                persistence=PersistenceSettings(
                    snapshot_dir=str(root / "captures"),
                    runtime_dir=str(root / "runtime"),
                    upload_to_supabase_storage=False,
                ),
            )
            with patch("helmet_monitoring.services.monitor.CameraStream", OnlineStream), patch(
                "helmet_monitoring.services.monitor.EvidenceStore"
            ), patch("helmet_monitoring.services.monitor.HelmetDetector", FakeDetector), patch(
                "helmet_monitoring.services.monitor.ViolationEventEngine", FakeEventEngine
            ), patch("helmet_monitoring.services.monitor.build_identity_resolver", return_value=FakeIdentityResolver()), patch(
                "helmet_monitoring.services.monitor.FalsePositiveGovernance", FakeGovernance
            ), patch("helmet_monitoring.services.monitor.ClipRecorder", FakeClipRecorder), patch(
                "helmet_monitoring.services.monitor.NotificationService", FakeNotifier
            ):
                monitor = SafetyHelmetMonitor(settings, repository=repo)
                monitor.run(max_frames=1)

            preview_path = root / "runtime" / "ops" / "live_frames" / "cam-1.jpg"
            self.assertTrue(preview_path.exists())

            monitor_health = root / "runtime" / "ops" / "monitor_health.json"
            payload = json.loads(monitor_health.read_text(encoding="utf-8"))
            self.assertEqual(payload["camera_statuses"][0]["preview_path"], str(preview_path))
            self.assertTrue(payload["camera_statuses"][0]["preview_updated_at"])


if __name__ == "__main__":
    unittest.main()
