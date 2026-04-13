from __future__ import annotations

import os
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import _resolve_env_placeholder, load_settings


class ConfigTest(unittest.TestCase):
    def test_resolve_env_placeholder_uses_env_value(self) -> None:
        with patch.dict(os.environ, {"HELMET_MONITOR_STREAM_URL": "rtmp://rtmp-gateway:1935/live/stream"}, clear=False):
            self.assertEqual(
                _resolve_env_placeholder("${HELMET_MONITOR_STREAM_URL:rtmp://fallback/live/stream}"),
                "rtmp://rtmp-gateway:1935/live/stream",
            )

    def test_resolve_env_placeholder_uses_fallback_when_env_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _resolve_env_placeholder("${HELMET_MONITOR_STREAM_URL:rtmp://fallback/live/stream}"),
                "rtmp://fallback/live/stream",
            )

    def test_load_settings_forces_laptop_camera_when_env_flag_true(self) -> None:
        runtime_payload = {
            "repository_backend": "supabase",
            "model": {"path": "artifacts/models/example.pt"},
            "cameras": [
                {
                    "camera_id": "cam-local-001",
                    "camera_name": "Laptop Camera",
                    "source": "0",
                    "enabled": False,
                    "location": "Local Workstation",
                    "department": "Safety",
                },
                {
                    "camera_id": "cam-rtsp-001",
                    "camera_name": "Phone Stream Camera",
                    "source": "${HELMET_MONITOR_STREAM_URL:rtmp://fallback/live/stream}",
                    "enabled": True,
                    "location": "Factory RTSP Zone",
                    "department": "Safety",
                },
            ],
        }

        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "runtime.json"
            config_path.write_text(json.dumps(runtime_payload, ensure_ascii=False), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "camera_use_laptop_camera": "true",
                    "HELMET_MONITOR_STREAM_URL": "rtmp://rtmp-gateway:1935/live/stream",
                },
                clear=False,
            ):
                settings = load_settings(config_path)

        self.assertTrue(settings.cameras[0].enabled)
        self.assertEqual(settings.cameras[0].source, "0")
        self.assertFalse(settings.cameras[1].enabled)

    def test_load_settings_keeps_runtime_camera_selection_when_env_flag_false(self) -> None:
        runtime_payload = {
            "repository_backend": "supabase",
            "model": {"path": "artifacts/models/example.pt"},
            "cameras": [
                {
                    "camera_id": "cam-local-001",
                    "camera_name": "Laptop Camera",
                    "source": "0",
                    "enabled": False,
                    "location": "Local Workstation",
                    "department": "Safety",
                },
                {
                    "camera_id": "cam-rtsp-001",
                    "camera_name": "Phone Stream Camera",
                    "source": "${HELMET_MONITOR_STREAM_URL:rtmp://fallback/live/stream}",
                    "enabled": True,
                    "location": "Factory RTSP Zone",
                    "department": "Safety",
                },
            ],
        }

        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "runtime.json"
            config_path.write_text(json.dumps(runtime_payload, ensure_ascii=False), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "camera_use_laptop_camera": "false",
                    "CAMERA_AUTO_SELECT_SOURCE": "false",
                    "HELMET_MONITOR_STREAM_URL": "rtmp://rtmp-gateway:1935/live/stream",
                },
                clear=False,
            ):
                settings = load_settings(config_path)

        self.assertFalse(settings.cameras[0].enabled)
        self.assertTrue(settings.cameras[1].enabled)
        self.assertEqual(settings.cameras[1].source, "rtmp://rtmp-gateway:1935/live/stream")

    def test_load_settings_auto_falls_back_to_local_when_remote_source_is_default_placeholder(self) -> None:
        runtime_payload = {
            "repository_backend": "supabase",
            "model": {"path": "artifacts/models/example.pt"},
            "cameras": [
                {
                    "camera_id": "cam-local-001",
                    "camera_name": "Laptop Camera",
                    "source": "0",
                    "enabled": False,
                    "location": "Local Workstation",
                    "department": "Safety",
                },
                {
                    "camera_id": "cam-rtsp-001",
                    "camera_name": "Factory Camera",
                    "source": "${HELMET_MONITOR_STREAM_URL:rtmp://rtmp-gateway:1935/live/stream}",
                    "enabled": True,
                    "location": "Factory RTSP Zone",
                    "department": "Safety",
                },
            ],
        }

        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "runtime.json"
            config_path.write_text(json.dumps(runtime_payload, ensure_ascii=False), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "camera_use_laptop_camera": "false",
                },
                clear=False,
            ):
                settings = load_settings(config_path)

        self.assertTrue(settings.cameras[0].enabled)
        self.assertFalse(settings.cameras[1].enabled)

    def test_load_settings_auto_prefers_remote_when_custom_stream_url_is_configured(self) -> None:
        runtime_payload = {
            "repository_backend": "supabase",
            "model": {"path": "artifacts/models/example.pt"},
            "cameras": [
                {
                    "camera_id": "cam-local-001",
                    "camera_name": "Laptop Camera",
                    "source": "0",
                    "enabled": True,
                    "location": "Local Workstation",
                    "department": "Safety",
                },
                {
                    "camera_id": "cam-rtsp-001",
                    "camera_name": "Factory Camera",
                    "source": "${HELMET_MONITOR_STREAM_URL:rtsp://replace-with-your-camera-url}",
                    "enabled": True,
                    "location": "Factory RTSP Zone",
                    "department": "Safety",
                },
            ],
        }

        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "runtime.json"
            config_path.write_text(json.dumps(runtime_payload, ensure_ascii=False), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "camera_use_laptop_camera": "false",
                    "HELMET_MONITOR_STREAM_URL": "rtsp://192.168.1.88:554/Streaming/Channels/101",
                },
                clear=False,
            ):
                settings = load_settings(config_path)

        self.assertFalse(settings.cameras[0].enabled)
        self.assertTrue(settings.cameras[1].enabled)
        self.assertEqual(settings.cameras[1].source, "rtsp://192.168.1.88:554/Streaming/Channels/101")

    def test_load_settings_discovers_additional_numbered_stream_urls_from_env(self) -> None:
        runtime_payload = {
            "repository_backend": "supabase",
            "model": {"path": "artifacts/models/example.pt"},
            "cameras": [
                {
                    "camera_id": "cam-local-001",
                    "camera_name": "Laptop Camera",
                    "source": "0",
                    "enabled": True,
                    "location": "Local Workstation",
                    "department": "Safety",
                },
                {
                    "camera_id": "cam-rtsp-001",
                    "camera_name": "Commercial RTSP Camera",
                    "source": "${HELMET_MONITOR_STREAM_URL:rtsp://replace-with-your-camera-url}",
                    "enabled": True,
                    "location": "Factory Camera Zone",
                    "department": "Safety",
                },
            ],
        }

        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "runtime.json"
            config_path.write_text(json.dumps(runtime_payload, ensure_ascii=False), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "camera_use_laptop_camera": "false",
                    "HELMET_MONITOR_STREAM_URL_1": "rtsp://192.168.1.101:554/Streaming/Channels/101",
                    "HELMET_MONITOR_STREAM_URL_2": "rtsp://192.168.1.102:554/Streaming/Channels/101",
                    "HELMET_CAMERA_NAME_2": "Workshop Camera 2",
                    "HELMET_CAMERA_LOCATION_2": "Assembly Line B",
                },
                clear=False,
            ):
                settings = load_settings(config_path)

        self.assertEqual(len(settings.cameras), 3)
        self.assertFalse(settings.cameras[0].enabled)
        self.assertEqual(settings.cameras[1].camera_id, "cam-rtsp-001")
        self.assertEqual(settings.cameras[1].source, "rtsp://192.168.1.101:554/Streaming/Channels/101")
        self.assertTrue(settings.cameras[1].enabled)
        self.assertEqual(settings.cameras[2].camera_id, "cam-rtsp-002")
        self.assertEqual(settings.cameras[2].camera_name, "Workshop Camera 2")
        self.assertEqual(settings.cameras[2].location, "Assembly Line B")
        self.assertEqual(settings.cameras[2].source, "rtsp://192.168.1.102:554/Streaming/Channels/101")
        self.assertTrue(settings.cameras[2].enabled)


if __name__ == "__main__":
    unittest.main()
