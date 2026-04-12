from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.enrich_identity_registry as enrich_identity_registry


class EnrichIdentityRegistryTest(unittest.TestCase):
    def test_enrich_registry_adds_aliases_keywords_and_unique_camera_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            face_root = root / "artifacts" / "identity" / "faces"
            (face_root / "person-001").mkdir(parents=True, exist_ok=True)
            (face_root / "person-001" / "face.jpg").write_bytes(b"face")
            payload = [
                {
                    "person_id": "person-001",
                    "name": "Wu Qiang",
                    "employee_id": "E10001",
                    "department": "Safety",
                    "status": "active",
                },
                {
                    "person_id": "person-002",
                    "name": "Li Peng",
                    "employee_id": "E10002",
                    "department": "Production",
                    "status": "active",
                },
            ]
            cameras = [
                {
                    "camera_id": "cam-rtsp-001",
                    "department": "Safety",
                    "responsible_department": "Safety",
                    "enabled": True,
                },
                {
                    "camera_id": "cam-local-001",
                    "department": "Safety",
                    "responsible_department": "Safety",
                    "enabled": False,
                },
            ]

            enriched, summary = enrich_identity_registry.enrich_registry_payload(payload, cameras, face_root)

        person_one = next(item for item in enriched if item["person_id"] == "person-001")
        person_two = next(item for item in enriched if item["person_id"] == "person-002")
        self.assertIn("Wu Qiang", person_one["aliases"])
        self.assertIn("WQ", person_one["aliases"])
        self.assertIn("E10001", person_one["badge_keywords"])
        self.assertIn("10001", person_one["badge_keywords"])
        self.assertEqual(person_one["default_camera_ids"], ["cam-rtsp-001"])
        self.assertNotIn("default_camera_ids", person_two)
        self.assertEqual(summary["aliases_added"], 2)
        self.assertEqual(summary["badge_keywords_added"], 2)
        self.assertEqual(summary["people_updated"], 2)
        self.assertEqual(summary["camera_bindings_added"], 1)


if __name__ == "__main__":
    unittest.main()
