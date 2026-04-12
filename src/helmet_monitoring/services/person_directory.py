from __future__ import annotations

import json
import time
from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np

from helmet_monitoring.core.config import AppSettings

try:
    from supabase import create_client
except ImportError:  # pragma: no cover
    create_client = None


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in value.strip().upper() if ch.isalnum())


def _tuple_from_person_values(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value]
    else:
        items = [item.strip() for item in str(value).split(",")]
    return tuple(item for item in items if item)


@dataclass(slots=True)
class FaceProfileRecord:
    profile_id: str
    person: dict
    embedding: np.ndarray
    embedding_version: str
    source_name: str
    source_photo_url: str | None


class PersonDirectory:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.registry_path = settings.resolve_path(settings.identity.registry_path)
        self.refresh_seconds = settings.identity.refresh_seconds
        self.client = None
        if settings.supabase.is_configured and create_client is not None:
            self.client = create_client(settings.supabase.url, settings.supabase.service_role_key)
        self._people_cache: list[dict] = []
        self._face_profile_cache: list[FaceProfileRecord] = []
        self._loaded_at = 0.0

    def _refresh_due(self) -> bool:
        return (time.time() - self._loaded_at) >= self.refresh_seconds

    def _load_people_from_registry(self) -> list[dict]:
        if not self.registry_path.exists():
            return []
        with self.registry_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return [item for item in payload if item.get("status", "active") == "active"]

    def _load_people_from_supabase(self) -> list[dict]:
        if self.client is None:
            return []
        try:
            response = self.client.table("persons").select("*").eq("status", "active").execute()
            return response.data or []
        except Exception:
            return []

    @staticmethod
    def _merge_people(supabase_people: list[dict], registry_people: list[dict]) -> list[dict]:
        if not supabase_people:
            return list(registry_people)

        people_by_id: dict[str, dict] = {
            str(item["person_id"]): dict(item)
            for item in supabase_people
            if item.get("person_id")
        }
        for registry_person in registry_people:
            person_id = str(registry_person.get("person_id") or "")
            if not person_id:
                continue
            merged = dict(people_by_id.get(person_id, {}))
            for key, value in registry_person.items():
                if key not in merged or value not in (None, "", [], (), {}):
                    merged[key] = value
            people_by_id[person_id] = merged
        return list(people_by_id.values())

    def _load_face_profiles_from_supabase(self, people_by_id: dict[str, dict]) -> list[FaceProfileRecord]:
        if self.client is None:
            return []
        try:
            response = self.client.table("person_face_profiles").select("*").execute()
            profiles = response.data or []
        except Exception:
            return []
        records: list[FaceProfileRecord] = []
        for item in profiles:
            person = people_by_id.get(item.get("person_id"))
            embedding_json = item.get("embedding_json")
            if not person or not isinstance(embedding_json, list):
                continue
            try:
                embedding = np.asarray(embedding_json, dtype=np.float32)
            except Exception:
                continue
            if embedding.size == 0:
                continue
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            records.append(
                FaceProfileRecord(
                    profile_id=str(item.get("profile_id")),
                    person=person,
                    embedding=embedding,
                    embedding_version=str(item.get("embedding_version", "")),
                    source_name=str(item.get("source_name", "unknown")),
                    source_photo_url=item.get("source_photo_url"),
                )
            )
        return records

    def refresh(self, force: bool = False) -> None:
        if not force and not self._refresh_due():
            return
        registry_people = self._load_people_from_registry()
        supabase_people = self._load_people_from_supabase()
        people = self._merge_people(supabase_people, registry_people) if supabase_people else registry_people
        people_by_id = {str(item["person_id"]): item for item in people if item.get("person_id")}
        profiles = self._load_face_profiles_from_supabase(people_by_id)
        self._people_cache = list(people_by_id.values())
        self._face_profile_cache = profiles
        self._loaded_at = time.time()

    def get_people(self) -> list[dict]:
        self.refresh()
        return list(self._people_cache)

    def get_person_by_id(self, person_id: str | None) -> dict | None:
        if not person_id:
            return None
        self.refresh()
        for person in self._people_cache:
            if person.get("person_id") == person_id:
                return person
        return None

    def get_face_profiles(self) -> list[FaceProfileRecord]:
        self.refresh()
        return list(self._face_profile_cache)

    def find_by_employee_id(self, employee_id: str | None) -> dict | None:
        target = normalize_text(employee_id)
        if not target:
            return None
        self.refresh()
        for person in self._people_cache:
            if normalize_text(person.get("employee_id")) == target:
                return person
        return None

    def suggest_default_person_for_camera(self, camera) -> dict | None:
        self.refresh()
        scored: list[tuple[float, dict]] = []
        weighted_camera_fields = (
            ("default_camera_ids", camera.camera_id, 3.2),
            ("default_camera_names", camera.camera_name, 2.2),
            ("default_locations", camera.location, 1.5),
            ("default_site_names", getattr(camera, "site_name", ""), 1.1),
            ("default_building_names", getattr(camera, "building_name", ""), 1.0),
            ("default_floor_names", getattr(camera, "floor_name", ""), 0.9),
            ("default_workshop_names", getattr(camera, "workshop_name", ""), 1.0),
            ("default_zone_names", getattr(camera, "zone_name", ""), 1.0),
            ("default_departments", getattr(camera, "responsible_department", "") or camera.department, 0.5),
        )
        for person in self._people_cache:
            score = 0.0
            for field_name, raw_camera_value, weight in weighted_camera_fields:
                target = normalize_text(raw_camera_value)
                if not target:
                    continue
                person_values = [normalize_text(item) for item in _tuple_from_person_values(person.get(field_name))]
                if not person_values:
                    continue
                if target in person_values:
                    score += weight
                    continue
                if any(target in item or item in target for item in person_values if item):
                    score += weight * 0.7
            if score > 0:
                candidate = dict(person)
                candidate["_default_match_score"] = round(float(score), 4)
                scored.append((score, candidate))
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            return None
        top_score, top_candidate = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        if top_score < 2.0:
            return None
        if second_score and (top_score - second_score) < 0.75:
            return None
        return top_candidate

    def search_candidates(self, query: str, limit: int = 5) -> list[dict]:
        target = normalize_text(query)
        if not target:
            return []
        self.refresh()
        scored: list[tuple[float, dict]] = []
        for person in self._people_cache:
            employee = normalize_text(person.get("employee_id"))
            name = normalize_text(person.get("name"))
            department = normalize_text(person.get("department"))
            team = normalize_text(person.get("team"))
            role = normalize_text(person.get("role"))
            aliases = [normalize_text(item) for item in _tuple_from_person_values(person.get("aliases"))]
            badge_keywords = [normalize_text(item) for item in _tuple_from_person_values(person.get("badge_keywords"))]
            tokens = [part for part in [employee, name, department, team, role, *aliases, *badge_keywords] if part]
            combined = " ".join(tokens)
            score = max(
                SequenceMatcher(None, target, employee).ratio() if employee else 0.0,
                SequenceMatcher(None, target, name).ratio() if name else 0.0,
                max((SequenceMatcher(None, target, alias).ratio() for alias in aliases), default=0.0),
                max((SequenceMatcher(None, target, keyword).ratio() for keyword in badge_keywords), default=0.0),
                SequenceMatcher(None, target, combined.replace(" ", "")).ratio() if combined else 0.0,
            )
            if employee and employee in target:
                score = max(score, 0.98)
            if name and name in target:
                score = max(score, 0.92)
            if any(alias and alias in target for alias in aliases):
                score = max(score, 0.95)
            if any(keyword and keyword in target for keyword in badge_keywords):
                score = max(score, 0.96)
            if score >= 0.45:
                candidate = dict(person)
                candidate["_match_score"] = round(float(score), 4)
                scored.append((score, candidate))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]
