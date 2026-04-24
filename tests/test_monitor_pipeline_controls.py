from __future__ import annotations

import sys
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import patch


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


def _build_settings() -> AppSettings:
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="artifacts/model.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(snapshot_dir="artifacts/captures", runtime_dir="artifacts/runtime"),
        monitoring=MonitoringSettings(frame_stride=2, inference_workers=1, postprocess_workers=1),
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
                camera_id="cam-001",
                camera_name="Camera 1",
                source="0",
                location="Test",
                department="QA",
                enabled=True,
            ),
        ),
    )


class _FakeRepository:
    backend_name = "local"

    def upsert_camera(self, camera_record):
        return camera_record

    def insert_audit_log(self, audit_record):
        return audit_record


class _FakeStream:
    def __init__(self, camera, retry_seconds: float) -> None:
        self.camera = camera
        self.retry_seconds = retry_seconds
        self.frames_seen = 0
        self.retry_count = 0
        self.reconnect_count = 0
        self.last_error = None
        self.last_frame_ts = None
        self.last_fps = None

    def release(self) -> None:
        return None


class MonitorPipelineControlTest(unittest.TestCase):
    def test_dynamic_frame_stride_rebalances_with_queue_pressure(self) -> None:
        with patch("helmet_monitoring.services.monitor.CameraStream", _FakeStream), patch(
            "helmet_monitoring.services.monitor.EvidenceStore"
        ), patch("helmet_monitoring.services.monitor.HelmetDetector"), patch(
            "helmet_monitoring.services.monitor.ViolationEventEngine"
        ), patch("helmet_monitoring.services.monitor.build_identity_resolver"), patch(
            "helmet_monitoring.services.monitor.FalsePositiveGovernance"
        ), patch("helmet_monitoring.services.monitor.ClipRecorder"), patch(
            "helmet_monitoring.services.monitor.NotificationService"
        ):
            monitor = SafetyHelmetMonitor(_build_settings(), repository=_FakeRepository())
            queue = Queue(maxsize=4)
            for _ in range(4):
                queue.put(object())

            monitor._rebalance_dynamic_stride(queue)
            self.assertGreaterEqual(monitor._current_frame_stride("cam-001"), 3)

            with patch("helmet_monitoring.services.monitor.time.monotonic", return_value=31.0):
                queue = Queue(maxsize=4)
                monitor._dynamic_frame_stride["cam-001"] = 4
                monitor._stride_low_water_started["cam-001"] = 0.0
                monitor._rebalance_dynamic_stride(queue)

            self.assertEqual(monitor._current_frame_stride("cam-001"), 3)


if __name__ == "__main__":
    unittest.main()
