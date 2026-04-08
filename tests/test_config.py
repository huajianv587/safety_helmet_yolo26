from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import _resolve_env_placeholder


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


if __name__ == "__main__":
    unittest.main()
