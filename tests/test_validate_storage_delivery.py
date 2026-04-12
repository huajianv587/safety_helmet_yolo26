from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import scripts.validate_storage_delivery as validate_storage_delivery
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
        persistence=PersistenceSettings(
            snapshot_dir=str(root / "artifacts" / "captures"),
            runtime_dir=str(root / "artifacts" / "runtime"),
            upload_to_supabase_storage=True,
        ),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(registry_path=str(registry_path)),
        face_recognition=FaceRecognitionSettings(enabled=False),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(),
        notifications=NotificationSettings(enabled=False, email_enabled=False),
        security=SecuritySettings(),
        supabase=SupabaseSettings(url="https://example.supabase.co", service_role_key="service-role", storage_bucket="alerts"),
        cameras=(
            CameraSettings(
                camera_id="cam-local-001",
                camera_name="Laptop Camera",
                source="0",
                location="Safety Lab",
                department="Safety",
                enabled=True,
            ),
        ),
        config_path=root / "configs" / "runtime.json",
    )


class _FakeBucketApi:
    def __init__(self) -> None:
        self.removed: list[list[str]] = []

    def remove(self, paths: list[str]) -> None:
        self.removed.append(paths)


class _FakeStorageApi:
    def __init__(self, bucket_api: _FakeBucketApi) -> None:
        self.bucket_api = bucket_api

    def from_(self, _bucket_name: str) -> _FakeBucketApi:
        return self.bucket_api


class _FakeClient:
    def __init__(self, bucket_api: _FakeBucketApi) -> None:
        self.storage = _FakeStorageApi(bucket_api)


class _FakeStore:
    def __init__(self, _settings) -> None:
        self.bucket_api = _FakeBucketApi()
        self.client = _FakeClient(self.bucket_api)

    def _remote_object_path(self, camera_id, artifact_id, _created_at, category, extension):
        return f"{category}/{camera_id}/{artifact_id}{extension}"

    def save_bytes(self, camera_id, file_bytes, artifact_id, _created_at, *, category, extension, content_type):
        self.saved = {
            "camera_id": camera_id,
            "artifact_id": artifact_id,
            "category": category,
            "extension": extension,
            "content_type": content_type,
            "size": len(file_bytes),
        }
        temp_dir = Path(tempfile.gettempdir())
        local_path = temp_dir / f"{artifact_id}{extension}"
        local_path.write_bytes(file_bytes)
        return str(local_path), "https://example.test/signed-url"


class ValidateStorageDeliveryTest(unittest.TestCase):
    def test_run_validation_uploads_fetches_and_deletes_remote_object(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = build_settings(Path(temp_dir))
            fake_store = _FakeStore(settings)

            class _FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return b"downloaded"

            with patch("scripts.validate_storage_delivery.EvidenceStore", return_value=fake_store), patch(
                "scripts.validate_storage_delivery._sample_bytes", return_value=b"fake-image"
            ), patch("scripts.validate_storage_delivery.urllib.request.urlopen", return_value=_FakeResponse()):
                result = validate_storage_delivery.run_validation(settings, require_success=True)

        self.assertEqual(result["camera_id"], "cam-local-001")
        self.assertTrue(result["access_url_present"])
        self.assertEqual(result["downloaded_bytes"], len(b"downloaded"))
        self.assertTrue(result["remote_deleted"])
        self.assertTrue(result["local_deleted"])
        self.assertEqual(fake_store.bucket_api.removed[0][0], result["object_path"])


if __name__ == "__main__":
    unittest.main()
