from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
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
from helmet_monitoring.services.readiness import collect_readiness_report, ensure_workspace_scaffold


def build_settings(root: Path) -> AppSettings:
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path=str(root / "models" / "missing.pt")),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(
            snapshot_dir=str(root / "artifacts" / "captures"),
            runtime_dir=str(root / "artifacts" / "runtime"),
        ),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(registry_path=str(root / "configs" / "person_registry.json")),
        face_recognition=FaceRecognitionSettings(
            enabled=False,
            face_profile_dir=str(root / "artifacts" / "identity" / "faces"),
        ),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(),
        notifications=NotificationSettings(),
        security=SecuritySettings(),
        supabase=SupabaseSettings(),
        cameras=(),
        config_path=root / "configs" / "runtime.json",
    )


class ReadinessTest(unittest.TestCase):
    def test_ensure_workspace_scaffold_creates_expected_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            created = ensure_workspace_scaffold(settings, repo_root=root)
            self.assertTrue(created)
            self.assertTrue((root / "artifacts" / "captures").exists())
            self.assertTrue((root / "artifacts" / "runtime").exists())
            self.assertTrue((root / "data" / "hard_cases" / "false_positive").exists())
            self.assertTrue((root / "artifacts" / "identity" / "review").exists())

    def test_collect_readiness_report_flags_missing_model_and_camera(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            ensure_workspace_scaffold(settings, repo_root=root)
            report = collect_readiness_report(settings, repo_root=root)
            self.assertFalse(report["model"]["exists"])
            self.assertEqual(report["cameras"]["enabled"], 0)
            self.assertTrue(any(item["status"] == "missing" for item in report["checks"]))
            self.assertTrue(report["next_actions"])

    def test_collect_readiness_report_warns_when_supabase_storage_is_public(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            settings = replace(
                settings,
                repository_backend="supabase",
                security=replace(settings.security, use_private_bucket=False),
                supabase=SupabaseSettings(url="https://example.supabase.co", service_role_key="service-role"),
            )
            ensure_workspace_scaffold(settings, repo_root=root)
            report = collect_readiness_report(settings, repo_root=root)
            checks = {item["name"]: item for item in report["checks"]}
            self.assertIn("storage_privacy", checks)
            self.assertEqual(checks["storage_privacy"]["status"], "warn")


if __name__ == "__main__":
    unittest.main()
