from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.utils.image_io import read_image, write_image


class ImageIoTest(unittest.TestCase):
    def test_read_and_write_image_support_non_ascii_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "中文目录" / "样本.png"
            frame = np.zeros((18, 24, 3), dtype=np.uint8)
            frame[:, :, 1] = 180

            self.assertTrue(write_image(target, frame))

            restored = read_image(target)
            self.assertIsNotNone(restored)
            self.assertEqual(restored.shape, frame.shape)
            self.assertTrue(np.array_equal(restored, frame))

    def test_read_image_returns_none_when_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "不存在" / "missing.jpg"
            self.assertIsNone(read_image(missing))


if __name__ == "__main__":
    unittest.main()

