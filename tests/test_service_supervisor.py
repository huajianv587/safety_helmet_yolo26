from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
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
from helmet_monitoring.core.schemas import utc_now
from helmet_monitoring.services.operations import operations_paths, write_monitor_heartbeat
from helmet_monitoring.services.service_supervisor import (
    build_managed_service_spec,
    check_managed_service_health,
    managed_service_status_path,
    mark_managed_service_state,
)


def build_settings(root: Path) -> AppSettings:
    config_path = root / "configs" / "runtime.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"model": {"path": "models/model-a.pt"}}, ensure_ascii=False), encoding="utf-8")
    (root / "configs" / "person_registry.json").write_text("[]\n", encoding="utf-8")
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="models/model-a.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(snapshot_dir=str(root / "artifacts" / "captures"), runtime_dir=str(root / "artifacts" / "runtime")),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(registry_path=str(root / "configs" / "person_registry.json")),
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
                camera_id="cam-local-001",
                camera_name="Laptop Camera",
                source="0",
                location="Safety Lab",
                department="Safety",
            ),
        ),
        config_path=config_path,
    )


class ServiceSupervisorTest(unittest.TestCase):
    def test_build_dashboard_spec_contains_streamlit_command(self) -> None:
        spec = build_managed_service_spec("dashboard", dashboard_port=8601)
        self.assertEqual(spec.service_name, "dashboard")
        self.assertIn("streamlit", spec.command)
        self.assertIn("8601", spec.command)
        self.assertEqual(spec.health_mode, "dashboard")

    def test_build_monitor_spec_contains_run_monitor_command(self) -> None:
        spec = build_managed_service_spec("monitor", config_path="configs/runtime.json")
        self.assertEqual(spec.service_name, "monitor")
        self.assertIn("scripts/run_monitor.py", spec.command)
        self.assertIn("--config", spec.command)
        self.assertEqual(spec.health_mode, "monitor")

    def test_dashboard_healthcheck_writes_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            spec = build_managed_service_spec("dashboard", repo_root=root, dashboard_port=8501)
            with patch("helmet_monitoring.services.service_supervisor.ping_dashboard", return_value=("ok", 12.5)):
                healthy, detail = check_managed_service_health(spec, settings)

            self.assertTrue(healthy)
            self.assertEqual(detail, "ok")
            status_path = managed_service_status_path(spec, settings)
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ready")

    def test_monitor_healthcheck_uses_monitor_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            spec = build_managed_service_spec("monitor", repo_root=root)
            write_monitor_heartbeat(
                settings,
                status="running",
                processed_frames=7,
                repository_backend="local",
                config_path=str(settings.config_path),
                model_path=settings.model.path,
                camera_statuses=[{"camera_id": "cam-local-001", "status": "online"}],
                repo_root=root,
            )

            healthy, detail = check_managed_service_health(spec, settings)

            self.assertTrue(healthy)
            self.assertIn("ok", detail)

    def test_mark_managed_service_state_marks_monitor_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            spec = build_managed_service_spec("monitor", repo_root=root)

            mark_managed_service_state(spec, settings, status="stopped", detail="Service stopped by operator.")

            status_path = operations_paths(settings)["monitor_health"]
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "stopped")
            self.assertIn("operator", payload["detail"])


if __name__ == "__main__":
    unittest.main()
