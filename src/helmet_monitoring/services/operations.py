from __future__ import annotations

import hashlib
import json
import os
import shutil
import smtplib
import time
import uuid
import zipfile
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable
from urllib import error, request

from helmet_monitoring.core.config import AppSettings, REPO_ROOT
from helmet_monitoring.core.schemas import utc_now
from helmet_monitoring.storage.repository import AlertRepository


UTC = timezone.utc


def _resolve_repo_path(path_value: str | Path, repo_root: Path | None = None) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate
    return ((repo_root or REPO_ROOT) / candidate).resolve()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    with temp_path.open("w", encoding="utf-8") as handle:
        handle.write(rendered)

    last_error: OSError | None = None
    for _ in range(8):
        try:
            os.replace(temp_path, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)

    for _ in range(8):
        try:
            with path.open("w", encoding="utf-8") as handle:
                handle.write(rendered)
            temp_path.unlink(missing_ok=True)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)

    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        pass
    if last_error is not None:
        raise last_error


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _record_audit(
    repository: AlertRepository | None,
    *,
    entity_type: str,
    entity_id: str,
    action_type: str,
    actor: str,
    payload: dict[str, Any],
    actor_role: str = "ops",
) -> None:
    if repository is None:
        return
    repository.insert_audit_log(
        {
            "audit_id": uuid.uuid4().hex,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action_type": action_type,
            "actor": actor,
            "actor_role": actor_role,
            "payload": payload,
            "created_at": utc_now().isoformat(),
        }
    )


def operations_paths(settings: AppSettings, repo_root: Path | None = None) -> dict[str, Path]:
    base = (repo_root or REPO_ROOT).resolve()
    runtime_dir = _resolve_repo_path(settings.persistence.runtime_dir, repo_root=base)
    return {
        "repo_root": base,
        "runtime_dir": runtime_dir,
        "ops_dir": runtime_dir / "ops",
        "live_frames_dir": runtime_dir / "ops" / "live_frames",
        "monitor_health": runtime_dir / "ops" / "monitor_health.json",
        "dashboard_health": runtime_dir / "ops" / "dashboard_health.json",
        "backups_dir": base / "artifacts" / "backups",
        "backup_registry": base / "artifacts" / "backups" / "backup_registry.json",
        "releases_dir": base / "artifacts" / "releases",
        "release_snapshots_dir": base / "artifacts" / "releases" / "snapshots",
        "release_registry": base / "artifacts" / "releases" / "release_registry.json",
        "model_registry": runtime_dir / "model_registry.json",
        "model_feedback_registry": runtime_dir / "model_feedback_registry.json",
        "feedback_exports_dir": base / "artifacts" / "exports" / "model_feedback",
    }


