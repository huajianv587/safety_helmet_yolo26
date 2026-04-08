from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts.doctor import deploy_blockers


class DoctorTest(unittest.TestCase):
    def test_deploy_blockers_ignore_training_dataset_warning(self) -> None:
        report = {
            "checks": [
                {"name": "runtime_config", "status": "ready", "detail": "ok"},
                {"name": "training_dataset", "status": "warn", "detail": "optional for runtime"},
            ]
        }
        self.assertEqual(deploy_blockers(report), [])

    def test_deploy_blockers_keep_runtime_warnings_and_missing_checks(self) -> None:
        report = {
            "checks": [
                {"name": "training_dataset", "status": "warn", "detail": "optional for runtime"},
                {"name": "smtp", "status": "warn", "detail": "missing smtp"},
                {"name": "detector_model", "status": "missing", "detail": "missing model"},
            ]
        }
        blockers = deploy_blockers(report)
        self.assertEqual([item["name"] for item in blockers], ["smtp", "detector_model"])


if __name__ == "__main__":
    unittest.main()
