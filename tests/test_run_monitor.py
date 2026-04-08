from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import scripts.run_monitor as run_monitor


class RunMonitorTest(unittest.TestCase):
    def test_parse_args_defaults_to_env_config(self) -> None:
        with patch.object(sys, "argv", ["run_monitor.py"]):
            args = run_monitor.parse_args()
        self.assertIsNone(args.config)

    def test_main_uses_env_config_when_cli_flag_is_omitted(self) -> None:
        expected = str(REPO_ROOT / "configs" / "runtime.json")

        with patch.dict(os.environ, {"HELMET_CONFIG_PATH": expected}, clear=False), patch.object(
            sys,
            "argv",
            ["run_monitor.py", "--max-frames", "2"],
        ), patch("scripts.run_monitor.load_settings") as load_settings_mock, patch(
            "scripts.run_monitor.validate_runtime_sources"
        ), patch(
            "scripts.run_monitor.SafetyHelmetMonitor"
        ) as monitor_cls:
            monitor = monitor_cls.return_value
            run_monitor.main()

        load_settings_mock.assert_called_once_with(None)
        monitor_cls.assert_called_once()
        monitor.run.assert_called_once_with(max_frames=2)

    def test_validate_runtime_sources_raises_when_local_camera_is_unavailable(self) -> None:
        camera = type("Camera", (), {"enabled": True, "camera_name": "Laptop Camera", "camera_id": "cam-local-001", "source": "0"})
        settings = type("Settings", (), {"cameras": (camera,)})

        with patch("scripts.run_monitor.local_device_access_issue", return_value="Local camera source 0 expects /dev/video0."):
            with self.assertRaises(RuntimeError) as exc:
                run_monitor.validate_runtime_sources(settings)

        self.assertIn("Laptop Camera", str(exc.exception))

    def test_validate_runtime_sources_raises_when_stream_url_is_missing(self) -> None:
        camera = type(
            "Camera",
            (),
            {
                "enabled": True,
                "camera_name": "Phone Stream Camera",
                "camera_id": "cam-rtsp-001",
                "source": "rtsp://replace-with-your-iphone-stream-url",
            },
        )
        settings = type("Settings", (), {"cameras": (camera,)})

        with self.assertRaises(RuntimeError) as exc:
            run_monitor.validate_runtime_sources(settings)

        self.assertIn("HELMET_MONITOR_STREAM_URL", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
