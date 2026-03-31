from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


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
from helmet_monitoring.core.schemas import AlertCandidate, utc_now
from helmet_monitoring.services.badge_ocr import BadgeOcrResult
from helmet_monitoring.services.face_recognition import FaceMatchResult
from helmet_monitoring.services.identity_resolver import IdentityResolver


class StubBadgeOcr:
    def __init__(self, result: BadgeOcrResult) -> None:
        self.result = result

    def recognize(self, frame, bbox):  # noqa: ANN001
        return self.result


class StubFaceRecognition:
    def __init__(self, result: FaceMatchResult) -> None:
        self.result = result

    def match(self, frame, bbox, profiles):  # noqa: ANN001
        return self.result


class StubLlmFallback:
    def __init__(self, result=None) -> None:
        self.result = result

    def resolve_badge_candidates(self, raw_text: str, candidates: list[dict]):
        return self.result


class StubDirectory:
    def __init__(self, people_by_id: dict[str, dict], people_by_employee_id: dict[str, dict]) -> None:
        self.people_by_id = people_by_id
        self.people_by_employee_id = people_by_employee_id

    def get_person_by_id(self, person_id: str | None) -> dict | None:
        if not person_id:
            return None
        return self.people_by_id.get(person_id)

    def find_by_employee_id(self, employee_id: str | None) -> dict | None:
        if not employee_id:
            return None
        return self.people_by_employee_id.get(employee_id)

    def search_candidates(self, query: str, limit: int = 5) -> list[dict]:
        return []

    def get_face_profiles(self) -> list:
        return []


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


def build_candidate() -> AlertCandidate:
    now = utc_now()
    return AlertCandidate(
        event_key="cam-1:track-1",
        camera_id="cam-1",
        confidence=0.91,
        label="no_helmet",
        bbox={"x1": 10, "y1": 10, "x2": 120, "y2": 220},
        first_seen_at=now,
        triggered_at=now,
        consecutive_hits=6,
    )


class IdentityResolverTest(unittest.TestCase):
    def test_badge_employee_id_resolves_person(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "persons.json"
            registry_path.write_text("[]", encoding="utf-8")
            settings = build_settings(registry_path)
            resolver = IdentityResolver(settings)
            person = {
                "person_id": "person-001",
                "name": "Zhang San",
                "employee_id": "E10001",
                "department": "Safety",
                "team": "Shift A",
                "role": "Inspector",
                "phone": "13800000001",
            }
            resolver.directory = StubDirectory(
                people_by_id={person["person_id"]: person},
                people_by_employee_id={person["employee_id"]: person},
            )
            resolver.badge_ocr = StubBadgeOcr(
                BadgeOcrResult(
                    text="EMP E10001 Zhang San",
                    confidence=0.94,
                    provider="paddleocr",
                    employee_id_hint="E10001",
                    crop=None,
                )
            )
            resolver.face_recognition = StubFaceRecognition(
                FaceMatchResult(person=None, similarity=None, crop=None, provider="none")
            )
            resolver.llm_fallback = StubLlmFallback()

            camera = CameraSettings(
                camera_id="cam-1",
                camera_name="Demo Camera",
                source="0",
                location="Workshop",
                department="Safety",
            )

            result = resolver.resolve(camera, build_candidate(), np.zeros((240, 320, 3), dtype=np.uint8))
            self.assertEqual(result.person_id, "person-001")
            self.assertEqual(result.identity_status, "resolved")
            self.assertEqual(result.identity_source, "badge_ocr")
            self.assertEqual(result.employee_id, "E10001")

    def test_camera_default_rule_marks_review_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "persons.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "person_id": "person-002",
                            "name": "Li Si",
                            "employee_id": "E10002",
                            "department": "Production",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            settings = build_settings(registry_path)
            resolver = IdentityResolver(settings)
            person = {
                "person_id": "person-002",
                "name": "Li Si",
                "employee_id": "E10002",
                "department": "Production",
                "team": "Shift B",
                "role": "Worker",
                "phone": "13800000002",
            }
            resolver.directory = StubDirectory(
                people_by_id={person["person_id"]: person},
                people_by_employee_id={},
            )
            resolver.badge_ocr = StubBadgeOcr(
                BadgeOcrResult(text=None, confidence=None, provider="none", employee_id_hint=None, crop=None)
            )
            resolver.face_recognition = StubFaceRecognition(
                FaceMatchResult(person=None, similarity=None, crop=None, provider="none")
            )
            resolver.llm_fallback = StubLlmFallback()

            camera = CameraSettings(
                camera_id="cam-2",
                camera_name="Line 2",
                source="0",
                location="Production Line 2",
                department="Production",
                default_person_id="person-002",
            )

            result = resolver.resolve(camera, build_candidate(), np.zeros((240, 320, 3), dtype=np.uint8))
            self.assertEqual(result.person_id, "person-002")
            self.assertEqual(result.identity_status, "review_required")
            self.assertEqual(result.identity_source, "camera_default_registry")


if __name__ == "__main__":
    unittest.main()
