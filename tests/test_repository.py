from __future__ import annotations

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
from helmet_monitoring.storage.repository import build_repository


def build_settings(root: Path, *, supabase: SupabaseSettings) -> AppSettings:
    return AppSettings(
        repository_backend="supabase",
        model=ModelSettings(path=str(root / "models" / "best.pt")),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(
            snapshot_dir=str(root / "artifacts" / "captures"),
            runtime_dir=str(root / "artifacts" / "runtime"),
        ),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(registry_path=str(root / "configs" / "person_registry.json")),
        face_recognition=FaceRecognitionSettings(enabled=False),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(),
        notifications=NotificationSettings(),
        security=SecuritySettings(),
        supabase=supabase,
        cameras=(),
        config_path=root / "configs" / "runtime.json",
    )


class RepositoryTest(unittest.TestCase):
    def test_build_repository_can_fallback_to_local_when_supabase_credentials_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = build_settings(Path(temp_dir), supabase=SupabaseSettings())
            repository = build_repository(settings)
            self.assertEqual(repository.backend_name, "local")

    def test_build_repository_requires_requested_backend_when_credentials_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = build_settings(Path(temp_dir), supabase=SupabaseSettings())
            with self.assertRaisesRegex(RuntimeError, "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY"):
                build_repository(settings, require_requested_backend=True)

    def test_build_repository_requires_requested_backend_when_supabase_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = build_settings(
                Path(temp_dir),
                supabase=SupabaseSettings(url="https://example.supabase.co", service_role_key="service-role"),
            )

            class BrokenSupabaseRepository:
                backend_name = "supabase"

                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                def list_cameras(self):
                    raise RuntimeError("network down")

            with patch("helmet_monitoring.storage.repository.SupabaseAlertRepository", BrokenSupabaseRepository):
                with self.assertRaisesRegex(RuntimeError, "Supabase backend requested but is unavailable"):
                    build_repository(settings, require_requested_backend=True)


if __name__ == "__main__":
    unittest.main()
