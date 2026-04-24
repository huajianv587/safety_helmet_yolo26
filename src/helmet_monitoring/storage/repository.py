from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from helmet_monitoring.core.config import AppSettings

try:
    from supabase import create_client
except ImportError:  # pragma: no cover
    create_client = None


UTC = timezone.utc
CLOSED_STATUSES = {"remediated", "ignored", "false_positive", "confirmed"}
REVIEW_REQUIRED_IDENTITY_STATUSES = {"review_required", "unresolved"}

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


def local_fallback_allowed() -> bool:
    raw = os.getenv("ALLOW_LOCAL_FALLBACK")
    if raw is None:
        raw = os.getenv("HELMET_ALLOW_LOCAL_FALLBACK")
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _hour_bucket(value: datetime) -> str:
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0).isoformat()


def _day_bucket(value: datetime) -> str:
    return value.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _encode_cursor(created_at: str, alert_id: str) -> str:
    payload = _json_dumps({"created_at": created_at, "alert_id": alert_id}).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    padding = "=" * (-len(cursor) % 4)
    payload = base64.urlsafe_b64decode((cursor + padding).encode("ascii")).decode("utf-8")
    parsed = json.loads(payload)
    return str(parsed.get("created_at") or ""), str(parsed.get("alert_id") or "")


