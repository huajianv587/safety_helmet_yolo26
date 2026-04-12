from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import (
    AppSettings,
    CameraSettings,
    ClipSettings,
    EventRuleSettings,
    FaceRecognitionSettings,
    GovernanceSettings,
    IdentitySettings,
    LlmFallbackSettings,
    ModelSettings,
    MonitoringSettings,
    NotificationSettings,
    OcrSettings,
    PersistenceSettings,
    SecuritySettings,
    SupabaseSettings,
    TrackingSettings,
)
from helmet_monitoring.services.person_directory import PersonDirectory


def build_settings(registry_path: Path) -> AppSettings:
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="artifacts/model.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(registry_path=str(registry_path)),
        face_recognition=FaceRecognitionSettings(enabled=False),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(),
        notifications=NotificationSettings(),
        security=SecuritySettings(),
        supabase=SupabaseSettings(),
        cameras=(),
        config_path=registry_path,
    )


class PersonDirectoryTest(unittest.TestCase):
    def test_search_candidates_considers_aliases_and_badge_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "persons.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "person_id": "person-001",
                            "name": "Huajian Jiang",
                            "employee_id": "E90001",
                            "department": "Safety",
                            "aliases": ["HJ Jiang"],
                            "badge_keywords": ["HUAJIAN", "JIANG"],
                            "status": "active",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            directory = PersonDirectory(build_settings(registry_path))
            results = directory.search_candidates("badge: huajian", limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["person_id"], "person-001")
        self.assertGreaterEqual(results[0]["_match_score"], 0.9)

    def test_suggest_default_person_for_camera_uses_registry_camera_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "persons.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "person_id": "person-001",
                            "name": "Shift Lead",
                            "employee_id": "E20001",
                            "department": "Safety",
                            "default_camera_ids": ["cam-local-001"],
                            "default_camera_names": ["Laptop Camera"],
                            "default_locations": ["Safety Lab"],
                            "status": "active",
                        },
                        {
                            "person_id": "person-002",
                            "name": "Other Lead",
                            "employee_id": "E20002",
                            "department": "Safety",
                            "default_camera_names": ["Warehouse Cam"],
                            "status": "active",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            directory = PersonDirectory(build_settings(registry_path))
            suggestion = directory.suggest_default_person_for_camera(
                CameraSettings(
                    camera_id="cam-local-001",
                    camera_name="Laptop Camera",
                    source="0",
                    location="Safety Lab",
                    department="Safety",
                    site_name="Demo Site",
                    building_name="HQ",
                    floor_name="Floor 1",
                    workshop_name="Safety Lab",
                    zone_name="Desktop",
                )
            )

        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion["person_id"], "person-001")
        self.assertGreaterEqual(suggestion["_default_match_score"], 2.0)

    def test_merge_people_keeps_local_identity_hints_when_supabase_row_is_missing_columns(self) -> None:
        directory = PersonDirectory(build_settings(Path("persons.json")))
        merged = directory._merge_people(
            [
                {
                    "person_id": "person-001",
                    "name": "Shift Lead",
                    "employee_id": "E20001",
                    "department": "Safety",
                    "status": "active",
                }
            ],
            [
                {
                    "person_id": "person-001",
                    "name": "Shift Lead",
                    "employee_id": "E20001",
                    "department": "Safety",
                    "aliases": ["Lead A"],
                    "badge_keywords": ["SHIFT", "LEAD"],
                    "default_camera_ids": ["cam-local-001"],
                    "status": "active",
                }
            ],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["aliases"], ["Lead A"])
        self.assertEqual(merged[0]["badge_keywords"], ["SHIFT", "LEAD"])
        self.assertEqual(merged[0]["default_camera_ids"], ["cam-local-001"])

    def test_supabase_people_are_enriched_with_registry_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "persons.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "person_id": "person-001",
                            "name": "Huajian Jiang",
                            "employee_id": "E90001",
                            "department": "Safety",
                            "aliases": ["HJ Jiang"],
                            "badge_keywords": ["HUAJIAN"],
                            "default_camera_ids": ["cam-local-001"],
                            "status": "active",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            directory = PersonDirectory(build_settings(registry_path))
            with patch.object(
                directory,
                "_load_people_from_supabase",
                return_value=[
                    {
                        "person_id": "person-001",
                        "name": "Huajian Jiang",
                        "employee_id": "E90001",
                        "department": "Safety",
                        "status": "active",
                    }
                ],
            ):
                directory.refresh(force=True)
                person = directory.get_person_by_id("person-001")

        self.assertEqual(person["aliases"], ["HJ Jiang"])
        self.assertEqual(person["badge_keywords"], ["HUAJIAN"])
        self.assertEqual(person["default_camera_ids"], ["cam-local-001"])


if __name__ == "__main__":
    unittest.main()
