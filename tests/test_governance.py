from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import (
    AppSettings,
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
from helmet_monitoring.core.schemas import AlertCandidate
from helmet_monitoring.services.governance import FalsePositiveGovernance
from helmet_monitoring.core.config import CameraSettings


def build_settings() -> AppSettings:
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="artifacts/model.pt"),
        event_rules=EventRuleSettings(min_confidence_for_alert=0.5),
        persistence=PersistenceSettings(),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(),
        face_recognition=FaceRecognitionSettings(enabled=False),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(min_bbox_area=5000, whitelist_camera_ids=("cam-whitelist",)),
        clip=ClipSettings(),
        notifications=NotificationSettings(),
        security=SecuritySettings(),
        supabase=SupabaseSettings(),
        cameras=(),
        config_path=REPO_ROOT / "configs" / "runtime.json",
    )


class GovernanceTest(unittest.TestCase):
    def test_small_target_is_filtered(self) -> None:
        settings = build_settings()
        service = FalsePositiveGovernance(settings)
        camera = CameraSettings(
            camera_id="cam-1",
            camera_name="Demo",
            source="0",
            location="Demo",
            department="Safety",
        )
        candidate = AlertCandidate(
            event_key="cam-1:1",
            camera_id="cam-1",
            confidence=0.9,
            label="no_helmet",
            bbox={"x1": 10, "y1": 10, "x2": 50, "y2": 50},
            first_seen_at=datetime.now(tz=timezone.utc),
            triggered_at=datetime.now(tz=timezone.utc),
            consecutive_hits=6,
        )
        decision = service.evaluate(camera, candidate, datetime.now(tz=timezone.utc))
        self.assertFalse(decision.allow)

    def test_whitelisted_camera_is_skipped(self) -> None:
        settings = build_settings()
        service = FalsePositiveGovernance(settings)
        camera = CameraSettings(
            camera_id="cam-whitelist",
            camera_name="Demo",
            source="0",
            location="Demo",
            department="Safety",
        )
        candidate = AlertCandidate(
            event_key="cam-1:1",
            camera_id="cam-whitelist",
            confidence=0.9,
            label="no_helmet",
            bbox={"x1": 10, "y1": 10, "x2": 110, "y2": 150},
            first_seen_at=datetime.now(tz=timezone.utc),
            triggered_at=datetime.now(tz=timezone.utc),
            consecutive_hits=6,
        )
        decision = service.evaluate(camera, candidate, datetime.now(tz=timezone.utc))
        self.assertFalse(decision.allow)


if __name__ == "__main__":
    unittest.main()
