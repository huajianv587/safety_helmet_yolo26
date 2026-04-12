from __future__ import annotations

import sys
import tempfile
import unittest
import json
from dataclasses import replace
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
from helmet_monitoring.services.auth import hash_password
from helmet_monitoring.services.readiness import collect_readiness_report, ensure_workspace_scaffold


def isolated_auth_env(root: Path) -> dict[str, str]:
    return {
        "HELMET_AUTH_USERS_FILE": str(root / "artifacts" / "runtime" / "ops" / "auth_users.json"),
        "HELMET_AUTH_ATTEMPTS_FILE": str(root / "artifacts" / "runtime" / "ops" / "auth_attempts.json"),
    }


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
            with patch.dict("os.environ", isolated_auth_env(root), clear=False):
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
            with patch.dict("os.environ", isolated_auth_env(root), clear=False):
                report = collect_readiness_report(settings, repo_root=root)
            checks = {item["name"]: item for item in report["checks"]}
            self.assertIn("storage_privacy", checks)
            self.assertEqual(checks["storage_privacy"]["status"], "warn")

    def test_collect_readiness_report_warns_when_identity_delivery_extension_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            settings = replace(
                settings,
                repository_backend="supabase",
                supabase=SupabaseSettings(url="https://example.supabase.co", service_role_key="service-role"),
            )
            ensure_workspace_scaffold(settings, repo_root=root)
            with patch.dict("os.environ", isolated_auth_env(root), clear=False), patch(
                "helmet_monitoring.services.readiness._identity_delivery_extension_ready",
                return_value=False,
            ):
                report = collect_readiness_report(settings, repo_root=root)
            checks = {item["name"]: item for item in report["checks"]}
            self.assertIn("identity_delivery_extension", checks)
            self.assertEqual(checks["identity_delivery_extension"]["status"], "warn")
            self.assertTrue(
                any("supabase_identity_delivery_extension.sql" in item for item in report["next_actions"])
            )

    def test_collect_readiness_report_warns_when_supabase_identity_delivery_columns_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            settings = replace(
                settings,
                repository_backend="supabase",
                supabase=SupabaseSettings(url="https://example.supabase.co", service_role_key="service-role"),
            )
            ensure_workspace_scaffold(settings, repo_root=root)
            with patch.dict("os.environ", isolated_auth_env(root), clear=False), patch(
                "helmet_monitoring.services.readiness._identity_delivery_extension_ready",
                return_value=False,
            ):
                report = collect_readiness_report(settings, repo_root=root)
            checks = {item["name"]: item for item in report["checks"]}
            self.assertIn("identity_delivery_extension", checks)
            self.assertEqual(checks["identity_delivery_extension"]["status"], "warn")
            self.assertTrue(
                any("supabase_identity_delivery_extension.sql" in item for item in report["next_actions"])
            )

    def test_collect_readiness_report_requires_trusted_console_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "configs").mkdir(parents=True, exist_ok=True)
            (root / "configs" / "runtime.json").write_text("{}", encoding="utf-8")
            (root / "app.py").write_text("pass\n", encoding="utf-8")
            settings = build_settings(root)
            with patch.dict("os.environ", isolated_auth_env(root), clear=False):
                report = collect_readiness_report(settings, repo_root=root)
            checks = {item["name"]: item for item in report["checks"]}
            self.assertIn("console_auth", checks)
            self.assertEqual(checks["console_auth"]["status"], "missing")

    def test_collect_readiness_report_accepts_configured_console_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "configs").mkdir(parents=True, exist_ok=True)
            (root / "configs" / "runtime.json").write_text("{}", encoding="utf-8")
            (root / "app.py").write_text("pass\n", encoding="utf-8")
            settings = build_settings(root)
            env = {
                **isolated_auth_env(root),
                "HELMET_AUTH_ADMIN_USERNAME": "admin",
                "HELMET_AUTH_ADMIN_PASSWORD_HASH": hash_password("AdminPass!2026"),
            }
            with patch.dict("os.environ", env, clear=False):
                report = collect_readiness_report(settings, repo_root=root)
            checks = {item["name"]: item for item in report["checks"]}
            self.assertIn("console_auth", checks)
            self.assertEqual(checks["console_auth"]["status"], "ready")

    def test_collect_readiness_report_warns_when_runtime_config_contains_inline_camera_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "configs").mkdir(parents=True, exist_ok=True)
            (root / "configs" / "runtime.json").write_text(
                (
                    '{"cameras": [{"camera_id": "cam-1", "source": "rtsp://admin:secret@example.com/live"}]}'
                ),
                encoding="utf-8",
            )
            (root / "app.py").write_text("pass\n", encoding="utf-8")
            settings = build_settings(root)
            settings = replace(
                settings,
                cameras=(
                    CameraSettings(
                        camera_id="cam-1",
                        camera_name="Camera 1",
                        source="rtsp://admin:secret@example.com/live",
                        location="Lab",
                        department="QA",
                    ),
                ),
            )
            with patch.dict("os.environ", isolated_auth_env(root), clear=False):
                report = collect_readiness_report(settings, repo_root=root)
            checks = {item["name"]: item for item in report["checks"]}
            self.assertIn("camera_secret_refs", checks)
            self.assertEqual(checks["camera_secret_refs"]["status"], "warn")

    def test_collect_readiness_report_exposes_identity_coverage_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "configs").mkdir(parents=True, exist_ok=True)
            (root / "configs" / "runtime.json").write_text("{}", encoding="utf-8")
            (root / "app.py").write_text("pass\n", encoding="utf-8")
            registry_path = root / "configs" / "person_registry.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "person_id": "person-001",
                            "name": "Shift Lead",
                            "department": "Safety",
                            "aliases": ["Lead A"],
                            "badge_keywords": ["SHIFT", "LEAD"],
                            "default_camera_ids": ["cam-local-001"],
                            "status": "active",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            face_dir = root / "artifacts" / "identity" / "faces" / "person-001"
            face_dir.mkdir(parents=True, exist_ok=True)
            (face_dir / "profile.jpg").write_bytes(b"fake")
            settings = replace(
                build_settings(root),
                face_recognition=replace(build_settings(root).face_recognition, enabled=True, face_profile_dir=str(root / "artifacts" / "identity" / "faces")),
            )
            settings = replace(
                settings,
                cameras=(
                    CameraSettings(
                        camera_id="cam-local-001",
                        camera_name="Laptop Camera",
                        source="0",
                        location="Lab",
                        department="Safety",
                    ),
                ),
            )
            with patch.dict("os.environ", isolated_auth_env(root), clear=False):
                report = collect_readiness_report(settings, repo_root=root)
            checks = {item["name"]: item for item in report["checks"]}
            self.assertEqual(checks["identity_coverage"]["status"], "ready")
            self.assertEqual(checks["identity_face_samples"]["status"], "ready")
            self.assertEqual(report["identity"]["people_with_camera_bindings"], 1)
            self.assertEqual(report["identity"]["people_with_face_samples"], 1)


if __name__ == "__main__":
    unittest.main()