def ensure_operations_state(settings: AppSettings, repo_root: Path | None = None) -> dict[str, Path]:
    paths = operations_paths(settings, repo_root=repo_root)
    for key in ("ops_dir", "live_frames_dir", "backups_dir", "releases_dir", "release_snapshots_dir", "feedback_exports_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    if not paths["backup_registry"].exists():
        _atomic_write_json(paths["backup_registry"], {"backups": []})
    if not paths["release_registry"].exists():
        _atomic_write_json(paths["release_registry"], {"active_release": None, "releases": [], "activation_history": []})
    if not paths["model_registry"].exists():
        _atomic_write_json(paths["model_registry"], {"active_model": None, "models": [], "promotion_history": []})
    if not paths["model_feedback_registry"].exists():
        _atomic_write_json(paths["model_feedback_registry"], {"exports": [], "datasets": []})
    return paths


def write_monitor_heartbeat(
    settings: AppSettings,
    *,
    status: str,
    processed_frames: int,
    repository_backend: str,
    config_path: str,
    model_path: str,
    camera_statuses: list[dict[str, Any]],
    last_alert_event_no: str | None = None,
    detail: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_operations_state(settings, repo_root=repo_root)
    payload = {
        "service": "monitor",
        "status": status,
        "detail": detail,
        "processed_frames": int(processed_frames),
        "repository_backend": repository_backend,
        "config_path": config_path,
        "model_path": model_path,
        "last_alert_event_no": last_alert_event_no,
        "camera_statuses": camera_statuses,
        "updated_at": utc_now().isoformat(),
    }
    _atomic_write_json(paths["monitor_health"], payload)
    return payload


def write_dashboard_status(
    settings: AppSettings,
    *,
    status: str,
    detail: str,
    url: str,
    latency_ms: float | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_operations_state(settings, repo_root=repo_root)
    payload = {
        "service": "dashboard",
        "status": status,
        "detail": detail,
        "url": url,
        "latency_ms": latency_ms,
        "updated_at": utc_now().isoformat(),
    }
    _atomic_write_json(paths["dashboard_health"], payload)
    return payload


def service_health_report(
    status_path: Path,
    *,
    service_name: str,
    stale_after_seconds: int = 90,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not status_path.exists():
        return {
            "service": service_name,
            "status": "missing",
            "detail": f"Missing service heartbeat: {status_path}",
            "path": str(status_path),
            "updated_at": None,
            "age_seconds": None,
        }
    payload = _read_json(status_path, {})
    updated_at = _parse_timestamp(payload.get("updated_at"))
    if updated_at is None:
        return {
            "service": service_name,
            "status": "invalid",
            "detail": f"Heartbeat file is invalid: {status_path}",
            "path": str(status_path),
            "updated_at": None,
            "age_seconds": None,
        }
    current = now or utc_now()
    age_seconds = max(0.0, (current - updated_at).total_seconds())
    reported_status = str(payload.get("status", "")).strip().lower() or "unknown"
    status = "ready"
    detail = str(payload.get("detail") or "ok")
    if reported_status in {"stopped", "error"}:
        status = reported_status
    elif age_seconds > stale_after_seconds:
        status = "stale"
        detail = f"Last heartbeat is {age_seconds:.1f}s old (threshold {stale_after_seconds}s)."
    return {
        "service": service_name,
        "status": status,
        "detail": detail,
        "path": str(status_path),
        "updated_at": updated_at.isoformat(),
        "age_seconds": round(age_seconds, 3),
        "payload": payload,
    }


def collect_operations_status(
    settings: AppSettings,
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    stale_after_seconds: int = 90,
) -> dict[str, Any]:
    paths = ensure_operations_state(settings, repo_root=repo_root)
    monitor = service_health_report(paths["monitor_health"], service_name="monitor", stale_after_seconds=stale_after_seconds, now=now)
    dashboard = service_health_report(paths["dashboard_health"], service_name="dashboard", stale_after_seconds=stale_after_seconds, now=now)
    backup_registry = _read_json(paths["backup_registry"], {"backups": []})
    release_registry = _read_json(paths["release_registry"], {"active_release": None, "releases": [], "activation_history": []})
    model_registry = _read_json(paths["model_registry"], {"active_model": None, "models": [], "promotion_history": []})
    backups = list(backup_registry.get("backups", []))
    releases = list(release_registry.get("releases", []))
    return {
        "services": {"monitor": monitor, "dashboard": dashboard},
        "backups": {"count": len(backups), "latest": backups[-1] if backups else None},
        "releases": {
            "count": len(releases),
            "active_release": release_registry.get("active_release"),
            "activation_history": release_registry.get("activation_history", []),
        },
        "models": {
            "active_model": model_registry.get("active_model"),
            "registered_models": len(model_registry.get("models", [])),
        },
    }


def _iter_backup_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    if not path.exists():
        return
    for child in sorted(path.rglob("*")):
        if child.is_file():
            yield child


def _backup_sources(settings: AppSettings, repo_root: Path) -> list[Path]:
    sources = [
        settings.config_path if settings.config_path.is_absolute() else (repo_root / settings.config_path),
        _resolve_repo_path(settings.identity.registry_path, repo_root=repo_root),
        _resolve_repo_path(settings.persistence.runtime_dir, repo_root=repo_root),
        repo_root / "artifacts" / "releases",
        repo_root / "data" / "hard_cases" / "false_positive",
        repo_root / "data" / "hard_cases" / "missed_detection",
        repo_root / "data" / "hard_cases" / "night_shift",
        repo_root / "data" / "hard_cases" / "labeled",
    ]
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for item in sources:
        resolved = item.resolve()
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(resolved)
    return unique_paths


def create_backup(
    settings: AppSettings,
    *,
    include_captures: bool = False,
    backup_name: str | None = None,
    actor: str = "system",
    note: str | None = None,
    repository: AlertRepository | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_operations_state(settings, repo_root=repo_root)
    root = paths["repo_root"]
    timestamp = utc_now().strftime("%Y%m%d-%H%M%S")
    backup_id = uuid.uuid4().hex
    archive_name = backup_name or f"backup-{timestamp}"
    backup_path = paths["backups_dir"] / f"{archive_name}.zip"
    sources = _backup_sources(settings, root)
    if include_captures:
        sources.append(_resolve_repo_path(settings.persistence.snapshot_dir, repo_root=root))

    file_manifest: list[dict[str, Any]] = []
    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sources:
            for file_path in _iter_backup_files(source):
                relative_path = file_path.resolve().relative_to(root)
                archive.write(file_path, arcname=str(relative_path).replace("\\", "/"))
                file_manifest.append({"path": str(relative_path).replace("\\", "/"), "size_bytes": file_path.stat().st_size})
        archive.writestr(
            "backup_manifest.json",
            json.dumps(
                {
                    "backup_id": backup_id,
                    "backup_name": archive_name,
                    "config_path": str(settings.config_path),
                    "include_captures": include_captures,
                    "created_at": utc_now().isoformat(),
                    "files": file_manifest,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    registry = _read_json(paths["backup_registry"], {"backups": []})
    record = {
        "backup_id": backup_id,
        "backup_name": archive_name,
        "backup_path": str(backup_path),
        "include_captures": include_captures,
        "file_count": len(file_manifest),
        "created_at": utc_now().isoformat(),
        "actor": actor,
        "note": note,
    }
    registry.setdefault("backups", []).append(record)
    _atomic_write_json(paths["backup_registry"], registry)
    _record_audit(repository, entity_type="ops_backup", entity_id=backup_id, action_type="create_backup", actor=actor, payload=record)
    return record


def restore_backup(
    settings: AppSettings,
    backup_path: str | Path,
    *,
    actor: str = "system",
    note: str | None = None,
    repository: AlertRepository | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_operations_state(settings, repo_root=repo_root)
    root = paths["repo_root"]
    archive_path = _resolve_repo_path(backup_path, repo_root=root)
    if not archive_path.exists():
        raise FileNotFoundError(f"Backup archive not found: {archive_path}")

    restored_files = 0
    with zipfile.ZipFile(archive_path, "r") as archive:
        for member in archive.infolist():
            if member.is_dir() or member.filename == "backup_manifest.json":
                continue
            target = (root / member.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"Unsafe archive member: {member.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source_handle, target.open("wb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle)
            restored_files += 1

    record = {
        "backup_path": str(archive_path),
        "restored_files": restored_files,
        "restored_at": utc_now().isoformat(),
        "actor": actor,
        "note": note,
    }
    _record_audit(repository, entity_type="ops_backup", entity_id=archive_path.stem, action_type="restore_backup", actor=actor, payload=record)
    return record


def _load_release_registry(path: Path) -> dict[str, Any]:
    return _read_json(path, {"active_release": None, "releases": [], "activation_history": []})


def _upsert_release_record(registry: dict[str, Any], record: dict[str, Any]) -> None:
    releases = [item for item in registry.get("releases", []) if item.get("release_name") != record["release_name"]]
    releases.append(record)
    releases.sort(key=lambda item: item.get("created_at", ""))
    registry["releases"] = releases


def create_release_snapshot(
    settings: AppSettings,
    *,
    release_name: str | None = None,
    activate: bool = False,
    actor: str = "system",
    note: str | None = None,
    release_kind: str = "manual",
    repository: AlertRepository | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_operations_state(settings, repo_root=repo_root)
    registry = _load_release_registry(paths["release_registry"])
    name = release_name or f"release-{utc_now().strftime('%Y%m%d-%H%M%S')}"
    snapshot_path = paths["release_snapshots_dir"] / f"{name}.json"
    shutil.copyfile(settings.config_path, snapshot_path)

    config_payload = _read_json(settings.config_path, {})
    record = {
        "release_name": name,
        "release_kind": release_kind,
        "config_path": str(settings.config_path),
        "config_snapshot": str(snapshot_path),
        "model_path": config_payload.get("model", {}).get("path"),
        "created_at": utc_now().isoformat(),
        "actor": actor,
        "note": note,
    }
    _upsert_release_record(registry, record)
    _atomic_write_json(paths["release_registry"], registry)
    _record_audit(repository, entity_type="release", entity_id=name, action_type="create_release_snapshot", actor=actor, payload=record)
    if activate or not registry.get("active_release"):
        return activate_release(
            settings,
            release_name=name,
            actor=actor,
            note=note,
            repository=repository,
            repo_root=repo_root,
            action_type="activate_release",
        )
    return record


def activate_release(
    settings: AppSettings,
    *,
    release_name: str,
    actor: str = "system",
    note: str | None = None,
    repository: AlertRepository | None = None,
    repo_root: Path | None = None,
    action_type: str = "activate_release",
) -> dict[str, Any]:
    paths = ensure_operations_state(settings, repo_root=repo_root)
    registry = _load_release_registry(paths["release_registry"])
    record = next((item for item in registry.get("releases", []) if item.get("release_name") == release_name), None)
    if record is None:
        raise ValueError(f"Unknown release: {release_name}")
    snapshot_path = Path(record["config_snapshot"])
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Release snapshot not found: {snapshot_path}")

    shutil.copyfile(snapshot_path, settings.config_path)
    registry["active_release"] = release_name
    registry.setdefault("activation_history", []).append(
        {
            "release_name": release_name,
            "action_type": action_type,
            "actor": actor,
            "note": note,
            "activated_at": utc_now().isoformat(),
        }
    )
    _atomic_write_json(paths["release_registry"], registry)
    payload = {
        "release_name": release_name,
        "config_snapshot": record["config_snapshot"],
        "activated_at": utc_now().isoformat(),
        "actor": actor,
        "note": note,
    }
    _record_audit(repository, entity_type="release", entity_id=release_name, action_type=action_type, actor=actor, payload=payload)
    return payload


def rollback_release(
    settings: AppSettings,
    *,
    steps: int = 1,
    actor: str = "system",
    note: str | None = None,
    repository: AlertRepository | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_operations_state(settings, repo_root=repo_root)
    registry = _load_release_registry(paths["release_registry"])
    ordered: list[str] = []
    for item in registry.get("activation_history", []):
        name = item.get("release_name")
        if not name:
            continue
        if not ordered or ordered[-1] != name:
            ordered.append(name)
    if len(ordered) <= steps:
        raise ValueError("No previous release is available for rollback.")
    target_release = ordered[-1 - steps]
    return activate_release(
        settings,
        release_name=target_release,
        actor=actor,
        note=note,
        repository=repository,
        repo_root=repo_root,
        action_type="rollback_release",
    )


def sha256_file(path: str | Path) -> str:
    target = Path(path)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def ping_dashboard(url: str, timeout_seconds: float = 5.0) -> tuple[str, float | None]:
    started = utc_now()
    try:
        with request.urlopen(url, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="ignore").strip().lower()
            latency_ms = (utc_now() - started).total_seconds() * 1000.0
            if response.status == 200 and body == "ok":
                return "ok", latency_ms
            return f"unexpected-response:{response.status}:{body}", latency_ms
    except error.URLError as exc:
        return str(exc.reason), None


def send_operations_email(
    settings: AppSettings,
    *,
    recipients: tuple[str, ...],
    subject: str,
    body: str,
) -> dict[str, Any]:
    if not recipients:
        return {"status": "skipped", "detail": "No recipients configured."}
    if not settings.notifications.is_email_configured:
        return {"status": "skipped", "detail": "SMTP is not configured."}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.notifications.smtp_from_email
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    with smtplib.SMTP(settings.notifications.smtp_host, settings.notifications.smtp_port, timeout=20) as smtp:
        if settings.notifications.use_tls:
            smtp.starttls()
        if settings.notifications.smtp_username:
            smtp.login(settings.notifications.smtp_username, settings.notifications.smtp_password)
        smtp.send_message(message)
    return {"status": "sent", "detail": f"Sent to {len(recipients)} recipients."}
