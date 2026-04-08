from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from helmet_monitoring.core.config import AppSettings

try:
    from supabase import create_client
except ImportError:  # pragma: no cover
    create_client = None


OPTIONAL_ALERT_FIELDS = {
    "person_id",
    "person_name",
    "employee_id",
    "team",
    "role",
    "phone",
    "identity_status",
    "identity_source",
    "identity_confidence",
    "badge_text",
    "badge_confidence",
    "face_match_score",
    "face_crop_path",
    "face_crop_url",
    "badge_crop_path",
    "badge_crop_url",
    "review_note",
    "llm_provider",
    "llm_summary",
    "event_no",
    "clip_path",
    "clip_url",
    "assigned_to",
    "assigned_email",
    "handled_by",
    "handled_at",
    "resolution_note",
    "remediation_snapshot_path",
    "remediation_snapshot_url",
    "false_positive",
    "closed_at",
    "alert_source",
    "governance_note",
    "track_id",
    "site_name",
    "building_name",
    "floor_name",
    "workshop_name",
    "zone_name",
    "responsible_department",
}


def parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


class AlertRepository(ABC):
    backend_name = "unknown"

    @abstractmethod
    def upsert_camera(self, camera_record: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def insert_alert(self, alert_record: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update_alert(self, alert_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def list_alerts(
        self,
        *,
        limit: int = 100,
        since: datetime | None = None,
        camera_id: str | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def list_cameras(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def append_alert_action(self, action_record: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_alert_actions(self, *, alert_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def insert_notification_log(self, notification_record: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_notification_logs(
        self,
        *,
        alert_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def insert_hard_case(self, hard_case_record: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_hard_cases(self, *, alert_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def insert_audit_log(self, audit_record: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_audit_logs(
        self,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


class LocalAlertRepository(AlertRepository):
    backend_name = "local"

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.alerts_file = self.runtime_dir / "alerts.jsonl"
        self.cameras_file = self.runtime_dir / "cameras.json"
        self.actions_file = self.runtime_dir / "alert_actions.jsonl"
        self.notifications_file = self.runtime_dir / "notification_logs.jsonl"
        self.hard_cases_file = self.runtime_dir / "hard_cases.jsonl"
        self.audit_logs_file = self.runtime_dir / "audit_logs.jsonl"
        self._lock = Lock()
        if not self.cameras_file.exists():
            self._atomic_write_json(self.cameras_file, {})

    def _atomic_write_json(self, path: Path, payload: Any) -> None:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        temp_path.replace(path)

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError:
            return default

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        temp_path.replace(path)

    def _append_jsonl(self, path: Path, row: dict[str, Any]) -> dict[str, Any]:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def upsert_camera(self, camera_record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = self._read_json(self.cameras_file, {})
            payload[camera_record["camera_id"]] = camera_record
            self._atomic_write_json(self.cameras_file, payload)
        return camera_record

    def insert_alert(self, alert_record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._append_jsonl(self.alerts_file, alert_record)

    def update_alert(self, alert_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            rows = self._read_jsonl(self.alerts_file)
            updated = None
            for row in rows:
                if row.get("alert_id") == alert_id:
                    row.update({key: value for key, value in patch.items() if value is not None})
                    updated = row
                    break
            if updated is not None:
                self._write_jsonl(self.alerts_file, rows)
            return updated

    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        rows = self._read_jsonl(self.alerts_file)
        for row in rows:
            if row.get("alert_id") == alert_id:
                return row
        return None

    def list_alerts(
        self,
        *,
        limit: int = 100,
        since: datetime | None = None,
        camera_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._read_jsonl(self.alerts_file)
        filtered: list[dict[str, Any]] = []
        for row in rows:
            if camera_id and row.get("camera_id") != camera_id:
                continue
            if since and parse_timestamp(row.get("created_at")) < since:
                continue
            filtered.append(row)
        filtered.sort(key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)
        return filtered[:limit]

    def list_cameras(self) -> list[dict[str, Any]]:
        payload = self._read_json(self.cameras_file, {})
        rows = list(payload.values())
        rows.sort(key=lambda item: item.get("camera_id", ""))
        return rows

    def append_alert_action(self, action_record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._append_jsonl(self.actions_file, action_record)

    def list_alert_actions(self, *, alert_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._read_jsonl(self.actions_file)
        if alert_id:
            rows = [row for row in rows if row.get("alert_id") == alert_id]
        rows.sort(key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)
        return rows[:limit]

    def insert_notification_log(self, notification_record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._append_jsonl(self.notifications_file, notification_record)

    def list_notification_logs(
        self,
        *,
        alert_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        rows = self._read_jsonl(self.notifications_file)
        if alert_id:
            rows = [row for row in rows if row.get("alert_id") == alert_id]
        rows.sort(key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)
        return rows[:limit]

    def insert_hard_case(self, hard_case_record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._append_jsonl(self.hard_cases_file, hard_case_record)

    def list_hard_cases(self, *, alert_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._read_jsonl(self.hard_cases_file)
        if alert_id:
            rows = [row for row in rows if row.get("alert_id") == alert_id]
        rows.sort(key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)
        return rows[:limit]

    def insert_audit_log(self, audit_record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._append_jsonl(self.audit_logs_file, audit_record)

    def list_audit_logs(
        self,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        rows = self._read_jsonl(self.audit_logs_file)
        if entity_type:
            rows = [row for row in rows if row.get("entity_type") == entity_type]
        if entity_id:
            rows = [row for row in rows if row.get("entity_id") == entity_id]
        rows.sort(key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)
        return rows[:limit]


class SupabaseAlertRepository(AlertRepository):
    backend_name = "supabase"

    def __init__(self, url: str, service_role_key: str, fallback_repo: LocalAlertRepository) -> None:
        if create_client is None:
            raise RuntimeError("supabase package is not installed")
        self.client = create_client(url, service_role_key)
        self.fallback_repo = fallback_repo

    def _is_schema_error(self, exc: Exception) -> bool:
        error_text = str(exc)
        return "schema cache" in error_text or "Could not find" in error_text or "column" in error_text or "relation" in error_text

    def upsert_camera(self, camera_record: dict[str, Any]) -> dict[str, Any]:
        try:
            self.client.table("cameras").upsert(camera_record, on_conflict="camera_id").execute()
            return camera_record
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.upsert_camera(camera_record)
            raise

    def insert_alert(self, alert_record: dict[str, Any]) -> dict[str, Any]:
        try:
            self.client.table("alerts").insert(alert_record).execute()
            return alert_record
        except Exception as exc:
            if self._is_schema_error(exc):
                downgraded_payload = {key: value for key, value in alert_record.items() if key not in OPTIONAL_ALERT_FIELDS}
                try:
                    self.client.table("alerts").insert(downgraded_payload).execute()
                    print(
                        "[repository] Alert inserted without extended workflow fields. "
                        "Run sql/supabase_identity_extension.sql, sql/supabase_identity_ai_extension.sql, "
                        "and sql/supabase_product_extension.sql to enable the full product pipeline."
                    )
                    return downgraded_payload
                except Exception:
                    return self.fallback_repo.insert_alert(alert_record)
            raise

    def update_alert(self, alert_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        try:
            response = self.client.table("alerts").update(patch).eq("alert_id", alert_id).execute()
            rows = response.data or []
            return rows[0] if rows else self.get_alert(alert_id)
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.update_alert(alert_id, patch)
            raise

    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        try:
            response = self.client.table("alerts").select("*").eq("alert_id", alert_id).limit(1).execute()
            rows = response.data or []
            return rows[0] if rows else None
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.get_alert(alert_id)
            raise

    def list_alerts(
        self,
        *,
        limit: int = 100,
        since: datetime | None = None,
        camera_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            query = self.client.table("alerts").select("*").order("created_at", desc=True).limit(limit)
            if since is not None:
                query = query.gte("created_at", since.isoformat())
            if camera_id:
                query = query.eq("camera_id", camera_id)
            response = query.execute()
            return response.data or []
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.list_alerts(limit=limit, since=since, camera_id=camera_id)
            raise

    def list_cameras(self) -> list[dict[str, Any]]:
        try:
            response = self.client.table("cameras").select("*").order("camera_id").execute()
            return response.data or []
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.list_cameras()
            raise

    def append_alert_action(self, action_record: dict[str, Any]) -> dict[str, Any]:
        try:
            self.client.table("alert_actions").insert(action_record).execute()
            return action_record
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.append_alert_action(action_record)
            raise

    def list_alert_actions(self, *, alert_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        try:
            query = self.client.table("alert_actions").select("*").order("created_at", desc=True).limit(limit)
            if alert_id:
                query = query.eq("alert_id", alert_id)
            response = query.execute()
            return response.data or []
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.list_alert_actions(alert_id=alert_id, limit=limit)
            raise

    def insert_notification_log(self, notification_record: dict[str, Any]) -> dict[str, Any]:
        try:
            self.client.table("notification_logs").insert(notification_record).execute()
            return notification_record
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.insert_notification_log(notification_record)
            raise

    def list_notification_logs(
        self,
        *,
        alert_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        try:
            query = self.client.table("notification_logs").select("*").order("created_at", desc=True).limit(limit)
            if alert_id:
                query = query.eq("alert_id", alert_id)
            response = query.execute()
            return response.data or []
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.list_notification_logs(alert_id=alert_id, limit=limit)
            raise

    def insert_hard_case(self, hard_case_record: dict[str, Any]) -> dict[str, Any]:
        try:
            self.client.table("hard_cases").insert(hard_case_record).execute()
            return hard_case_record
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.insert_hard_case(hard_case_record)
            raise

    def list_hard_cases(self, *, alert_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        try:
            query = self.client.table("hard_cases").select("*").order("created_at", desc=True).limit(limit)
            if alert_id:
                query = query.eq("alert_id", alert_id)
            response = query.execute()
            return response.data or []
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.list_hard_cases(alert_id=alert_id, limit=limit)
            raise

    def insert_audit_log(self, audit_record: dict[str, Any]) -> dict[str, Any]:
        try:
            self.client.table("audit_logs").insert(audit_record).execute()
            return audit_record
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.insert_audit_log(audit_record)
            raise

    def list_audit_logs(
        self,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        try:
            query = self.client.table("audit_logs").select("*").order("created_at", desc=True).limit(limit)
            if entity_type:
                query = query.eq("entity_type", entity_type)
            if entity_id:
                query = query.eq("entity_id", entity_id)
            response = query.execute()
            return response.data or []
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.list_audit_logs(entity_type=entity_type, entity_id=entity_id, limit=limit)
            raise


def build_repository(settings: AppSettings, *, require_requested_backend: bool = False) -> AlertRepository:
    runtime_dir = settings.resolve_path(settings.persistence.runtime_dir)
    fallback_repo = LocalAlertRepository(runtime_dir)
    if settings.repository_backend == "supabase" and settings.supabase.is_configured:
        try:
            repository = SupabaseAlertRepository(
                settings.supabase.url,
                settings.supabase.service_role_key,
                fallback_repo=fallback_repo,
            )
            repository.list_cameras()
            return repository
        except Exception as exc:  # pragma: no cover
            if require_requested_backend:
                raise RuntimeError(f"Supabase backend requested but is unavailable: {exc}") from exc
            print(f"[repository] Supabase unavailable, fallback to local store: {exc}")
    elif settings.repository_backend == "supabase" and require_requested_backend:
        raise RuntimeError("Supabase backend requested but SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are missing.")
    return fallback_repo
