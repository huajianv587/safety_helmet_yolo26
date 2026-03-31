from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.services.badge_ocr import extract_employee_id, normalize_badge_text


class BadgeOcrHelpersTest(unittest.TestCase):
    def test_extract_employee_id_normalizes_spaces(self) -> None:
        self.assertEqual(extract_employee_id("emp  e 10026"), "E10026")

    def test_normalize_badge_text_collapses_whitespace(self) -> None:
        self.assertEqual(normalize_badge_text("Alice\n  Safety \r E10026"), "Alice Safety E10026")


if __name__ == "__main__":
    unittest.main()
