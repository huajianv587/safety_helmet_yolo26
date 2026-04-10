from __future__ import annotations

import sys
import tempfile
import unittest
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
from helmet_monitoring.core.schemas import AlertRecord, utc_now
from helmet_monitoring.services.notifier import NotificationService
from helmet_monitoring.storage.repository import LocalAlertRepository


def build_settings(runtime_dir: Path, *, notifications: NotificationSettings | None = None) -> AppSettings:
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="artifacts/model.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(snapshot_dir=str(runtime_dir / "captures"), runtime_dir=str(runtime_dir)),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(),
        face_recognition=FaceRecognitionSettings(enabled=False),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(),
        notifications=notifications or NotificationSettings(enabled=True, email_enabled=True),
        security=SecuritySettings(),
        supabase=SupabaseSettings(),
        cameras=(),
        config_path=runtime_dir / "runtime.json",
    )


def build_alert() -> AlertRecord:
    observed_at = utc_now()
    return AlertRecord(
        alert_id="alert-001",
        event_key="cam-local-001:track-1",
        event_no="SMK-20260410-TEST01",
        camera_id="cam-local-001",
        camera_name="Laptop Camera",
        location="Safety Lab",
        department="Safety",
        violation_type="no_helmet",
        risk_level="high",
        confidence=0.91,
        snapshot_path="artifacts/captures/alert-001.jpg",
        snapshot_url=None,
        status="pending",
        bbox={"x1": 1, "y1": 2, "x2": 3, "y2": 4},
        model_name="best.pt",
        person_id=None,
        person_name="Unknown",
        employee_id=None,
        team=None,
        role=None,
        phone=None,
        identity_status="unresolved",
        identity_source="none",
        created_at=observed_at,
    )


class NotifierTest(unittest.TestCase):
    def test_simulate_alert_email_writes_dry_run_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            repository = LocalAlertRepository(runtime_dir)
            settings = build_settings(
                runtime_dir,
                notifications=NotificationSettings(
                    enabled=True,
                    email_enabled=True,
                    smtp_from_email="alerts@example.com",
                ),
            )
            notifier = NotificationService(settings, repository)

            notifier.simulate_alert_email(build_alert(), ("ops@example.com",), reason="smoke_product")
            logs = repository.list_notification_logs(limit=10)

        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["status"], "dry_run")
        self.assertEqual(logs[0]["recipient"], "ops@example.com")
        self.assertIn("smoke_product", logs[0]["error_message"])
        self.assertEqual(logs[0]["payload"]["mode"], "smoke_product")
        self.assertIn("Event No:", logs[0]["payload"]["body_preview"])

    def test_send_alert_email_logs_skipped_when_notifications_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            repository = LocalAlertRepository(runtime_dir)
            settings = build_settings(
                runtime_dir,
                notifications=NotificationSettings(
                    enabled=False,
                    email_enabled=False,
                    smtp_from_email="alerts@example.com",
                ),
            )
            notifier = NotificationService(settings, repository)

            notifier.send_alert_email(build_alert(), ("ops@example.com",))
            logs = repository.list_notification_logs(limit=10)

        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["status"], "skipped")
        self.assertIn("disabled", logs[0]["error_message"].lower())


if __name__ == "__main__":
    unittest.main()
