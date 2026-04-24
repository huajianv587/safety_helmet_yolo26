from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.core.schemas import utc_now
from helmet_monitoring.services.notifier import NotificationService
from helmet_monitoring.storage.evidence_store import EvidenceStore
from helmet_monitoring.storage.repository import build_repository, parse_timestamp
from helmet_monitoring.tasks.task_queue import async_task


def _content_type_for_extension(extension: str) -> str:
    normalized = str(extension or "").strip().lower()
    if normalized in {".mp4", "mp4"}:
        return "video/mp4"
    return "image/jpeg"


def _repo_close(repository: Any) -> None:
    try:
        repository.close()
    except Exception:
        pass


@async_task(max_retries=3, worker_pool="upload")
def upload_alert_artifact(
    *,
    alert_id: str,
    camera_id: str,
    artifact_id: str,
    created_at: str,
    local_path: str,
    category: str,
    extension: str,
    field_name: str,
) -> dict[str, Any]:
    settings = load_settings()
    repository = build_repository(settings)
    try:
        local_file = Path(local_path)
        if not local_file.exists():
            raise FileNotFoundError(f"Artifact does not exist: {local_path}")
        store = EvidenceStore(settings)
        created_at_value = parse_timestamp(created_at)
        object_path = store.remote_object_path(
            camera_id,
            artifact_id,
            created_at_value,
            category=category,
            extension=extension,
        )
        access_url = store.upload_artifact(local_file, object_path, _content_type_for_extension(extension))
        if access_url:
            repository.update_alert(alert_id, {f"{field_name}_url": access_url})
            repository.insert_audit_log(
                {
                    "audit_id": uuid.uuid4().hex,
                    "entity_type": "alert",
                    "entity_id": alert_id,
                    "action_type": "artifact_uploaded",
                    "actor": "system",
                    "actor_role": "worker",
                    "payload": {
                        "field_name": field_name,
                        "local_path": str(local_file),
                        "object_path": object_path,
                        "access_url": access_url,
                    },
                    "created_at": utc_now().isoformat(),
                }
            )
            if not settings.persistence.keep_local_copy:
                local_file.unlink(missing_ok=True)
        return {
            "status": "completed",
            "alert_id": alert_id,
            "field_name": field_name,
            "local_path": str(local_file),
            "object_path": object_path,
            "access_url": access_url,
        }
    finally:
        _repo_close(repository)


@async_task(max_retries=3, worker_pool="notify")
def deliver_alert_email(
    *,
    alert_id: str,
    recipient: str,
) -> dict[str, Any]:
    settings = load_settings()
    repository = build_repository(settings)
    try:
        alert = repository.get_alert(alert_id)
        if alert is None:
            raise RuntimeError(f"Alert does not exist: {alert_id}")
        notifier = NotificationService(settings, repository)
        notifier.send_alert_email(alert, (recipient,))
        return {
            "status": "completed",
            "alert_id": alert_id,
            "recipient": recipient,
        }
    finally:
        _repo_close(repository)


def artifact_idempotency_key(alert_id: str, field_name: str, local_path: str) -> str:
    digest = hashlib.sha1(str(local_path).encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{alert_id}:{field_name}:{digest}"


def notification_idempotency_key(alert_id: str, recipient: str) -> str:
    digest = hashlib.sha1(str(recipient).encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{alert_id}:notify:{digest}"
