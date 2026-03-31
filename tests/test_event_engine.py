from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import EventRuleSettings
from helmet_monitoring.core.schemas import DetectionRecord, utc_now
from helmet_monitoring.services.event_engine import ViolationEventEngine


class ViolationEventEngineTest(unittest.TestCase):
    def test_alert_requires_consecutive_hits_and_dedupes(self) -> None:
        engine = ViolationEventEngine(
            EventRuleSettings(
                alert_frames=3,
                dedupe_seconds=30,
                match_distance_pixels=50,
                max_track_age_seconds=5.0,
                min_confidence_for_alert=0.5,
            )
        )
        base_time = utc_now()
        detection = DetectionRecord(
            class_id=1,
            label="no_helmet",
            confidence=0.9,
            x1=10,
            y1=10,
            x2=50,
            y2=70,
            is_violation=True,
        )

        self.assertEqual(engine.evaluate("cam-1", [detection], base_time), [])
        self.assertEqual(engine.evaluate("cam-1", [detection], base_time + timedelta(seconds=1)), [])
        alerts = engine.evaluate("cam-1", [detection], base_time + timedelta(seconds=2))
        self.assertEqual(len(alerts), 1)

        deduped = engine.evaluate("cam-1", [detection], base_time + timedelta(seconds=3))
        self.assertEqual(deduped, [])


if __name__ == "__main__":
    unittest.main()

