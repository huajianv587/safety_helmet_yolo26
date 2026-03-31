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
        people = self._load_people_from_supabase() or self._load_people_from_registry()
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
            combined = " ".join(part for part in [employee, name, department] if part)
            score = max(
                SequenceMatcher(None, target, employee).ratio() if employee else 0.0,
                SequenceMatcher(None, target, name).ratio() if name else 0.0,
                SequenceMatcher(None, target, combined.replace(" ", "")).ratio() if combined else 0.0,
            )
            if employee and employee in target:
                score = max(score, 0.98)
            if name and name in target:
                score = max(score, 0.92)
            if score >= 0.45:
                candidate = dict(person)
                candidate["_match_score"] = round(float(score), 4)
                scored.append((score, candidate))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]
