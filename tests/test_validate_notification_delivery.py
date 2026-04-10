from __future__ import annotations

import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import scripts.validate_notification_delivery as validate_notification_delivery
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


def build_settings(root: Path) -> AppSettings:
    registry_path = root / "configs" / "person_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("[]\n", encoding="utf-8")
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="artifacts/model.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(snapshot_dir=str(root / "artifacts" / "captures"), runtime_dir=str(root / "artifacts" / "runtime")),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(registry_path=str(registry_path)),
        face_recognition=FaceRecognitionSettings(enabled=False),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(),
        notifications=NotificationSettings(enabled=True, email_enabled=True, smtp_from_email="alerts@example.com"),
        security=SecuritySettings(),
        supabase=SupabaseSettings(),
        cameras=(
            CameraSettings(
                camera_id="cam-local-001",
                camera_name="Laptop Camera",
                source="0",
                location="Safety Lab",
                department="Safety",
            ),
        ),
        config_path=root / "configs" / "runtime.json",
    )


class ValidateNotificationDeliveryTest(unittest.TestCase):
    def test_run_validation_dry_run_creates_notification_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = build_settings(Path(temp_dir))
            args = Namespace(
                strict_runtime=False,
                mode="dry_run",
                recipient=["ops@example.com"],
                camera_id=None,
                require_success=False,
            )

            result = validate_notification_delivery.run_validation(settings, args)

        self.assertEqual(result["notification_mode"], "dry_run")
        self.assertEqual(result["notifications"], 1)
        self.assertIn("dry_run", str(result["notification_statuses"]))


if __name__ == "__main__":
    unittest.main()
