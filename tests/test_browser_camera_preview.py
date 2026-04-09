from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

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

import scripts.browser_camera_preview as browser_camera_preview


def build_settings() -> AppSettings:
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="artifacts/training_runs/helmet_project/cpu_test3/weights/best.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(
            snapshot_dir="artifacts/captures",
            runtime_dir="artifacts/runtime",
            upload_to_supabase_storage=False,
        ),
        monitoring=MonitoringSettings(camera_retry_seconds=0.0),
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
                camera_id="cam-local-001",
                camera_name="Laptop Camera",
                source="0",
                location="Test",
                department="QA",
                enabled=True,
            ),
        ),
    )


def test_pick_camera_id_uses_enabled_local_camera() -> None:
    settings = build_settings()
    assert browser_camera_preview._pick_camera_id(settings, None) == "cam-local-001"


def test_preview_url_encodes_camera_id() -> None:
    url = browser_camera_preview._preview_url("127.0.0.1", 8765, "cam local/001")
    assert url == "http://127.0.0.1:8765/browser/cam%20local/001"


def test_main_opens_browser_and_shuts_down_server() -> None:
    settings = build_settings()
    fake_server = Mock()
    fake_handle = SimpleNamespace(server=fake_server)

    with patch.object(browser_camera_preview, "parse_args", return_value=SimpleNamespace(
        config=None,
        camera_id=None,
        port=8899,
        host="127.0.0.1",
        bind_host="0.0.0.0",
        no_browser=False,
        startup_wait=0.0,
    )), patch.object(browser_camera_preview, "load_settings", return_value=settings), patch.object(
        browser_camera_preview, "start_live_preview_server", return_value=fake_handle
    ) as start_server, patch.object(browser_camera_preview.webbrowser, "open") as open_browser, patch.object(
        browser_camera_preview.time,
        "sleep",
        side_effect=[None, KeyboardInterrupt()],
    ):
        browser_camera_preview.main()

    start_server.assert_called_once()
    open_browser.assert_called_once_with("http://127.0.0.1:8899/browser/cam-local-001", new=1)
    fake_server.shutdown.assert_called_once()
    fake_server.server_close.assert_called_once()
