from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.services.workflow import AlertWorkflowService
from helmet_monitoring.storage.repository import LocalAlertRepository


class WorkflowTest(unittest.TestCase):
    def test_false_positive_creates_hard_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = LocalAlertRepository(Path(temp_dir))
            alert = {
                "alert_id": "alert-001",
                "event_no": "AL-001",
                "snapshot_path": "snap.jpg",
                "snapshot_url": None,
                "clip_path": None,
                "clip_url": None,
                "created_at": "2026-03-31T00:00:00+00:00",
            }
            repo.insert_alert(alert)
            service = AlertWorkflowService(repo)
            service.update_status(
                alert,
                actor="tester",
                actor_role="admin",
                new_status="false_positive",
                note="bad angle",
            )
            updated = repo.get_alert("alert-001")
            hard_cases = repo.list_hard_cases(limit=10)
            self.assertEqual(updated["status"], "false_positive")
            self.assertTrue(updated["false_positive"])
            self.assertEqual(len(hard_cases), 1)


if __name__ == "__main__":
    unittest.main()
