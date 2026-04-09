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
                    "HELMET_MONITOR_STREAM_URL": "rtmp://rtmp-gateway:1935/live/stream",
                },
                clear=False,
            ):
                settings = load_settings(config_path)

        self.assertFalse(settings.cameras[0].enabled)
        self.assertTrue(settings.cameras[1].enabled)
        self.assertEqual(settings.cameras[1].source, "rtmp://rtmp-gateway:1935/live/stream")


if __name__ == "__main__":
    unittest.main()
