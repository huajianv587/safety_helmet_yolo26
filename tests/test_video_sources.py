from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import helmet_monitoring.services.video_sources as video_sources
from helmet_monitoring.services.video_sources import (
    CameraStream,
    is_remote_stream_source,
    local_device_access_issue,
    local_device_open_failure,
    local_device_path,
)


class VideoSourceTest(unittest.TestCase):
    def test_local_device_path_for_numeric_source(self) -> None:
        self.assertEqual(local_device_path("0"), Path("/dev/video0"))
        self.assertIsNone(local_device_path("rtsp://example"))
        self.assertTrue(is_remote_stream_source("rtsp://example"))

    def test_local_device_access_issue_requires_device_in_container(self) -> None:
        with patch("helmet_monitoring.services.video_sources.Path.exists", side_effect=[True, False]):
            issue = local_device_access_issue("0")
        self.assertIsNotNone(issue)
        self.assertIn("/dev/video0", issue or "")

    def test_camera_stream_open_short_circuits_when_local_device_is_missing(self) -> None:
        camera = type("Camera", (), {"source": "0"})
        stream = CameraStream(camera, retry_seconds=0.0)

        with patch("helmet_monitoring.services.video_sources.local_device_access_issue", return_value="camera missing"), patch(
            "helmet_monitoring.services.video_sources.cv2.VideoCapture"
        ) as capture_cls:
            opened = stream.open()

        self.assertFalse(opened)
        self.assertEqual(stream.last_error, "camera missing")
        capture_cls.assert_not_called()

    def test_local_device_open_failure_is_explicit(self) -> None:
        message = local_device_open_failure("0")
        self.assertIn("/dev/video0", message)
        self.assertIn("run the monitor on the host", message)

    def test_remote_stream_open_applies_low_buffer_settings(self) -> None:
        camera = type("Camera", (), {"source": "rtsp://example/stream"})
        stream = CameraStream(camera, retry_seconds=0.0)

        class FakeCapture:
            def __init__(self) -> None:
                self.set_calls: list[tuple[int, float]] = []
                self.read_count = 0

            def isOpened(self) -> bool:
                return True

            def set(self, prop_id: int, value: float) -> bool:
                self.set_calls.append((prop_id, value))
                return True

            def read(self):
                self.read_count += 1
                return True, np.zeros((32, 32, 3), dtype=np.uint8)

            def release(self) -> None:
                return None

        created: list[tuple[tuple[object, ...], FakeCapture]] = []

        def fake_capture(*args):
            capture = FakeCapture()
            created.append((args, capture))
            return capture

        with patch("helmet_monitoring.services.video_sources.cv2.VideoCapture", side_effect=fake_capture):
            opened = stream.open()

        self.assertTrue(opened)
        self.assertGreaterEqual(len(created), 1)
        self.assertEqual(created[0][0][0], "rtsp://example/stream")
        self.assertEqual(len(created[0][0]), 1)

        set_props = {prop_id for prop_id, _ in created[0][1].set_calls}
        for prop_name in ("CAP_PROP_BUFFERSIZE", "CAP_PROP_OPEN_TIMEOUT_MSEC", "CAP_PROP_READ_TIMEOUT_MSEC"):
            prop_id = getattr(video_sources.cv2, prop_name, None)
            if prop_id is not None:
                self.assertIn(prop_id, set_props)
        stream.release()


if __name__ == "__main__":
    unittest.main()