def _split_filter_values(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


class AlertRepository(ABC):
    backend_name = "unknown"

    def close(self) -> None:
        return None

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
    def list_alerts_page(
        self,
        *,
        limit: int = 100,
        since: datetime | None = None,
        camera_id: str | None = None,
        status: str | None = None,
        identity_status: str | None = None,
        department: str | None = None,
        text_query: str = "",
        cursor: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_dashboard_aggregates(
        self,
        *,
        days: int,
        now: datetime | None = None,
        status_filters: set[str] | None = None,
        camera_filters: set[str] | None = None,
        preview_limit: int = 20,
        row_offset: int = 0,
        row_limit: int = 200,
        include_rows: bool = False,
    ) -> dict[str, Any]:
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
    def insert_visitor_evidence(self, visitor_record: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_visitor_evidence(
        self,
        *,
        camera_id: str | None = None,
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
        self.db_path = self.runtime_dir / "helmet_monitoring.db"
        self.alerts_file = self.runtime_dir / "alerts.jsonl"
        self.cameras_file = self.runtime_dir / "cameras.json"
        self.actions_file = self.runtime_dir / "alert_actions.jsonl"
        self.notifications_file = self.runtime_dir / "notification_logs.jsonl"
        self.visitor_evidence_file = self.runtime_dir / "visitor_evidence.jsonl"
        self.hard_cases_file = self.runtime_dir / "hard_cases.jsonl"
        self.audit_logs_file = self.runtime_dir / "audit_logs.jsonl"
        self.migration_manifest_path = self.runtime_dir / "jsonl_migration_manifest.json"
        self._lock = RLock()
        self._closed = False
        self._initialized = False
        self._conn: sqlite3.Connection | None = None

    def _ensure_connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._closed:
                raise RuntimeError("LocalAlertRepository is closed.")
            if self._conn is None:
                conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                self._conn = conn
            if not self._initialized:
                self._initialized = True
                self._ensure_schema()
                self._migrate_legacy_jsonl_if_needed()
            return self._conn

    @contextmanager
    def _transaction(self):
        with self._lock:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self._conn is not None:
                    self._conn.close()
            except Exception:
                pass
            finally:
                self._conn = None

    def __del__(self) -> None:  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass

    def _ensure_schema(self) -> None:
        with self._transaction() as cur:
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    closed_at TEXT,
                    camera_id TEXT,
                    status TEXT,
                    identity_status TEXT,
                    department TEXT,
                    event_no TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at DESC, alert_id DESC);
                CREATE INDEX IF NOT EXISTS idx_alerts_camera_id ON alerts(camera_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_alerts_identity_status ON alerts(identity_status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_alerts_department ON alerts(department, created_at DESC);

                CREATE TABLE IF NOT EXISTS cameras (
                    camera_id TEXT PRIMARY KEY,
                    last_seen_at TEXT,
                    last_status TEXT,
                    department TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_actions (
                    action_id TEXT PRIMARY KEY,
                    alert_id TEXT,
                    created_at TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_alert_actions_alert ON alert_actions(alert_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS notification_logs (
                    notification_id TEXT PRIMARY KEY,
                    alert_id TEXT,
                    recipient TEXT,
                    status TEXT,
                    created_at TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notifications_alert ON notification_logs(alert_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS visitor_evidence (
                    record_id TEXT PRIMARY KEY,
                    camera_id TEXT,
                    created_at TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_visitor_evidence_camera ON visitor_evidence(camera_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS hard_cases (
                    case_id TEXT PRIMARY KEY,
                    alert_id TEXT,
                    case_type TEXT,
                    created_at TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_hard_cases_alert ON hard_cases(alert_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS audit_logs (
                    audit_id TEXT PRIMARY KEY,
                    entity_type TEXT,
                    entity_id TEXT,
                    action_type TEXT,
                    created_at TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS task_queue (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    idempotency_key TEXT UNIQUE,
                    worker_pool TEXT NOT NULL,
                    lease_expires_at TEXT,
                    dead_letter_reason TEXT,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_queue_poll ON task_queue(status, worker_pool, created_at);
                CREATE TABLE IF NOT EXISTS alert_aggregates_hourly (
                    bucket_hour TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_aggregates_daily (
                    bucket_day TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS repo_metadata (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                """
            )

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
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
        return rows

    def _metadata_get(self, key: str) -> Any | None:
        row = self._ensure_connection().execute("SELECT value_json FROM repo_metadata WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        return _json_loads(row["value_json"], None)

    def _metadata_set(self, cur: sqlite3.Cursor, key: str, payload: Any) -> None:
        cur.execute(
            """
            INSERT INTO repo_metadata(key, value_json) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            (key, _json_dumps(payload)),
        )

    def _legacy_migration_candidates(self) -> dict[str, tuple[Path, str]]:
        return {
            "alerts": (self.alerts_file, "alerts"),
            "cameras": (self.cameras_file, "cameras"),
            "alert_actions": (self.actions_file, "alert_actions"),
            "notification_logs": (self.notifications_file, "notification_logs"),
            "visitor_evidence": (self.visitor_evidence_file, "visitor_evidence"),
            "hard_cases": (self.hard_cases_file, "hard_cases"),
            "audit_logs": (self.audit_logs_file, "audit_logs"),
        }

    def _file_hash(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _migrate_legacy_jsonl_if_needed(self) -> None:
        already_done = bool(self._metadata_get("jsonl_migration_done"))
        if already_done:
            return
        if not any(path.exists() for path, _ in self._legacy_migration_candidates().values()):
            return

        manifest: dict[str, Any] = {"migrated_at": datetime.now(tz=UTC).isoformat(), "files": {}}
        with self._transaction() as cur:
            for logical_name, (path, table_name) in self._legacy_migration_candidates().items():
                if not path.exists():
                    continue
                if path.suffix == ".json":
                    payload = self._read_json(path, {})
                    rows = list(payload.values()) if isinstance(payload, dict) else []
                else:
                    rows = self._read_jsonl(path)
                imported = 0
                for row in rows:
                    self._upsert_table_record(cur, table_name, row, migrating=True)
                    imported += 1
                manifest["files"][logical_name] = {
                    "path": str(path),
                    "sha256": self._file_hash(path),
                    "rows_imported": imported,
                }
            self._metadata_set(cur, "jsonl_migration_done", manifest)
        self._atomic_write_json(self.migration_manifest_path, manifest)
        self._rebuild_aggregate_tables()

    def _alert_columns_from_record(self, record: dict[str, Any]) -> tuple[Any, ...]:
        created_at = str(record.get("created_at") or "")
        updated_at = str(record.get("updated_at") or created_at or datetime.now(tz=UTC).isoformat())
        return (
            record["alert_id"],
            created_at,
            updated_at,
            record.get("closed_at"),
            record.get("camera_id"),
            record.get("status"),
            record.get("identity_status"),
            record.get("department"),
            record.get("event_no"),
            _json_dumps(record),
        )

    def _camera_columns_from_record(self, record: dict[str, Any]) -> tuple[Any, ...]:
        return (
            record["camera_id"],
            record.get("last_seen_at"),
            record.get("last_status"),
            record.get("department"),
            _json_dumps(record),
        )

    def _upsert_table_record(self, cur: sqlite3.Cursor, table_name: str, record: dict[str, Any], *, migrating: bool = False) -> None:
        if table_name == "alerts":
            cur.execute(
                """
                INSERT INTO alerts(
                    alert_id, created_at, updated_at, closed_at, camera_id, status, identity_status,
                    department, event_no, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    closed_at = excluded.closed_at,
                    camera_id = excluded.camera_id,
                    status = excluded.status,
                    identity_status = excluded.identity_status,
                    department = excluded.department,
                    event_no = excluded.event_no,
                    payload_json = excluded.payload_json
                """,
                self._alert_columns_from_record(record),
            )
            return
        if table_name == "cameras":
            cur.execute(
                """
                INSERT INTO cameras(camera_id, last_seen_at, last_status, department, payload_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    last_status = excluded.last_status,
                    department = excluded.department,
                    payload_json = excluded.payload_json
                """,
                self._camera_columns_from_record(record),
            )
            return
        mapping = {
            "alert_actions": ("action_id", "alert_actions", "created_at"),
            "notification_logs": ("notification_id", "notification_logs", "created_at"),
            "visitor_evidence": ("record_id", "visitor_evidence", "created_at"),
            "hard_cases": ("case_id", "hard_cases", "created_at"),
            "audit_logs": ("audit_id", "audit_logs", "created_at"),
        }
        if table_name not in mapping:
            raise KeyError(table_name)
        key_name, actual_table, created_key = mapping[table_name]
        payload = dict(record)
        record_id = str(payload.get(key_name) or "")
        if not record_id:
            return
        columns: dict[str, Any] = {
            key_name: record_id,
            "payload_json": _json_dumps(payload),
        }
        if actual_table == "alert_actions":
            columns["alert_id"] = payload.get("alert_id")
        if actual_table == "notification_logs":
            columns["alert_id"] = payload.get("alert_id")
            columns["recipient"] = payload.get("recipient")
            columns["status"] = payload.get("status")
        if actual_table == "visitor_evidence":
            columns["camera_id"] = payload.get("camera_id")
        if actual_table == "hard_cases":
            columns["alert_id"] = payload.get("alert_id")
            columns["case_type"] = payload.get("case_type")
        if actual_table == "audit_logs":
            columns["entity_type"] = payload.get("entity_type")
            columns["entity_id"] = payload.get("entity_id")
            columns["action_type"] = payload.get("action_type")
        columns[created_key] = payload.get("created_at")
        names = ", ".join(columns.keys())
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{name} = excluded.{name}" for name in columns if name != key_name)
        cur.execute(
            f"""
            INSERT INTO {actual_table}({names}) VALUES ({placeholders})
            ON CONFLICT({key_name}) DO UPDATE SET {updates}
            """,
            tuple(columns.values()),
        )

    def _alert_from_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        payload = _json_loads(row["payload_json"], {})
        if not isinstance(payload, dict):
            payload = {}
        payload["alert_id"] = row["alert_id"]
        payload["created_at"] = row["created_at"]
        payload["updated_at"] = row["updated_at"]
        payload["closed_at"] = row["closed_at"]
        payload["camera_id"] = row["camera_id"]
        payload["status"] = row["status"]
        payload["identity_status"] = row["identity_status"]
        payload["department"] = row["department"]
        payload["event_no"] = row["event_no"]
        return payload

    def _payload_rows(self, query: str, params: Iterable[Any]) -> list[dict[str, Any]]:
        rows = self._ensure_connection().execute(query, tuple(params)).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            payload = _json_loads(row["payload_json"], {})
            if isinstance(payload, dict):
                output.append(payload)
        return output

    def _bucket_summary(self, alerts: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "total": len(alerts),
            "pending": sum(1 for item in alerts if item.get("status") == "pending"),
            "assigned": sum(1 for item in alerts if item.get("status") == "assigned"),
            "review_required": sum(1 for item in alerts if item.get("identity_status") in REVIEW_REQUIRED_IDENTITY_STATUSES),
            "resolved_identity": sum(1 for item in alerts if item.get("identity_status") == "resolved"),
            "remediated": sum(1 for item in alerts if item.get("status") == "remediated"),
            "false_positive": sum(1 for item in alerts if item.get("status") == "false_positive"),
            "closed": sum(1 for item in alerts if item.get("status") in CLOSED_STATUSES),
        }

    def _rebuild_aggregate_tables(self) -> None:
        rows = self._payload_rows("SELECT payload_json FROM alerts ORDER BY created_at DESC, alert_id DESC", ())
        hourly: dict[str, list[dict[str, Any]]] = {}
        daily: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            created_at = parse_timestamp(str(row.get("created_at") or ""))
            hourly.setdefault(_hour_bucket(created_at), []).append(row)
            daily.setdefault(_day_bucket(created_at), []).append(row)
        with self._transaction() as cur:
            cur.execute("DELETE FROM alert_aggregates_hourly")
            cur.execute("DELETE FROM alert_aggregates_daily")
            for bucket, bucket_rows in hourly.items():
                cur.execute(
                    "INSERT INTO alert_aggregates_hourly(bucket_hour, payload_json) VALUES (?, ?)",
                    (bucket, _json_dumps(self._bucket_summary(bucket_rows))),
                )
            for bucket, bucket_rows in daily.items():
                cur.execute(
                    "INSERT INTO alert_aggregates_daily(bucket_day, payload_json) VALUES (?, ?)",
                    (bucket, _json_dumps(self._bucket_summary(bucket_rows))),
                )

    def _dashboard_base_filters(
        self,
        *,
        since: datetime | None = None,
        camera_id: str | None = None,
        status: str | None = None,
        identity_status: str | None = None,
        department: str | None = None,
        cursor: str | None = None,
        text_query: str = "",
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since.isoformat())
        for field_name, raw_value in (
            ("camera_id", camera_id),
            ("status", status),
            ("identity_status", identity_status),
            ("department", department),
        ):
            values = _split_filter_values(raw_value)
            if not values:
                continue
            if len(values) == 1:
                clauses.append(f"{field_name} = ?")
                params.append(values[0])
            else:
                placeholders = ", ".join("?" for _ in values)
                clauses.append(f"{field_name} IN ({placeholders})")
                params.extend(values)
        decoded_cursor = _decode_cursor(cursor)
        if decoded_cursor:
            cursor_created_at, cursor_alert_id = decoded_cursor
            clauses.append("(created_at < ? OR (created_at = ? AND alert_id < ?))")
            params.extend([cursor_created_at, cursor_created_at, cursor_alert_id])
        if text_query.strip():
            clauses.append("LOWER(payload_json) LIKE ?")
            params.append(f"%{text_query.strip().lower()}%")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where_sql, params

    def upsert_camera(self, camera_record: dict[str, Any]) -> dict[str, Any]:
        with self._transaction() as cur:
            self._upsert_table_record(cur, "cameras", camera_record)
        return camera_record

    def insert_alert(self, alert_record: dict[str, Any]) -> dict[str, Any]:
        record = dict(alert_record)
        record.setdefault("updated_at", record.get("created_at"))
        with self._transaction() as cur:
            self._upsert_table_record(cur, "alerts", record)
        self._rebuild_aggregate_tables()
        return record

    def update_alert(self, alert_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_alert(alert_id)
        if current is None:
            return None
        merged = dict(current)
        merged.update({key: value for key, value in patch.items() if value is not None})
        merged["updated_at"] = datetime.now(tz=UTC).isoformat()
        with self._transaction() as cur:
            self._upsert_table_record(cur, "alerts", merged)
        self._rebuild_aggregate_tables()
        return merged

    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        return self._alert_from_row(self._ensure_connection().execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone())

    def list_alerts(
        self,
        *,
        limit: int = 100,
        since: datetime | None = None,
        camera_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.list_alerts_page(limit=limit, since=since, camera_id=camera_id)["items"]

    def list_alerts_page(
        self,
        *,
        limit: int = 100,
        since: datetime | None = None,
        camera_id: str | None = None,
        status: str | None = None,
        identity_status: str | None = None,
        department: str | None = None,
        text_query: str = "",
        cursor: str | None = None,
    ) -> dict[str, Any]:
        capped_limit = max(1, min(int(limit), 1000))
        where_sql, params = self._dashboard_base_filters(
            since=since,
            camera_id=camera_id,
            status=status,
            identity_status=identity_status,
            department=department,
            cursor=cursor,
            text_query=text_query,
        )
        items = [
            self._alert_from_row(row)
            for row in self._ensure_connection().execute(
                f"SELECT * FROM alerts {where_sql} ORDER BY created_at DESC, alert_id DESC LIMIT ?",
                tuple(params + [capped_limit + 1]),
            ).fetchall()
        ]
        items = [item for item in items if item is not None]
        has_more = len(items) > capped_limit
        visible = items[:capped_limit]
        next_cursor = None
        if has_more and visible:
            last_item = visible[-1]
            next_cursor = _encode_cursor(str(last_item.get("created_at") or ""), str(last_item.get("alert_id") or ""))
        total_row = self._ensure_connection().execute(f"SELECT COUNT(*) AS total FROM alerts {where_sql}", tuple(params)).fetchone()
        total = int(total_row["total"]) if total_row else len(visible)
        return {
            "items": visible,
            "total": total,
            "limit": capped_limit,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    def _iter_alerts_window(
        self,
        *,
        since: datetime,
        status_filters: set[str] | None = None,
        camera_filters: set[str] | None = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = self.list_alerts_page(
                limit=page_size,
                since=since,
                status=",".join(sorted(status_filters or [])) or None,
                camera_id=",".join(sorted(camera_filters or [])) or None,
                cursor=cursor,
            )
            items = page.get("items") or []
            rows.extend(items)
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                break
        return rows

    def _aggregate_bucket_rows(self, table_name: str, *, since: datetime, key_name: str) -> dict[str, dict[str, Any]]:
        rows = self._ensure_connection().execute(
            f"SELECT {key_name}, payload_json FROM {table_name} WHERE {key_name} >= ? ORDER BY {key_name}",
            (since.isoformat(),),
        ).fetchall()
        return {
            str(row[key_name]): _json_loads(row["payload_json"], {})
            for row in rows
        }

    def _counter_query(
        self,
        field_name: str,
        *,
        since: datetime,
        limit: int,
        status_filters: set[str] | None = None,
        camera_filters: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["created_at >= ?"]
        params: list[Any] = [since.isoformat()]
        if status_filters:
            placeholders = ", ".join("?" for _ in status_filters)
            clauses.append(f"status IN ({placeholders})")
            params.extend(sorted(status_filters))
        if camera_filters:
            placeholders = ", ".join("?" for _ in camera_filters)
            clauses.append(f"camera_id IN ({placeholders})")
            params.extend(sorted(camera_filters))
        rows = self._ensure_connection().execute(
            f"""
            SELECT json_extract(payload_json, '$.{field_name}') AS key_value, COUNT(*) AS count
            FROM alerts
            WHERE {' AND '.join(clauses)}
            GROUP BY key_value
            ORDER BY count DESC, key_value ASC
            LIMIT ?
            """,
            tuple(params + [limit]),
        ).fetchall()
        return [{"key": row["key_value"], "count": int(row["count"])} for row in rows]

    def get_dashboard_aggregates(
        self,
        *,
        days: int,
        now: datetime | None = None,
        status_filters: set[str] | None = None,
        camera_filters: set[str] | None = None,
        preview_limit: int = 20,
        row_offset: int = 0,
        row_limit: int = 200,
        include_rows: bool = False,
    ) -> dict[str, Any]:
        current = now or datetime.now(tz=UTC)
        since = current - timedelta(days=max(1, int(days)))
        start_today = current.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        day_aggregates = self._aggregate_bucket_rows("alert_aggregates_daily", since=since, key_name="bucket_day")
        hour_aggregates = self._aggregate_bucket_rows("alert_aggregates_hourly", since=start_today, key_name="bucket_hour")
        all_rows = self._iter_alerts_window(since=since, status_filters=status_filters, camera_filters=camera_filters)
        todays_rows = [item for item in all_rows if parse_timestamp(str(item.get("created_at") or "")) >= start_today]
        summary_all = self._bucket_summary(all_rows)
        summary_today = self._bucket_summary(todays_rows)
        total = len(all_rows)
        unique_people = len(
            {
                str(item.get("employee_id") or item.get("person_name") or "unknown")
                for item in all_rows
            }
        ) if all_rows else 0
        closure_rate = round((summary_all["closed"] / total) * 100, 2) if total else 0.0
        false_positive_rate = round((summary_all["false_positive"] / total) * 100, 2) if total else 0.0
        daily_trend = [
            {"date": bucket[:10], "alerts": int((payload or {}).get("total", 0))}
            for bucket, payload in sorted(day_aggregates.items())
        ]
        hourly_trend = [
            {
                "hour": parse_timestamp(bucket).strftime("%H:00"),
                "alerts": int((payload or {}).get("total", 0)),
            }
            for bucket, payload in sorted(hour_aggregates.items())
        ]
        recent_rows = all_rows[: max(1, int(preview_limit))]
        rows_total = total
        offset = max(0, int(row_offset))
        capped_row_limit = max(1, min(int(row_limit), 1000))
        rows = all_rows[offset : offset + capped_row_limit] if include_rows else recent_rows
        department_counter = self._counter_query("department", since=since, limit=8, status_filters=status_filters, camera_filters=camera_filters)
        zone_counter = self._counter_query("zone_name", since=since, limit=8, status_filters=status_filters, camera_filters=camera_filters)
        camera_counter = self._counter_query("camera_name", since=since, limit=10, status_filters=status_filters, camera_filters=camera_filters)
        identity_counter = self._counter_query("identity_source", since=since, limit=8, status_filters=status_filters, camera_filters=camera_filters)
        status_counter = self._counter_query("status", since=since, limit=12, status_filters=status_filters, camera_filters=camera_filters)
        people_counts: dict[tuple[str, str], int] = {}
        for item in all_rows:
            key = (str(item.get("person_name") or "Unknown"), str(item.get("employee_id") or "--"))
            people_counts[key] = people_counts.get(key, 0) + 1
        people_ranking = [
            {"person_name": key[0], "employee_id": key[1], "alerts": count}
            for key, count in sorted(people_counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))[:10]
        ]
        return {
            "generated_at": current.isoformat(),
            "window_days": max(1, int(days)),
            "metrics": {
                "today_alerts": summary_today["total"],
                "pending_queue": summary_today["pending"] + summary_today["assigned"],
                "review_required": summary_today["review_required"],
                "resolved_identity": summary_today["resolved_identity"],
                "false_positive": summary_today["false_positive"],
                "closure_rate": closure_rate,
                "alert_volume": total,
                "people_impacted": unique_people,
                "open_cases": summary_all["pending"] + summary_all["assigned"],
                "false_positive_rate": false_positive_rate,
            },
            "daily_trend": daily_trend,
            "hourly_trend": hourly_trend,
            "status_mix": [{"status": item["key"] or "unknown", "count": item["count"]} for item in status_counter],
            "department_ranking": [{"department": item["key"] or "Unknown", "alerts": item["count"]} for item in department_counter],
            "zone_ranking": [{"zone_name": item["key"] or "Unknown", "alerts": item["count"]} for item in zone_counter],
            "camera_ranking": [{"camera_name": item["key"] or "--", "camera_id": item["key"] or "--", "alerts": item["count"]} for item in camera_counter],
            "identity_source_mix": [{"identity_source": item["key"] or "unknown", "count": item["count"]} for item in identity_counter],
            "people_ranking": people_ranking,
            "applied_filters": {
                "statuses": sorted(status_filters or []),
                "camera_ids": sorted(camera_filters or []),
            },
            "preview_rows": recent_rows,
            "recent_alerts": recent_rows,
            "rows": rows,
            "rows_total": rows_total,
            "rows_offset": offset if include_rows else 0,
            "rows_limit": capped_row_limit if include_rows else max(1, int(preview_limit)),
            "rows_truncated": not include_rows and total > len(recent_rows),
            "has_more": offset + len(rows) < rows_total if include_rows else total > len(recent_rows),
            "next_cursor": None,
        }

    def list_cameras(self) -> list[dict[str, Any]]:
        return self._payload_rows("SELECT payload_json FROM cameras ORDER BY camera_id", ())

    def append_alert_action(self, action_record: dict[str, Any]) -> dict[str, Any]:
        with self._transaction() as cur:
            self._upsert_table_record(cur, "alert_actions", action_record)
        return action_record

    def list_alert_actions(self, *, alert_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if alert_id:
            return self._payload_rows(
                "SELECT payload_json FROM alert_actions WHERE alert_id = ? ORDER BY created_at DESC LIMIT ?",
                (alert_id, max(1, min(int(limit), 1000))),
            )
        return self._payload_rows(
            "SELECT payload_json FROM alert_actions ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        )

    def insert_notification_log(self, notification_record: dict[str, Any]) -> dict[str, Any]:
        with self._transaction() as cur:
            self._upsert_table_record(cur, "notification_logs", notification_record)
        return notification_record

    def list_notification_logs(
        self,
        *,
        alert_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if alert_id:
            return self._payload_rows(
                "SELECT payload_json FROM notification_logs WHERE alert_id = ? ORDER BY created_at DESC LIMIT ?",
                (alert_id, max(1, min(int(limit), 1000))),
            )
        return self._payload_rows(
            "SELECT payload_json FROM notification_logs ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        )

    def insert_visitor_evidence(self, visitor_record: dict[str, Any]) -> dict[str, Any]:
        with self._transaction() as cur:
            self._upsert_table_record(cur, "visitor_evidence", visitor_record)
        return visitor_record

    def list_visitor_evidence(
        self,
        *,
        camera_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if camera_id:
            return self._payload_rows(
                "SELECT payload_json FROM visitor_evidence WHERE camera_id = ? ORDER BY created_at DESC LIMIT ?",
                (camera_id, max(1, min(int(limit), 1000))),
            )
        return self._payload_rows(
            "SELECT payload_json FROM visitor_evidence ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        )

    def insert_hard_case(self, hard_case_record: dict[str, Any]) -> dict[str, Any]:
        with self._transaction() as cur:
            self._upsert_table_record(cur, "hard_cases", hard_case_record)
        return hard_case_record

    def list_hard_cases(self, *, alert_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if alert_id:
            return self._payload_rows(
                "SELECT payload_json FROM hard_cases WHERE alert_id = ? ORDER BY created_at DESC LIMIT ?",
                (alert_id, max(1, min(int(limit), 1000))),
            )
        return self._payload_rows(
            "SELECT payload_json FROM hard_cases ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        )

    def insert_audit_log(self, audit_record: dict[str, Any]) -> dict[str, Any]:
        with self._transaction() as cur:
            self._upsert_table_record(cur, "audit_logs", audit_record)
        return audit_record

    def list_audit_logs(
        self,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self._payload_rows(
            f"SELECT payload_json FROM audit_logs {where_sql} ORDER BY created_at DESC LIMIT ?",
            tuple(params + [max(1, min(int(limit), 1000))]),
        )


class SupabaseAlertRepository(AlertRepository):
    backend_name = "supabase"

    def __init__(self, url: str, service_role_key: str, fallback_repo: LocalAlertRepository) -> None:
        if create_client is None:
            raise RuntimeError("supabase package is not installed")
        self.client = create_client(url, service_role_key)
        self.fallback_repo = fallback_repo

    def close(self) -> None:
        self.fallback_repo.close()

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
        return self.list_alerts_page(limit=limit, since=since, camera_id=camera_id)["items"]

    def list_alerts_page(
        self,
        *,
        limit: int = 100,
        since: datetime | None = None,
        camera_id: str | None = None,
        status: str | None = None,
        identity_status: str | None = None,
        department: str | None = None,
        text_query: str = "",
        cursor: str | None = None,
    ) -> dict[str, Any]:
        try:
            capped_limit = max(1, min(int(limit), 1000))
            query = self.client.table("alerts").select("*", count="exact").order("created_at", desc=True).limit(capped_limit + 1)
            if since is not None:
                query = query.gte("created_at", since.isoformat())
            for field_name, raw_value in (
                ("camera_id", camera_id),
                ("status", status),
                ("identity_status", identity_status),
                ("department", department),
            ):
                values = _split_filter_values(raw_value)
                if not values:
                    continue
                if len(values) == 1:
                    query = query.eq(field_name, values[0])
                else:
                    query = query.in_(field_name, values)
            decoded_cursor = _decode_cursor(cursor)
            if decoded_cursor:
                query = query.lt("created_at", decoded_cursor[0])
            if text_query.strip():
                needle = f"%{text_query.strip()}%"
                query = query.or_(f"event_no.ilike.{needle},camera_name.ilike.{needle},person_name.ilike.{needle},employee_id.ilike.{needle}")
            response = query.execute()
            rows = response.data or []
            has_more = len(rows) > capped_limit
            visible = rows[:capped_limit]
            next_cursor = None
            if has_more and visible:
                next_cursor = _encode_cursor(str(visible[-1].get("created_at") or ""), str(visible[-1].get("alert_id") or ""))
            return {
                "items": visible,
                "total": int(getattr(response, "count", 0) or len(visible)),
                "limit": capped_limit,
                "cursor": cursor,
                "next_cursor": next_cursor,
                "has_more": has_more,
            }
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.list_alerts_page(
                    limit=limit,
                    since=since,
                    camera_id=camera_id,
                    status=status,
                    identity_status=identity_status,
                    department=department,
                    text_query=text_query,
                    cursor=cursor,
                )
            raise

    def get_dashboard_aggregates(
        self,
        *,
        days: int,
        now: datetime | None = None,
        status_filters: set[str] | None = None,
        camera_filters: set[str] | None = None,
        preview_limit: int = 20,
        row_offset: int = 0,
        row_limit: int = 200,
        include_rows: bool = False,
    ) -> dict[str, Any]:
        return self.fallback_repo.get_dashboard_aggregates(
            days=days,
            now=now,
            status_filters=status_filters,
            camera_filters=camera_filters,
            preview_limit=preview_limit,
            row_offset=row_offset,
            row_limit=row_limit,
            include_rows=include_rows,
        )

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

    def insert_visitor_evidence(self, visitor_record: dict[str, Any]) -> dict[str, Any]:
        try:
            self.client.table("visitor_evidence").insert(visitor_record).execute()
            return visitor_record
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.insert_visitor_evidence(visitor_record)
            raise

    def list_visitor_evidence(
        self,
        *,
        camera_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        try:
            query = self.client.table("visitor_evidence").select("*").order("created_at", desc=True).limit(limit)
            if camera_id:
                query = query.eq("camera_id", camera_id)
            response = query.execute()
            return response.data or []
        except Exception as exc:
            if self._is_schema_error(exc):
                return self.fallback_repo.list_visitor_evidence(camera_id=camera_id, limit=limit)
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
    require_requested_backend = require_requested_backend or (
        settings.repository_backend == "supabase" and not local_fallback_allowed()
    )
    runtime_dir = settings.resolve_path(settings.persistence.runtime_dir)
    if settings.repository_backend != "supabase":
        return LocalAlertRepository(runtime_dir)
    if settings.supabase.is_configured:
        fallback_repo = LocalAlertRepository(runtime_dir)
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
                fallback_repo.close()
                raise RuntimeError(f"Supabase backend requested but is unavailable: {exc}") from exc
            print(f"[repository] Supabase unavailable, fallback to local store: {exc}")
            return fallback_repo
    if require_requested_backend:
        raise RuntimeError("Supabase backend requested but SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are missing.")
    return LocalAlertRepository(runtime_dir)
