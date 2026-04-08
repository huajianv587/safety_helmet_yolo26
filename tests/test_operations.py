from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import timedelta
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
from helmet_monitoring.core.schemas import utc_now
from helmet_monitoring.services.operations import (
    create_backup,
    create_release_snapshot,
    operations_paths,
    restore_backup,
    rollback_release,
    service_health_report,
    write_monitor_heartbeat,
)


def build_settings(root: Path) -> AppSettings:
    config_path = root / "configs" / "runtime.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"model": {"path": "models/model-a.pt"}}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "configs" / "person_registry.json").write_text("[]\n", encoding="utf-8")
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "models" / "model-a.pt").write_text("baseline-model", encoding="utf-8")
    (root / "models" / "model-b.pt").write_text("candidate-model", encoding="utf-8")
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="models/model-a.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(
            snapshot_dir=str(root / "artifacts" / "captures"),
            runtime_dir=str(root / "artifacts" / "runtime"),
            upload_to_supabase_storage=False,
        ),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(registry_path=str(root / "configs" / "person_registry.json")),
        face_recognition=FaceRecognitionSettings(enabled=False, face_profile_dir=str(root / "artifacts" / "identity" / "faces")),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(),
        notifications=NotificationSettings(enabled=False, email_enabled=False),
        security=SecuritySettings(),
        supabase=SupabaseSettings(),
        cameras=(),
        config_path=config_path,
    )


class OperationsTest(unittest.TestCase):
    def test_monitor_heartbeat_reports_ready_and_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            write_monitor_heartbeat(
                settings,
                status="running",
                processed_frames=12,
                repository_backend="local",
                config_path=str(settings.config_path),
                model_path="models/model-a.pt",
                camera_statuses=[{"camera_id": "cam-1", "status": "online"}],
                repo_root=root,
            )
            monitor_health = operations_paths(settings, repo_root=root)["monitor_health"]
            ready = service_health_report(monitor_health, service_name="monitor", stale_after_seconds=90)
            self.assertEqual(ready["status"], "ready")

            stale = service_health_report(
                monitor_health,
                service_name="monitor",
                stale_after_seconds=1,
                now=utc_now() + timedelta(seconds=5),
            )
            self.assertEqual(stale["status"], "stale")

    def test_backup_and_restore_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            runtime_file = root / "artifacts" / "runtime" / "state.json"
            runtime_file.parent.mkdir(parents=True, exist_ok=True)
            runtime_file.write_text('{"value":"before"}\n', encoding="utf-8")

            record = create_backup(settings, backup_name="unit-backup", repo_root=root)
            runtime_file.write_text('{"value":"after"}\n', encoding="utf-8")
            restore_backup(settings, record["backup_path"], repo_root=root)

            self.assertIn('"before"', runtime_file.read_text(encoding="utf-8"))
            backup_registry = json.loads(operations_paths(settings, repo_root=root)["backup_registry"].read_text(encoding="utf-8"))
            self.assertEqual(len(backup_registry["backups"]), 1)

    def test_release_snapshot_and_rollback_restore_previous_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            create_release_snapshot(settings, release_name="baseline", activate=True, repo_root=root)

            settings.config_path.write_text(
                json.dumps({"model": {"path": "models/model-b.pt"}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            create_release_snapshot(settings, release_name="candidate", activate=True, repo_root=root)
            rollback_release(settings, steps=1, repo_root=root)

            restored = json.loads(settings.config_path.read_text(encoding="utf-8"))
            self.assertEqual(restored["model"]["path"], "models/model-a.pt")


if __name__ == "__main__":
    unittest.main()
