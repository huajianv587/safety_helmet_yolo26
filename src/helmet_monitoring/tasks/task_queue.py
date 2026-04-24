"""
Persistent background task queue backed by the local SQLite runtime store.

This keeps the existing async_task / submit_task public API while adding:
- persisted task records
- worker pools
- retry scheduling
- lease-based recovery after restart
- dead-letter handling
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from helmet_monitoring.core.config import load_settings


UTC = timezone.utc
TASK_REGISTRY: dict[str, Callable[..., Any]] = {}


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _task_name(func: Callable[..., Any]) -> str:
    return f"{func.__module__}:{func.__name__}"


def _register_task(func: Callable[..., Any]) -> str:
    task_type = _task_name(func)
    TASK_REGISTRY[task_type] = func
    return task_type


@dataclass
class Task:
    task_id: str
    task_type: str
    func: Callable[..., Any]
    args: tuple
    kwargs: dict[str, Any]
    worker_pool: str = "persist"
    status: str = "pending"
    result: Any = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retries: int = 0
    max_retries: int = 3
    idempotency_key: str | None = None


class PersistentTaskQueue:
    def __init__(
        self,
        db_path: Path,
        *,
        worker_pools: dict[str, int] | None = None,
        lease_seconds: int = 30,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.worker_pools = worker_pools or {"persist": 2, "upload": 2, "notify": 2}
        self.lease_seconds = max(10, int(lease_seconds))
        self._conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._task_available = threading.Event()
        self.running = False
        self.workers: list[threading.Thread] = []
        self._ensure_schema()

    @property
    def num_workers(self) -> int:
        return sum(self.worker_pools.values())

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
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
                """
            )
            self._conn.commit()

    def start(self):
        if self.running:
            return
        self.running = True
        self._shutdown_event.clear()
        self._ensure_runtime_task_modules_loaded()
        for pool_name, count in self.worker_pools.items():
            for index in range(max(1, int(count))):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"PersistentTaskWorker-{pool_name}-{index}",
                    args=(pool_name,),
                    daemon=True,
                )
                worker.start()
                self.workers.append(worker)
        print(f"[TaskQueue] Started {len(self.workers)} persistent workers")

    def stop(self):
        self.running = False
        self._shutdown_event.set()
        self._task_available.set()
        for worker in self.workers:
            worker.join(timeout=5)
        self.workers.clear()
        print("[TaskQueue] Stopped all workers")

    def _ensure_runtime_task_modules_loaded(self) -> None:
        for module_name in (
            "helmet_monitoring.tasks.file_tasks",
            "helmet_monitoring.tasks.notification_tasks",
        ):
            try:
                importlib.import_module(module_name)
            except Exception:
                continue

    def _backoff_seconds(self, retries: int) -> float:
        return min(60.0, float(2 ** max(0, retries)))

    def submit(
        self,
        func: Callable[..., Any],
        *args,
        max_retries: int = 3,
        worker_pool: str = "persist",
        idempotency_key: str | None = None,
        **kwargs,
    ) -> str:
        task_type = _register_task(func)
        worker_pool = str(worker_pool or "persist")
        if worker_pool not in self.worker_pools:
            worker_pool = "persist"
        payload = {"args": list(args), "kwargs": kwargs}
        now = _utc_now_iso()
        task_id = f"task-{uuid.uuid4().hex}"
        with self._lock:
            if idempotency_key:
                existing = self._conn.execute(
                    "SELECT task_id FROM task_queue WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    return str(existing["task_id"])
            self._conn.execute(
                """
                INSERT INTO task_queue(
                    task_id, task_type, payload_json, status, retry_count, max_retries,
                    idempotency_key, worker_pool, lease_expires_at, dead_letter_reason,
                    result_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', 0, ?, ?, ?, NULL, NULL, NULL, ?, ?)
                """,
                (
                    task_id,
                    task_type,
                    json.dumps(payload, ensure_ascii=False),
                    max(1, int(max_retries)),
                    idempotency_key,
                    worker_pool,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        self._task_available.set()
        print(f"[TaskQueue] Submitted task {task_id}: {task_type}")
        return task_id

    def _lookup_func(self, task_type: str) -> Callable[..., Any]:
        func = TASK_REGISTRY.get(task_type)
        if func is not None:
            return func
        module_name, _, func_name = task_type.partition(":")
        if not module_name or not func_name:
            raise RuntimeError(f"Invalid task type: {task_type}")
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
        TASK_REGISTRY[task_type] = func
        return func

    def _claim_task(self, worker_pool: str) -> sqlite3.Row | None:
        now = _utc_now_iso()
        lease_expires_at = datetime.now(UTC).timestamp() + self.lease_seconds
        lease_iso = datetime.fromtimestamp(lease_expires_at, tz=UTC).isoformat()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT *
                FROM task_queue
                WHERE worker_pool = ?
                  AND status = 'pending'
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (worker_pool, now),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                """
                UPDATE task_queue
                SET status = 'running', lease_expires_at = ?, updated_at = ?
                WHERE task_id = ? AND status = 'pending'
                """,
                (lease_iso, now, row["task_id"]),
            )
            self._conn.commit()
        return self._conn.execute("SELECT * FROM task_queue WHERE task_id = ?", (row["task_id"],)).fetchone()

    def _mark_success(self, task_id: str, result: Any) -> None:
        now = _utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                UPDATE task_queue
                SET status = 'completed', result_json = ?, lease_expires_at = NULL, updated_at = ?
                WHERE task_id = ?
                """,
                (json.dumps(result, ensure_ascii=False, default=str), now, task_id),
            )
            self._conn.commit()

    def _mark_failure(self, task_id: str, retries: int, max_retries: int, error: str) -> None:
        now = datetime.now(UTC)
        if retries >= max_retries:
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE task_queue
                    SET status = 'dead_letter', retry_count = ?, dead_letter_reason = ?, lease_expires_at = NULL, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (retries, error, now.isoformat(), task_id),
                )
                self._conn.commit()
            return
        available_at = (now + timedelta(seconds=self._backoff_seconds(retries))).isoformat()
        with self._lock:
            self._conn.execute(
                """
                UPDATE task_queue
                SET status = 'pending', retry_count = ?, dead_letter_reason = ?, lease_expires_at = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (retries, error, available_at, now.isoformat(), task_id),
            )
            self._conn.commit()
        self._task_available.set()

    def _worker_loop(self, worker_pool: str):
        while self.running and not self._shutdown_event.is_set():
            row = self._claim_task(worker_pool)
            if row is None:
                self._task_available.wait(timeout=1.0)
                self._task_available.clear()
                continue
            task_id = str(row["task_id"])
            task_type = str(row["task_type"])
            retries = int(row["retry_count"] or 0)
            max_retries = int(row["max_retries"] or 3)
            try:
                payload = json.loads(row["payload_json"])
                func = self._lookup_func(task_type)
                result = func(*(payload.get("args") or []), **(payload.get("kwargs") or {}))
                self._mark_success(task_id, result)
            except Exception as exc:
                self._mark_failure(task_id, retries + 1, max_retries, str(exc))

    def get_task_status(self, task_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM task_queue WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return {
            "task_id": row["task_id"],
            "task_type": row["task_type"],
            "status": row["status"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["dead_letter_reason"],
            "created_at": row["created_at"],
            "started_at": None,
            "completed_at": row["updated_at"] if row["status"] in {"completed", "dead_letter"} else None,
            "retries": int(row["retry_count"] or 0),
            "max_retries": int(row["max_retries"] or 0),
            "worker_pool": row["worker_pool"],
            "idempotency_key": row["idempotency_key"],
        }

    def get_queue_stats(self) -> dict[str, Any]:
        rows = self._conn.execute(
            """
            SELECT worker_pool, status, COUNT(*) AS count
            FROM task_queue
            GROUP BY worker_pool, status
            """
        ).fetchall()
        by_pool: dict[str, dict[str, int]] = defaultdict(dict)
        total_tasks = 0
        for row in rows:
            worker_pool = str(row["worker_pool"])
            status = str(row["status"])
            count = int(row["count"])
            by_pool[worker_pool][status] = count
            total_tasks += count
        pending_row = self._conn.execute("SELECT COUNT(*) AS count FROM task_queue WHERE status = 'pending'").fetchone()
        return {
            "queue_size": int(pending_row["count"]) if pending_row else 0,
            "total_tasks": total_tasks,
            "workers": self.num_workers,
            "worker_pools": {key: int(value) for key, value in self.worker_pools.items()},
            "status_by_pool": by_pool,
        }


_task_queue: Optional[PersistentTaskQueue] = None


def _queue_db_path() -> Path:
    settings = load_settings()
    runtime_dir = settings.resolve_path(settings.persistence.runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir / "helmet_monitoring.db"


def get_task_queue() -> PersistentTaskQueue:
    global _task_queue
    if _task_queue is None:
        _task_queue = PersistentTaskQueue(_queue_db_path())
        _task_queue.start()
    return _task_queue


def submit_task(func: Callable, *args, max_retries: int = 3, **kwargs) -> str:
    queue = get_task_queue()
    worker_pool = kwargs.pop("worker_pool", "persist")
    idempotency_key = kwargs.pop("idempotency_key", None)
    return queue.submit(
        func,
        *args,
        max_retries=max_retries,
        worker_pool=worker_pool,
        idempotency_key=idempotency_key,
        **kwargs,
    )


def get_task_status(task_id: str) -> Optional[dict[str, Any]]:
    queue = get_task_queue()
    return queue.get_task_status(task_id)


def get_queue_stats() -> dict[str, Any]:
    queue = get_task_queue()
    return queue.get_queue_stats()


def async_task(max_retries: int = 3, *, worker_pool: str = "persist"):
    def decorator(func: Callable):
        _register_task(func)

        def delay(*args, **kwargs) -> str:
            idempotency_key = kwargs.pop("idempotency_key", None)
            return submit_task(
                func,
                *args,
                max_retries=max_retries,
                worker_pool=worker_pool,
                idempotency_key=idempotency_key,
                **kwargs,
            )

        func.delay = delay
        func.task_type = _task_name(func)
        return func

    return decorator
