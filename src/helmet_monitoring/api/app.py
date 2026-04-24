from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from helmet_monitoring.core.config import REPO_ROOT, load_settings
from helmet_monitoring.core.schemas import utc_now
from helmet_monitoring.services.auth import (
    AuthAccount,
    TrustedIdentity,
    authenticate_user,
    auth_configuration_summary,
    clear_login_failures,
    delete_managed_auth_account,
    get_login_lockout_state,
    hash_password,
    load_auth_accounts,
    load_auth_policy,
    load_managed_auth_accounts,
    register_login_failure,
    role_has_permission,
    upsert_managed_auth_account,
)
from helmet_monitoring.services.dashboard_api import (
    ROLE_ROUTES,
    build_overview_payload,
    build_reports_payload,
    filter_alerts,
    is_safe_camera_source_reference,
    merge_live_cameras,
    sort_alerts,
    upsert_runtime_camera,
    visible_routes_for_role,
)
from helmet_monitoring.services.notifier import NotificationService
from helmet_monitoring.services.operations import (
    activate_release,
    create_backup,
    create_release_snapshot,
    operations_paths,
    restore_backup,
    rollback_release,
)
from helmet_monitoring.services.operations_studio import (
    OPS_CONFIRM_TEXT,
    OPS_READ_ROLES,
    build_backups_payload,
    build_capability_matrix_payload,
    build_evidence_delivery_summary,
    build_identity_summary,
    build_model_feedback_summary,
    build_quality_summary,
    build_readiness_payload,
    build_releases_payload,
    build_services_payload,
    bootstrap_identity_defaults,
    perform_service_action,
    run_notification_delivery_check,
    run_storage_delivery_check,
    sync_identity_registry,
)
from helmet_monitoring.services.person_directory import PersonDirectory
from helmet_monitoring.services.live_frame_hub import get_live_frame_hub
from helmet_monitoring.services.video_sources import is_local_device_source
from helmet_monitoring.ui.live_preview_stream import BrowserInferenceEngine
from helmet_monitoring.services.model_governance import build_feedback_dataset, export_feedback_cases
from helmet_monitoring.storage.evidence_store import EvidenceStore
from helmet_monitoring.storage.repository import AlertRepository, build_repository, parse_timestamp
from helmet_monitoring.api.cache_manager import CacheTier, get_cache_manager, stable_cache_key
from helmet_monitoring.api.cache_integration import CacheKeyBuilder, CacheInvalidator, warmup_critical_caches
from helmet_monitoring.api.websocket import (
    broadcast_alert_updated,
    broadcast_frame_state,
    broadcast_metrics_update,
    broadcast_overview_snapshot,
    broadcast_queue_update,
    dispatch_topic_message,
    get_connection_manager,
    websocket_alerts_handler,
    websocket_cameras_handler,
    websocket_dashboard_handler,
)
from helmet_monitoring.tasks.task_queue import get_queue_stats


UTC = timezone.utc
API_PREFIX = "/api/v1/helmet"
TOKEN_VERSION = "h1"
MEDIA_TOKEN_SECONDS = 24 * 60 * 60
ALLOWED_ACCOUNT_ROLES = tuple(ROLE_ROUTES.keys())
GUEST_IDENTITY = TrustedIdentity(username="guest", role="viewer", display_name="访客模式", email="")
_ENV_PRIMED = False

# Optimization: Unified cache system using TieredCacheManager
# Replaces dual cache (_RUNTIME_CACHE + _READ_CACHE) with single manager
_UNIFIED_CACHE_LOCK = Lock()
_RUNTIME_SERVICES_REGISTRY: dict[str, "RuntimeServices"] = {}
_AUTH_WRITE_LOCK = Lock()

COMPACT_ALERT_FIELDS = (
    "alert_id",
    "event_no",
    "camera_id",
    "camera_name",
    "person_id",
    "person_name",
    "employee_id",
    "department",
    "team",
    "role",
    "location",
    "site_name",
    "building_name",
    "floor_name",
    "workshop_name",
    "zone_name",
    "responsible_department",
    "status",
    "identity_status",
    "identity_source",
    "risk_level",
    "assigned_to",
    "created_at",
    "updated_at",
    "closed_at",
    "snapshot_display_url",
    "snapshot_media_state",
    "face_crop_display_url",
    "face_crop_media_state",
    "badge_crop_display_url",
    "badge_crop_media_state",
)


@dataclass(slots=True)
class RuntimeServices:
    settings: Any
    repository: Any
    directory: PersonDirectory
    evidence_store: EvidenceStore
    notifier: NotificationService
    browser_inference: BrowserInferenceEngine


class ThreadLockedRepository:
    def __init__(self, repository: AlertRepository) -> None:
        self._repository = repository
        self._lock = Lock()
        self.backend_name = getattr(repository, "backend_name", "unknown")

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._repository, name)
        if not callable(attr):
            return attr

        def locked_call(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                return attr(*args, **kwargs)

        return locked_call


class LoginRequest(BaseModel):
    username: str = Field(default="")
    password: str = Field(default="")
    remember: bool = False


class RegisterRequest(BaseModel):
    username: str = Field(default="")
    password: str = Field(default="")
    display_name: str = Field(default="")
    email: str = Field(default="")
    remember: bool = False


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(default="")


class AssignRequest(BaseModel):
    assignee: str = Field(default="")
    assignee_email: str = Field(default="")
    note: str = Field(default="")


class CameraUpsertRequest(BaseModel):
    camera_id: str
    camera_name: str = ""
    source: str = "0"
    enabled: bool = True
    location: str = "Unknown"
    department: str = "Unknown"
    site_name: str = "Default Site"
    building_name: str = "Main Building"
    floor_name: str = "Floor 1"
    workshop_name: str = "Workshop A"
    zone_name: str = "Zone A"
    responsible_department: str = ""
    alert_emails: list[str] = Field(default_factory=list)
    default_person_id: str = ""


class TestNotificationRequest(BaseModel):
    recipient: str
    subject: str = "Safety Helmet System Test"
    body: str = "This is a test email from the Safety Helmet Command Center."


class AccountUpsertRequest(BaseModel):
    username: str
    role: str = "viewer"
    display_name: str = ""
    email: str = ""
    password: str = ""


class ServiceActionRequest(BaseModel):
    action: str
    note: str = ""
    confirm_text: str = ""


class IdentityBootstrapRequest(BaseModel):
    apply: bool = False
    overwrite: bool = False
    note: str = ""


class FeedbackExportRequest(BaseModel):
    limit: int = 200
    case_types: list[str] = Field(default_factory=list)
    note: str = ""


class FeedbackDatasetRequest(BaseModel):
    base_dataset_yaml: str = "configs/datasets/shwd_yolo26.yaml"
    note: str = ""


class BackupCreateRequest(BaseModel):
    backup_name: str = ""
    include_captures: bool = False
    note: str = ""


class BackupRestoreRequest(BaseModel):
    backup_path: str
    note: str = ""
    confirm_text: str = ""


class ReleaseSnapshotRequest(BaseModel):
    release_name: str = ""
    activate: bool = False
    note: str = ""


class ReleaseActionRequest(BaseModel):
    release_name: str = ""
    steps: int = 1
    note: str = ""
    confirm_text: str = ""


class DeliveryValidationRequest(BaseModel):
    note: str = ""


def _b64_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _token_secret() -> bytes:
    raw = (
        os.getenv("HELMET_API_TOKEN_SECRET")
        or os.getenv("HELMET_AUTH_TOKEN_SECRET")
        or os.getenv("HELMET_AUTH_ADMIN_PASSWORD_HASH")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or "helmet-local-development-secret"
    )
    return str(raw).encode("utf-8")


def _ensure_environment_loaded() -> None:
    global _ENV_PRIMED
    if _ENV_PRIMED:
        return
    try:
        load_settings()
    except Exception:
        pass
    _ENV_PRIMED = True


def _sign_bytes(payload: bytes) -> str:
    digest = hmac.new(_token_secret(), payload, hashlib.sha256).digest()
    return _b64_encode(digest)


def _signed_token(payload: dict[str, Any]) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = _b64_encode(rendered)
    signature = _sign_bytes(body.encode("ascii"))
    return f"{TOKEN_VERSION}.{body}.{signature}"


def _decode_signed_token(token: str) -> dict[str, Any]:
    try:
        version, body, signature = str(token).split(".", 2)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid token.") from exc
    if version != TOKEN_VERSION:
        raise HTTPException(status_code=401, detail="Unsupported token version.")
    expected = _sign_bytes(body.encode("ascii"))
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid token signature.")
    try:
        payload = json.loads(_b64_decode(body).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token payload.") from exc
    exp = int(payload.get("exp") or 0)
    if exp <= int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired.")
    return payload


def _issue_user_token(identity: TrustedIdentity, *, remember: bool = False) -> tuple[str, datetime]:
    policy = load_auth_policy()
    ttl = max(policy.session_timeout_seconds, 300)
    if remember:
        ttl = max(ttl, 7 * 24 * 60 * 60)
    expires_at = datetime.now(tz=UTC) + timedelta(seconds=ttl)
    payload = {
        "typ": "user",
        "sub": identity.username,
        "role": identity.role,
        "display_name": identity.display_name,
        "email": identity.email,
        "iat": int(time.time()),
        "exp": int(expires_at.timestamp()),
        "nonce": secrets.token_urlsafe(8),
    }
    return _signed_token(payload), expires_at


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Invalid authorization header.")
    return token.strip()


def _identity_from_payload(payload: dict[str, Any]) -> TrustedIdentity:
    if payload.get("typ") != "user":
        raise HTTPException(status_code=401, detail="Invalid token type.")
    username = str(payload.get("sub") or "").strip().lower()
    if not username:
        raise HTTPException(status_code=401, detail="Missing token subject.")
    return TrustedIdentity(
        username=username,
        role=str(payload.get("role") or "viewer"),
        display_name=str(payload.get("display_name") or username),
        email=str(payload.get("email") or ""),
    )


def current_identity(authorization: str | None = Header(default=None)) -> TrustedIdentity:
    payload = _decode_signed_token(_extract_bearer(authorization))
    return _identity_from_payload(payload)


def optional_identity(authorization: str | None = Header(default=None)) -> TrustedIdentity:
    if not authorization:
        return GUEST_IDENTITY
    payload = _decode_signed_token(_extract_bearer(authorization))
    return _identity_from_payload(payload)


def require_permission(permission: str) -> Callable[[TrustedIdentity], TrustedIdentity]:
    def dependency(identity: TrustedIdentity = Depends(current_identity)) -> TrustedIdentity:
        if not role_has_permission(identity.role, permission):
            raise HTTPException(status_code=403, detail=f"Permission required: {permission}")
        return identity

    return dependency


def require_role(*roles: str) -> Callable[[TrustedIdentity], TrustedIdentity]:
    allowed = set(roles)

    def dependency(identity: TrustedIdentity = Depends(current_identity)) -> TrustedIdentity:
        if identity.role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient role.")
        return identity

    return dependency


def require_ops_read(identity: TrustedIdentity = Depends(current_identity)) -> TrustedIdentity:
    if identity.role not in OPS_READ_ROLES:
        raise HTTPException(status_code=403, detail="Operations Studio requires an elevated role.")
    return identity


def _require_confirm_text(value: str) -> None:
    if str(value or "").strip() != OPS_CONFIRM_TEXT:
        raise HTTPException(status_code=400, detail=f"confirm_text must match {OPS_CONFIRM_TEXT!r}.")


def _runtime_cache_key() -> tuple[str, str, str, str]:
    return (
        str(os.getenv("HELMET_CONFIG_PATH") or ""),
        str(os.getenv("HELMET_STORAGE_BACKEND") or os.getenv("HELMET_REPOSITORY_BACKEND") or ""),
        str(os.getenv("SUPABASE_URL") or ""),
        str(os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""),
    )


def _runtime_registry_signature() -> str:
    payload = stable_cache_key(_runtime_cache_key()).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def _read_cache_key(key: Any) -> str:
    return f"read:{stable_cache_key(key)}"


def _close_runtime_service_bundle(services: RuntimeServices) -> None:
    try:
        services.repository.close()
    except Exception:
        pass


def invalidate_runtime_services() -> None:
    """
    Invalidate runtime services cache.

    Optimization: Uses unified cache manager instead of dual cache.
    """
    cache = get_cache_manager()
    with _UNIFIED_CACHE_LOCK:
        stale_services = list(_RUNTIME_SERVICES_REGISTRY.values())
        _RUNTIME_SERVICES_REGISTRY.clear()
    for services in stale_services:
        _close_runtime_service_bundle(services)
    cache.invalidate_pattern("runtime:*")
    cache.invalidate_pattern("read:*")


def _read_cache_get(key: Any) -> Any | None:
    """
    Get value from read cache.

    Optimization: Uses unified TieredCacheManager instead of separate _READ_CACHE.
    """
    cache = get_cache_manager()
    return cache.get(_read_cache_key(key), CacheTier.METRICS)


def _read_cache_set(key: Any, payload: Any) -> Any:
    """
    Set value in read cache.

    Optimization: Uses unified TieredCacheManager instead of separate _READ_CACHE.
    """
    cache = get_cache_manager()
    cache.set(_read_cache_key(key), payload, CacheTier.METRICS)
    return payload


def runtime_services() -> RuntimeServices:
    """
    Get or create runtime services (settings, repository, etc.).

    Runtime services are not stored in the shared cache because they contain
    locks, clients, and other live runtime state that should never be deep-copied.
    """
    signature = _runtime_registry_signature()
    with _UNIFIED_CACHE_LOCK:
        cached = _RUNTIME_SERVICES_REGISTRY.get(signature)
        if cached is not None:
            return cached

        settings = load_settings()
        repository = ThreadLockedRepository(build_repository(settings))
        services = RuntimeServices(
            settings=settings,
            repository=repository,
            directory=PersonDirectory(settings),
            evidence_store=EvidenceStore(settings),
            notifier=NotificationService(settings, repository),
            browser_inference=BrowserInferenceEngine(settings),
        )
        _RUNTIME_SERVICES_REGISTRY[signature] = services
        return services


def get_runtime_services() -> RuntimeServices:
    """Compatibility wrapper for startup hooks and external callers."""
    return runtime_services()


def _user_payload(identity: TrustedIdentity) -> dict[str, Any]:
    return {
        **identity.to_record(),
        "permissions": sorted(
            permission
            for permission in ("review.assign", "review.update", "camera.edit", "account.manage")
            if role_has_permission(identity.role, permission)
        ),
        "routes": list(visible_routes_for_role(identity.role)),
    }


def _public_root_candidates() -> list[Path]:
    return [
        REPO_ROOT / "dist" / "landing.html",
        REPO_ROOT / "helmet_safety_landing.html",
        REPO_ROOT / "dist" / "index.html",
    ]


def _app_frontend_candidates() -> list[Path]:
    return [
        REPO_ROOT / "dist" / "app",
        REPO_ROOT / "frontend-react" / "build",
        REPO_ROOT / "frontend",
    ]


def _allowed_media_roots(settings) -> list[Path]:
    roots = [
        REPO_ROOT / "artifacts",
        REPO_ROOT / "data" / "hard_cases",
        settings.resolve_path(settings.persistence.snapshot_dir),
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        resolved = root.resolve()
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_safe_media_path(raw_path: str, settings) -> Path:
    candidate = Path(str(raw_path))
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    resolved = candidate.resolve()
    if not any(_is_relative_to(resolved, root) for root in _allowed_media_roots(settings)):
        raise HTTPException(status_code=403, detail="Media path is outside allowed artifact roots.")
    return resolved


def _media_state(path: str | None, url: str | None, settings) -> str:
    if url:
        return "remote_url"
    if not path:
        return "missing"
    try:
        resolved = _resolve_safe_media_path(path, settings)
    except HTTPException:
        return "blocked"
    if not resolved.exists() or not resolved.is_file():
        return "missing"
    return "available"


def _media_token(path: str, settings) -> str | None:
    if not path:
        return None
    try:
        resolved = _resolve_safe_media_path(path, settings)
    except HTTPException:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    payload = {
        "typ": "media",
        "path": str(resolved),
        "iat": int(time.time()),
        "exp": int(time.time()) + MEDIA_TOKEN_SECONDS,
        "nonce": secrets.token_urlsafe(8),
    }
    return _signed_token(payload)


def _media_url(path: str | None, settings) -> str | None:
    token = _media_token(str(path or ""), settings)
    if not token:
        return None
    return f"{API_PREFIX}/media/{token}"


def _decorate_alert(alert: dict[str, Any], settings, *, include_media: bool = True) -> dict[str, Any]:
    item = dict(alert)
    for name in ("snapshot", "clip", "face_crop", "badge_crop", "remediation_snapshot"):
        url_key = f"{name}_url"
        path_key = f"{name}_path"
        display_key = f"{name}_display_url"
        state_key = f"{name}_media_state"
        raw_url = str(item.get(url_key) or "").strip()
        raw_path = str(item.get(path_key) or "").strip()
        item[state_key] = _media_state(raw_path, raw_url, settings)
        if not include_media:
            item[display_key] = None
        elif raw_url:
            item[display_key] = raw_url
        elif raw_path:
            item[display_key] = _media_url(raw_path, settings)
        else:
            item[display_key] = None
        item.pop(path_key, None)
    return item


def _compact_alert_payload(alert: dict[str, Any]) -> dict[str, Any]:
    return {key: alert.get(key) for key in COMPACT_ALERT_FIELDS if key in alert}


def _decorate_case(case: dict[str, Any], repository: AlertRepository, settings, *, include_media: bool = True) -> dict[str, Any]:
    item = dict(case)
    alert_id = str(item.get("alert_id") or "")
    alert = repository.get_alert(alert_id) if alert_id else None
    if alert:
        item.setdefault("camera_id", alert.get("camera_id"))
        item.setdefault("camera_name", alert.get("camera_name"))
        item.setdefault("department", alert.get("department"))
        item.setdefault("person_name", alert.get("person_name"))
    raw_url = str(item.get("snapshot_url") or "").strip()
    raw_path = str(item.get("snapshot_path") or "").strip()
    item["snapshot_media_state"] = _media_state(raw_path, raw_url, settings)
    if not include_media:
        item["snapshot_display_url"] = None
    elif raw_url:
        item["snapshot_display_url"] = raw_url
    else:
        item["snapshot_display_url"] = _media_url(raw_path, settings)
    item.pop("snapshot_path", None)
    return item


def _decorate_visitor_evidence(record: dict[str, Any], settings, *, include_media: bool = True) -> dict[str, Any]:
    item = dict(record)
    raw_url = str(item.get("snapshot_url") or "").strip()
    raw_path = str(item.get("snapshot_path") or "").strip()
    item["snapshot_media_state"] = _media_state(raw_path, raw_url, settings)
    if not include_media:
        item["snapshot_display_url"] = None
    elif raw_url:
        item["snapshot_display_url"] = raw_url
    else:
        item["snapshot_display_url"] = _media_url(raw_path, settings)
    item.pop("snapshot_path", None)
    return item


def _camera_payload_for_identity(camera: dict[str, Any], identity: TrustedIdentity) -> dict[str, Any]:
    item = dict(camera)
    can_edit = role_has_permission(identity.role, "camera.edit")
    source = str(item.get("source") or "")
    if not can_edit:
        item["alert_emails"] = []
        if "://" in source or "@" in source:
            item["source"] = "remote_stream_configured"
        elif source.startswith("${") and source.endswith("}"):
            item["source"] = source
        elif source.startswith("env:"):
            item["source"] = source
        elif source:
            item["source"] = source
        else:
            item["source"] = ""
    return item


def _configured_camera_ids(settings, repository: AlertRepository) -> set[str]:
    _, merged = merge_live_cameras(settings, repository.list_cameras())
    return {
        str(item.get("camera_id") or "").strip()
        for item in merged
        if str(item.get("camera_id") or "").strip()
    }


def _live_frame_root(settings) -> Path:
    return operations_paths(settings)["live_frames_dir"].resolve()


def _resolve_live_frame_path(
    settings,
    repository: AlertRepository,
    camera_id: str,
    *,
    valid_ids: set[str] | None = None,
) -> Path:
    normalized = str(camera_id or "").strip()
    allowed = valid_ids if valid_ids is not None else _configured_camera_ids(settings, repository)
    if not normalized or normalized not in allowed:
        raise HTTPException(status_code=404, detail="Camera is not configured.")
    if any(separator in normalized for separator in ("/", "\\")):
        raise HTTPException(status_code=400, detail="Invalid camera_id.")
    root = _live_frame_root(settings)
    resolved = (root / f"{normalized}.jpg").resolve()
    if not _is_relative_to(resolved, root):
        raise HTTPException(status_code=403, detail="Live frame path is outside the preview directory.")
    return resolved


def _camera_source_kind(source: str) -> str:
    normalized = str(source or "").strip()
    if not normalized:
        return "unknown"
    if is_local_device_source(normalized):
        return "local_device"
    if normalized.startswith("${") and normalized.endswith("}"):
        return "env_placeholder"
    if normalized.startswith("env:"):
        return "env_reference"
    if "://" in normalized:
        return "remote_stream"
    return "local_path"


def _live_frame_state(
    settings,
    repository: AlertRepository,
    camera_id: str,
    *,
    now: datetime | None = None,
    valid_ids: set[str] | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(tz=UTC)
    frame_entry = get_live_frame_hub().get(camera_id)
    if frame_entry is not None:
        updated_at = frame_entry.updated_at.astimezone(UTC)
        return {
            "has_live_frame": True,
            "frame_updated_at": updated_at.isoformat(),
            "frame_age_seconds": max(0, round((current - updated_at).total_seconds(), 2)),
            "frame_url": f"{API_PREFIX}/cameras/{camera_id}/frame.jpg",
            "stream_url": f"{API_PREFIX}/cameras/{camera_id}/stream.mjpg",
            "frame_sequence": frame_entry.sequence,
        }
    path = _resolve_live_frame_path(settings, repository, camera_id, valid_ids=valid_ids)
    if not path.exists() or not path.is_file():
        return {
            "has_live_frame": False,
            "frame_updated_at": None,
            "frame_age_seconds": None,
            "frame_url": None,
            "stream_url": None,
            "frame_sequence": None,
        }
    stat = path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    return {
        "has_live_frame": True,
        "frame_updated_at": updated_at.isoformat(),
        "frame_age_seconds": max(0, round((current - updated_at).total_seconds(), 2)),
        "frame_url": f"{API_PREFIX}/cameras/{camera_id}/frame.jpg",
        "stream_url": f"{API_PREFIX}/cameras/{camera_id}/stream.mjpg",
        "frame_sequence": None,
    }


def _safe_camera_error(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    lowered = text.lower()
    if any(marker in lowered for marker in ("rtsp://", "rtsps://", "rtmp://", "rtmps://", "http://", "https://")):
        return "Remote stream is unavailable. Check the configured source on the host."
    if ":\\" in text or text.startswith(("/", "\\")):
        return "Camera stream is unavailable. Check the local source on the host."
    return text


def _live_camera_payload(
    camera: dict[str, Any],
    settings,
    repository: AlertRepository,
    *,
    now: datetime | None = None,
    valid_ids: set[str] | None = None,
) -> dict[str, Any]:
    camera_id = str(camera.get("camera_id") or "").strip()
    source = str(camera.get("source") or "").strip()
    frame_state = _live_frame_state(settings, repository, camera_id, now=now, valid_ids=valid_ids)
    return {
        "camera_id": camera_id,
        "camera_name": camera.get("camera_name") or camera_id,
        "enabled": camera.get("enabled") is not False,
        "is_enabled": camera.get("enabled") is not False,
        "location": camera.get("location") or "",
        "department": camera.get("department") or "",
        "site_name": camera.get("site_name") or "",
        "building_name": camera.get("building_name") or "",
        "floor_name": camera.get("floor_name") or "",
        "workshop_name": camera.get("workshop_name") or "",
        "zone_name": camera.get("zone_name") or "",
        "responsible_department": camera.get("responsible_department") or camera.get("department") or "",
        "last_status": camera.get("last_status") or camera.get("status") or "configured",
        "last_seen_at": camera.get("last_seen_at"),
        "last_frame_at": camera.get("last_frame_at"),
        "last_fps": camera.get("last_fps"),
        "last_error": _safe_camera_error(camera.get("last_error")),
        "preview_updated_at": camera.get("preview_updated_at") or frame_state["frame_updated_at"],
        "browser_preview_supported": bool(camera.get("enabled") is not False and is_local_device_source(source)),
        "browser_infer_url": f"{API_PREFIX}/cameras/{camera_id}/browser-infer",
        "source_kind": _camera_source_kind(source),
        "selectable": bool(camera_id),
        "display_group": (
            "disabled"
            if camera.get("enabled") is False
            else "local"
            if is_local_device_source(source)
            else "remote"
        ),
        **frame_state,
    }


def _live_mjpeg_generator(frame_path: Path, *, interval_seconds: float = 0.12):
    last_mtime_ns = -1
    while True:
        try:
            stat = frame_path.stat()
            if stat.st_mtime_ns == last_mtime_ns:
                time.sleep(interval_seconds)
                continue
            payload = frame_path.read_bytes()
            last_mtime_ns = stat.st_mtime_ns
        except OSError:
            time.sleep(interval_seconds)
            continue
        yield b"--frame\r\n"
        yield b"Content-Type: image/jpeg\r\n"
        yield f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        yield payload
        yield b"\r\n"
        time.sleep(interval_seconds)


def _live_mjpeg_generator_for_camera(camera_id: str, frame_path: Path, *, interval_seconds: float = 0.12):
    last_sequence = -1
    hub = get_live_frame_hub()
    while True:
        entry = hub.get(camera_id)
        if entry is not None and entry.sequence != last_sequence:
            payload = entry.payload
            last_sequence = entry.sequence
            yield b"--frame\r\n"
            yield b"Content-Type: image/jpeg\r\n"
            yield f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
            yield payload
            yield b"\r\n"
            time.sleep(interval_seconds)
            continue
        if entry is not None:
            time.sleep(interval_seconds)
            continue
        yield from _live_mjpeg_generator(frame_path, interval_seconds=interval_seconds)
        return


def _runtime_path_state(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "exists": resolved.exists(),
        "is_dir": resolved.is_dir(),
        "is_file": resolved.is_file(),
        "writable": os.access(resolved if resolved.exists() else resolved.parent, os.W_OK),
    }


def _safe_path_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = Path(text)
    try:
        resolved = candidate.resolve() if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()
        try:
            return str(resolved.relative_to(REPO_ROOT)).replace("\\", "/")
        except ValueError:
            return resolved.name or text
    except OSError:
        return candidate.name or text


def _release_gate_status(services: RuntimeServices) -> dict[str, Any]:
    quality_payload = build_quality_summary(services.settings, services.repository, services.directory)
    readiness_payload = build_readiness_payload(services.settings)
    readiness_blockers = [
        {
            "check_id": str(item.get("check_id") or ""),
            "status": str(item.get("status") or ""),
            "detail": str(item.get("detail") or ""),
        }
        for item in readiness_payload.get("checks", [])
        if str(item.get("status") or "").lower() in {"missing", "invalid"}
    ]
    return {
        "quality_payload": quality_payload,
        "readiness_payload": readiness_payload,
        "quality_ready": quality_payload.get("promotion_gate", {}).get("status") == "ready",
        "readiness_ready": not readiness_blockers,
        "readiness_blockers": readiness_blockers,
    }


def _normalize_list_param(value: str | None) -> set[str] | None:
    if not value:
        return None
    items = {item.strip() for item in str(value).split(",") if item.strip()}
    return items or None


def _list_alerts_with_offset(
    repository: AlertRepository,
    *,
    limit: int,
    offset: int,
    since: datetime | None = None,
    camera_id: str | None = None,
    status: str | None = None,
    identity_status: str | None = None,
    department: str | None = None,
    text_query: str = "",
) -> dict[str, Any]:
    remaining_offset = max(0, int(offset))
    page_limit = max(1, min(int(limit), 500))
    cursor: str | None = None
    skipped_total = 0
    while remaining_offset > 0:
        page = repository.list_alerts_page(
            limit=min(remaining_offset, 500),
            since=since,
            camera_id=camera_id,
            status=status,
            identity_status=identity_status,
            department=department,
            text_query=text_query,
            cursor=cursor,
        )
        items = page.get("items") or []
        skipped_total += len(items)
        remaining_offset -= len(items)
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not items or not cursor:
            return {
                "items": [],
                "total": int(page.get("total") or skipped_total),
                "limit": page_limit,
                "cursor": cursor,
                "next_cursor": None,
                "has_more": False,
                "offset": max(0, int(offset)),
            }

    page = repository.list_alerts_page(
        limit=page_limit,
        since=since,
        camera_id=camera_id,
        status=status,
        identity_status=identity_status,
        department=department,
        text_query=text_query,
        cursor=cursor,
    )
    return {
        **page,
        "offset": max(0, int(offset)),
    }


def _account_payload(account: AuthAccount, *, editable: bool) -> dict[str, Any]:
    return {
        "username": account.username,
        "role": account.role,
        "display_name": account.display_name,
        "email": account.email,
        "source": account.source,
        "editable": editable,
    }


def _validate_password_for_write(password: str) -> str:
    normalized = str(password or "")
    if len(normalized) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    return normalized


auth_router = APIRouter(tags=["auth"])
helmet_router = APIRouter(prefix=API_PREFIX, tags=["helmet"])


@auth_router.post("/auth/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    _ensure_environment_loaded()
    username = str(payload.username or "").strip().lower()
    password = str(payload.password or "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    if not auth_configuration_summary()["configured"]:
        raise HTTPException(status_code=503, detail="Console authentication is not configured.")

    with _AUTH_WRITE_LOCK:
        state = get_login_lockout_state(username)
        if state.is_locked:
            raise HTTPException(status_code=423, detail=f"Account is locked for {state.remaining_seconds()} seconds.")

        identity = authenticate_user(username, password)
        if identity is None:
            next_state = register_login_failure(username)
            if next_state.is_locked:
                raise HTTPException(status_code=423, detail=f"Account locked for {next_state.remaining_seconds()} seconds.")
            policy = load_auth_policy()
            remaining = max(0, policy.max_failed_attempts - next_state.failed_attempts)
            raise HTTPException(status_code=401, detail=f"Invalid username or password. {remaining} attempt(s) remaining.")

        clear_login_failures(username)
    token, expires_at = _issue_user_token(identity, remember=payload.remember)
    return {"token": token, "user": _user_payload(identity), "expires_at": expires_at.isoformat()}


@auth_router.post("/auth/register")
def register(payload: RegisterRequest) -> dict[str, Any]:
    _ensure_environment_loaded()
    username = str(payload.username or "").strip().lower()
    password = _validate_password_for_write(payload.password)
    if not username:
        raise HTTPException(status_code=400, detail="username is required.")
    with _AUTH_WRITE_LOCK:
        if any(item.username == username for item in load_auth_accounts()):
            raise HTTPException(status_code=409, detail="Account already exists.")

        account = AuthAccount(
            username=username,
            role="admin",
            display_name=str(payload.display_name or "").strip() or username,
            email=str(payload.email or "").strip() or username,
            password_hash=hash_password(password),
            source="managed_file",
        )
        upsert_managed_auth_account(account)
    invalidate_runtime_services()
    clear_login_failures(username)
    token, expires_at = _issue_user_token(account.to_identity(), remember=payload.remember)
    return {"token": token, "user": _user_payload(account.to_identity()), "expires_at": expires_at.isoformat()}


@auth_router.post("/auth/change-password")
def change_password(
    payload: ChangePasswordRequest,
    identity: TrustedIdentity = Depends(current_identity),
) -> dict[str, Any]:
    _ensure_environment_loaded()
    password = _validate_password_for_write(payload.new_password)
    with _AUTH_WRITE_LOCK:
        managed_accounts = {item.username: item for item in load_managed_auth_accounts()}
        account = managed_accounts.get(identity.username)
        if account is None:
            raise HTTPException(status_code=409, detail="Only managed accounts can change password here.")
        updated = AuthAccount(
            username=account.username,
            role=account.role,
            display_name=account.display_name or identity.display_name or account.username,
            email=account.email or identity.email,
            password_hash=hash_password(password),
            source="managed_file",
        )
        upsert_managed_auth_account(updated)
    invalidate_runtime_services()
    clear_login_failures(identity.username)
    return {"changed": identity.username}


@auth_router.get("/auth/me")
def me(identity: TrustedIdentity = Depends(optional_identity)) -> dict[str, Any]:
    _ensure_environment_loaded()
    return {"user": _user_payload(identity)}


@helmet_router.get("/platform/overview")
def platform_overview(
    days: int = 7,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    cache = get_cache_manager()
    cache_key = ("overview", _runtime_cache_key(), identity.role, max(1, int(days)))
    cached = cache.get(cache_key, CacheTier.SUMMARIES)
    if cached is not None:
        return cached
    payload = build_overview_payload(services.settings, services.repository, days=days, recent_limit=12, evidence_limit=6)
    payload["user"] = _user_payload(identity)
    payload["recent_alerts"] = [
        _compact_alert_payload(_decorate_alert(item, services.settings, include_media=False))
        for item in payload["recent_alerts"]
    ]
    payload["evidence_alerts"] = [
        _compact_alert_payload(_decorate_alert(item, services.settings, include_media=True))
        for item in payload["evidence_alerts"]
    ]
    payload["evidence_alerts_available"] = [
        item for item in payload["evidence_alerts"] if str(item.get("snapshot_media_state") or "") == "available"
    ]
    payload["evidence_alerts_unavailable"] = [
        item for item in payload["evidence_alerts"] if str(item.get("snapshot_media_state") or "") != "available"
    ]
    visitor_summary = payload.get("visitor_evidence_summary") or {}
    visitor_items = visitor_summary.get("items") or []
    payload["visitor_evidence_summary"] = {
        **visitor_summary,
        "items": [_decorate_visitor_evidence(item, services.settings, include_media=True) for item in visitor_items],
    }
    payload["cameras"] = [_camera_payload_for_identity(item, identity) for item in payload.get("cameras", [])]
    service_summary = build_services_payload(services.settings, services.repository)
    identity_summary = build_identity_summary(services.settings, services.directory)
    delivery_summary = build_evidence_delivery_summary(services.settings, services.repository)
    payload["operations"] = {
        "services": {
            "monitor": service_summary.get("services", {}).get("monitor", {}).get("status"),
            "dashboard": service_summary.get("services", {}).get("dashboard", {}).get("status"),
            "camera_preview": service_summary.get("services", {}).get("camera_preview", {}).get("status"),
        },
        "identity": {
            "active_people": identity_summary.get("active_people", 0),
            "people_with_camera_bindings": identity_summary.get("people_with_camera_bindings", 0),
            "people_with_face_samples": identity_summary.get("people_with_face_samples", 0),
        },
        "delivery": {
            "email_enabled": delivery_summary.get("notifications", {}).get("email_enabled", False),
            "storage_backend": delivery_summary.get("storage", {}).get("requested_backend", services.settings.repository_backend),
            "private_bucket": delivery_summary.get("storage", {}).get("private_bucket", False),
        },
    }
    cache.set(cache_key, payload, CacheTier.SUMMARIES)
    return payload


@helmet_router.get("/public/landing")
def public_landing(services: RuntimeServices = Depends(runtime_services)) -> dict[str, Any]:
    cache_key = ("public_landing", _runtime_cache_key())
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    payload = build_overview_payload(services.settings, services.repository, days=7)
    return _read_cache_set(cache_key, {
        "generated_at": payload["generated_at"],
        "metrics": payload["metrics"],
        "camera_summary": payload["camera_summary"],
        "repository_backend": payload["repository_backend"],
    })


@helmet_router.get("/visitor-evidence")
def visitor_evidence(
    limit: int = 20,
    camera_id: str | None = None,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    capped = max(1, min(int(limit), 100))
    items = services.repository.list_visitor_evidence(camera_id=camera_id, limit=capped)
    return {
        "items": [_decorate_visitor_evidence(item, services.settings, include_media=True) for item in items],
        "limit": capped,
    }


@helmet_router.post("/visitor-evidence")
async def create_visitor_evidence(
    visitor_name: str = Form(default=""),
    visitor_company: str = Form(default=""),
    visit_reason: str = Form(default=""),
    note: str = Form(default=""),
    camera_id: str = Form(default=""),
    snapshot: UploadFile = File(...),
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    if snapshot is None or not snapshot.filename:
        raise HTTPException(status_code=400, detail="snapshot is required.")
    file_bytes = await snapshot.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="snapshot is required.")

    _, merged_cameras = merge_live_cameras(services.settings, services.repository.list_cameras())
    camera_lookup = {
        str(item.get("camera_id") or "").strip(): item
        for item in merged_cameras
        if str(item.get("camera_id") or "").strip()
    }
    normalized_camera_id = str(camera_id or "").strip()
    current = utc_now()
    record_id = f"visitor-{uuid.uuid4().hex[:16]}"
    extension = Path(snapshot.filename or "snapshot.jpg").suffix or ".jpg"
    storage_camera_id = normalized_camera_id or "visitor-desk"
    snapshot_path, snapshot_url = services.evidence_store.save_bytes(
        storage_camera_id,
        file_bytes,
        record_id,
        current,
        category="visitor_evidence",
        extension=extension,
        content_type=snapshot.content_type or "image/jpeg",
    )
    record = {
        "record_id": record_id,
        "visitor_name": str(visitor_name or "").strip() or "Guest Visitor",
        "visitor_company": str(visitor_company or "").strip(),
        "visit_reason": str(visit_reason or "").strip(),
        "note": str(note or "").strip(),
        "camera_id": normalized_camera_id,
        "camera_name": camera_lookup.get(normalized_camera_id, {}).get("camera_name") or "",
        "snapshot_path": snapshot_path,
        "snapshot_url": snapshot_url,
        "created_at": current.isoformat(),
        "created_by": identity.username,
        "created_role": identity.role,
    }
    stored = services.repository.insert_visitor_evidence(record)
    invalidate_runtime_services()
    return {"record": _decorate_visitor_evidence(stored, services.settings, include_media=True)}


@helmet_router.get("/alerts")
def list_alerts(
    q: str = "",
    status: str | None = None,
    identity_status: str | None = None,
    department: str | None = None,
    camera_id: str | None = None,
    days: int = 7,
    limit: int = 100,
    offset: int = 0,
    cursor: str | None = None,
    mode: str = "compact",
    include_media: bool = False,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    # Use tiered cache with 30s TTL for alert summaries
    cache = get_cache_manager()
    cache_key = CacheKeyBuilder.alerts_list(
        q=q,
        status=status,
        identity_status=identity_status,
        department=department,
        camera_id=camera_id,
        days=days,
        limit=limit,
        offset=offset,
        cursor=cursor,
        mode=mode,
        include_media=include_media,
    )

    cached = cache.get(cache_key, CacheTier.SUMMARIES)
    if cached is not None:
        return cached

    since = datetime.now(tz=UTC) - timedelta(days=max(1, int(days)))
    start = max(0, int(offset))
    capped_limit = max(1, min(int(limit), 500))
    if cursor:
        page = services.repository.list_alerts_page(
            limit=capped_limit,
            since=since,
            camera_id=camera_id,
            status=status,
            identity_status=identity_status,
            department=department,
            text_query=q,
            cursor=cursor,
        )
    else:
        page = _list_alerts_with_offset(
            services.repository,
            limit=capped_limit,
            offset=start,
            since=since,
            camera_id=camera_id,
            status=status,
            identity_status=identity_status,
            department=department,
            text_query=q,
        )
    capped = page.get("items") or []
    detailed = str(mode).strip().lower() == "detail"
    rows = [_decorate_alert(item, services.settings, include_media=bool(include_media or detailed)) for item in capped]
    if not detailed:
        rows = [_compact_alert_payload(item) for item in rows]

    result = {
        "items": rows,
        "total": int(page.get("total") or len(rows)),
        "offset": 0 if cursor else start,
        "limit": capped_limit,
        "cursor": cursor,
        "next_cursor": page.get("next_cursor"),
        "has_more": bool(page.get("has_more")),
    }
    cache.set(cache_key, result, CacheTier.SUMMARIES)
    return result


@helmet_router.get("/alerts/{alert_id}")
def get_alert(
    alert_id: str,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    # Use tiered cache with 30s TTL for alert details
    cache = get_cache_manager()
    cache_key = CacheKeyBuilder.alert_detail(alert_id)

    cached = cache.get(cache_key, CacheTier.SUMMARIES)
    if cached is not None:
        return cached

    alert = services.repository.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")

    result = {
        "alert": _decorate_alert(alert, services.settings, include_media=True),
        "actions": services.repository.list_alert_actions(alert_id=alert_id, limit=100),
        "notifications": services.repository.list_notification_logs(alert_id=alert_id, limit=100),
    }
    cache.set(cache_key, result, CacheTier.SUMMARIES)
    return result


@helmet_router.post("/alerts/{alert_id}/assign")
def assign_alert(
    alert_id: str,
    payload: AssignRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_permission("review.assign")),
) -> dict[str, Any]:
    alert = services.repository.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    from helmet_monitoring.services.workflow import AlertWorkflowService

    workflow = AlertWorkflowService(services.repository, repo_root=REPO_ROOT)
    workflow.assign(
        alert,
        actor=identity.username,
        actor_role=identity.role,
        assignee=payload.assignee.strip(),
        assignee_email=payload.assignee_email.strip(),
        note=payload.note.strip() or None,
    )
    updated = services.repository.get_alert(alert_id) or alert

    # Invalidate related caches
    cache = get_cache_manager()
    for pattern in CacheInvalidator.on_alert_updated(alert_id):
        cache.invalidate_pattern(pattern)

    dispatch_topic_message("alerts", "alert_updated", {"alert_id": alert_id, "updates": _compact_alert_payload(_decorate_alert(updated, services.settings, include_media=False))})
    invalidate_runtime_services()
    return {"alert": _decorate_alert(updated, services.settings, include_media=True)}


@helmet_router.post("/alerts/{alert_id}/status")
async def update_alert_status(
    alert_id: str,
    new_status: str = Form(...),
    note: str = Form(default=""),
    person_id: str = Form(default=""),
    remediation_snapshot: UploadFile | None = File(default=None),
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_permission("review.update")),
) -> dict[str, Any]:
    alert = services.repository.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")

    remediation_path = None
    remediation_url = None
    if remediation_snapshot is not None and remediation_snapshot.filename:
        file_bytes = await remediation_snapshot.read()
        extension = Path(remediation_snapshot.filename).suffix or ".jpg"
        remediation_path, remediation_url = services.evidence_store.save_bytes(
            alert.get("camera_id") or "manual",
            file_bytes,
            f"{alert_id}_remediation",
            datetime.now(tz=UTC),
            category="remediation",
            extension=extension,
            content_type=remediation_snapshot.content_type or "image/jpeg",
        )

    corrected_identity = None
    if person_id:
        person = services.directory.get_person_by_id(person_id)
        if person is None:
            raise HTTPException(status_code=404, detail="Person not found.")
        corrected_identity = {
            "person_id": person.get("person_id"),
            "person_name": person.get("name"),
            "employee_id": person.get("employee_id"),
            "department": person.get("department"),
            "team": person.get("team"),
            "role": person.get("role"),
            "phone": person.get("phone"),
            "identity_status": "resolved",
            "identity_source": "manual_review",
        }

    from helmet_monitoring.services.workflow import AlertWorkflowService

    workflow = AlertWorkflowService(services.repository, repo_root=REPO_ROOT)
    workflow.update_status(
        alert,
        actor=identity.username,
        actor_role=identity.role,
        new_status=new_status,
        note=note.strip() or None,
        corrected_identity=corrected_identity,
        remediation_snapshot_path=remediation_path,
        remediation_snapshot_url=remediation_url,
    )
    updated = services.repository.get_alert(alert_id) or alert

    # Invalidate related caches
    cache = get_cache_manager()
    for pattern in CacheInvalidator.on_alert_status_changed(alert_id):
        cache.invalidate_pattern(pattern)

    dispatch_topic_message("alerts", "alert_updated", {"alert_id": alert_id, "updates": _compact_alert_payload(_decorate_alert(updated, services.settings, include_media=False))})
    invalidate_runtime_services()
    return {"alert": _decorate_alert(updated, services.settings, include_media=True)}


@helmet_router.get("/people")
def people(
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(current_identity),
) -> dict[str, Any]:
    # Use tiered cache with 60s TTL for people list
    cache = get_cache_manager()
    cache_key = CacheKeyBuilder.people_list()

    cached = cache.get(cache_key, CacheTier.CAMERAS)
    if cached is not None:
        return cached

    result = {"items": services.directory.get_people()}
    cache.set(cache_key, result, CacheTier.CAMERAS)
    return result


@helmet_router.get("/cameras")
def cameras(
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    # Use tiered cache with 60s TTL for cameras list
    cache = get_cache_manager()
    cache_key = f"{CacheKeyBuilder.cameras_list()}:role={identity.role}"

    cached = cache.get(cache_key, CacheTier.CAMERAS)
    if cached is not None:
        return cached

    _, merged = merge_live_cameras(services.settings, services.repository.list_cameras())
    result = {"items": [_camera_payload_for_identity(item, identity) for item in merged]}
    cache.set(cache_key, result, CacheTier.CAMERAS)
    return result


@helmet_router.get("/cameras/live")
def live_cameras(
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    now = datetime.now(tz=UTC)
    _, merged = merge_live_cameras(services.settings, services.repository.list_cameras())
    valid_ids = {
        str(item.get("camera_id") or "").strip()
        for item in merged
        if str(item.get("camera_id") or "").strip()
    }
    return {
        "generated_at": now.isoformat(),
        "items": [
            _live_camera_payload(item, services.settings, services.repository, now=now, valid_ids=valid_ids)
            for item in merged
        ],
    }


@helmet_router.get("/cameras/{camera_id}/frame.jpg")
def live_camera_frame(
    camera_id: str,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> Response:
    frame_path = _resolve_live_frame_path(services.settings, services.repository, camera_id)
    entry = get_live_frame_hub().get(camera_id)
    if entry is not None:
        return Response(
            content=entry.payload,
            media_type=entry.content_type,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    if not frame_path.exists() or not frame_path.is_file():
        raise HTTPException(status_code=404, detail="Live frame is not available yet.")
    return FileResponse(
        frame_path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _stream_live_camera(
    camera_id: str,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> StreamingResponse:
    frame_path = _resolve_live_frame_path(services.settings, services.repository, camera_id)
    entry = get_live_frame_hub().get(camera_id)
    if entry is None and (not frame_path.exists() or not frame_path.is_file()):
        raise HTTPException(status_code=404, detail="Live stream is not available yet.")
    interval = 1.0 / max(1.0, float(getattr(services.settings.monitoring, "preview_fps", 8.0) or 8.0))
    return StreamingResponse(
        _live_mjpeg_generator_for_camera(camera_id, frame_path, interval_seconds=max(0.05, min(interval, 1.0))),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@helmet_router.get("/cameras/{camera_id}/stream.mjpeg")
def live_camera_stream(
    camera_id: str,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> StreamingResponse:
    return _stream_live_camera(camera_id, services=services, _identity=_identity)


@helmet_router.get("/cameras/{camera_id}/stream.mjpg")
def live_camera_stream_mjpg(
    camera_id: str,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> StreamingResponse:
    return _stream_live_camera(camera_id, services=services, _identity=_identity)


@helmet_router.post("/cameras/{camera_id}/browser-infer")
async def browser_camera_infer(
    camera_id: str,
    request: Request,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    _resolve_live_frame_path(services.settings, services.repository, camera_id)
    if not services.browser_inference.supports_camera(camera_id):
        raise HTTPException(status_code=404, detail="Browser inference is only available for enabled local cameras.")
    payload = await request.body()
    if not payload or len(payload) > 5_000_000:
        raise HTTPException(status_code=400, detail="Invalid frame payload.")
    try:
        return services.browser_inference.detect(camera_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="The camera is not configured for browser preview.") from exc


@helmet_router.post("/cameras")
def upsert_camera(
    payload: CameraUpsertRequest,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(require_permission("camera.edit")),
) -> dict[str, Any]:
    camera_id = payload.camera_id.strip()
    if not camera_id:
        raise HTTPException(status_code=400, detail="camera_id is required.")
    source = payload.source.strip()
    if not is_safe_camera_source_reference(source):
        raise HTTPException(status_code=400, detail="source only accepts local paths, local device indexes, or env placeholders.")
    record = {
        "camera_id": camera_id,
        "camera_name": payload.camera_name.strip() or camera_id,
        "source": source,
        "enabled": bool(payload.enabled),
        "location": payload.location.strip() or "Unknown",
        "department": payload.department.strip() or "Unknown",
        "site_name": payload.site_name.strip() or "Default Site",
        "building_name": payload.building_name.strip() or "Main Building",
        "floor_name": payload.floor_name.strip() or "Floor 1",
        "workshop_name": payload.workshop_name.strip() or "Workshop A",
        "zone_name": payload.zone_name.strip() or "Zone A",
        "responsible_department": payload.responsible_department.strip() or payload.department.strip() or "Unknown",
        "alert_emails": [item.strip() for item in payload.alert_emails if item.strip()],
        "default_person_id": payload.default_person_id.strip(),
    }
    upsert_runtime_camera(services.settings.config_path, record)
    heartbeat = {
        **record,
        "last_status": "configured",
        "last_seen_at": utc_now().isoformat(),
        "retry_count": 0,
        "reconnect_count": 0,
        "last_error": None,
        "last_frame_at": None,
        "last_fps": None,
    }
    services.repository.upsert_camera(heartbeat)
    dispatch_topic_message("cameras", "camera_status", {"camera_id": camera_id, "status": "configured"})
    invalidate_runtime_services()
    return {"camera": heartbeat}


@helmet_router.get("/reports/summary")
def reports_summary(
    days: int = 30,
    preview_limit: int = 20,
    include_rows: bool = False,
    rows_limit: int = 200,
    rows_offset: int = 0,
    status: str | None = None,
    camera_id: str | None = None,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    cache_key = (
        "reports_summary",
        _runtime_cache_key(),
        max(1, int(days)),
        max(0, min(int(preview_limit), 100)),
        bool(include_rows),
        max(1, min(int(rows_limit), 1000)),
        max(0, int(rows_offset)),
        status,
        camera_id,
    )
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    payload = services.repository.get_dashboard_aggregates(
        days=days,
        preview_limit=preview_limit,
        include_rows=include_rows,
        row_offset=rows_offset,
        row_limit=rows_limit,
        status_filters=_normalize_list_param(status),
        camera_filters=_normalize_list_param(camera_id),
    )
    payload["applied_filters"] = payload.get("applied_filters") or {
        "statuses": sorted(_normalize_list_param(status)),
        "camera_ids": sorted(_normalize_list_param(camera_id)),
    }
    payload["preview_rows"] = [
        _compact_alert_payload(_decorate_alert(item, services.settings, include_media=False))
        for item in (payload.get("preview_rows") or payload.get("recent_alerts", []))
    ]
    payload["rows"] = [
        _compact_alert_payload(_decorate_alert(item, services.settings, include_media=False))
        for item in payload.get("rows", [])
    ]
    return _read_cache_set(cache_key, payload)


@helmet_router.get("/reports/rows")
def reports_rows(
    days: int = 30,
    limit: int = 500,
    offset: int = 0,
    cursor: str | None = None,
    status: str | None = None,
    camera_id: str | None = None,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    cache_key = (
        "reports_rows",
        _runtime_cache_key(),
        max(1, int(days)),
        max(1, min(int(limit), 1000)),
        max(0, int(offset)),
        cursor,
        status,
        camera_id,
    )
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    since = datetime.now(tz=UTC) - timedelta(days=max(1, int(days)))
    capped_limit = max(1, min(int(limit), 1000))
    if cursor:
        page = services.repository.list_alerts_page(
            limit=capped_limit,
            since=since,
            camera_id=camera_id,
            status=status,
            cursor=cursor,
        )
        payload = {
            "items": [
                _compact_alert_payload(_decorate_alert(item, services.settings, include_media=False))
                for item in page.get("items", [])
            ],
            "total": int(page.get("total") or 0),
            "offset": 0,
            "limit": capped_limit,
            "cursor": cursor,
            "next_cursor": page.get("next_cursor"),
            "has_more": bool(page.get("has_more")),
        }
    else:
        page = services.repository.get_dashboard_aggregates(
            days=days,
            status_filters=_normalize_list_param(status),
            camera_filters=_normalize_list_param(camera_id),
            include_rows=True,
            row_offset=max(0, int(offset)),
            row_limit=capped_limit,
        )
        payload = {
            "items": [
                _compact_alert_payload(_decorate_alert(item, services.settings, include_media=False))
                for item in page.get("rows", [])
            ],
            "total": int(page.get("rows_total") or 0),
            "offset": max(0, int(offset)),
            "limit": capped_limit,
            "cursor": None,
            "next_cursor": page.get("next_cursor"),
            "has_more": bool(page.get("has_more")),
        }
    return _read_cache_set(cache_key, payload)


@helmet_router.get("/notifications")
def notifications(
    limit: int = 200,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    capped = max(1, min(int(limit), 500))
    return {"items": services.repository.list_notification_logs(limit=capped)}


@helmet_router.post("/notifications/test")
def test_notification(
    payload: TestNotificationRequest,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(require_role("admin", "safety_manager")),
) -> dict[str, Any]:
    result = services.notifier.send_test_email(payload.recipient, payload.subject, payload.body)
    return {"status": result}


@helmet_router.get("/hard-cases")
def hard_cases(
    limit: int = 50,
    offset: int = 0,
    include_media: bool = True,
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    cache_key = ("hard_cases", _runtime_cache_key(), max(1, min(int(limit), 200)), max(0, int(offset)), bool(include_media))
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    capped_limit = max(1, min(int(limit), 200))
    start = max(0, int(offset))
    cases = services.repository.list_hard_cases(limit=500)
    page_cases = cases[start : start + capped_limit]
    decorated = [_decorate_case(item, services.repository, services.settings, include_media=include_media) for item in page_cases]
    recent_cutoff = datetime.now(tz=UTC) - timedelta(days=7)
    return _read_cache_set(cache_key, {
        "items": decorated,
        "total": len(cases),
        "offset": start,
        "limit": capped_limit,
        "metrics": {
            "total": len(cases),
            "recent_7d": sum(parse_timestamp(item.get("created_at")) >= recent_cutoff for item in cases),
            "cameras": len({str(item.get("camera_id") or "") for item in cases if item.get("camera_id")}),
        },
    })


@helmet_router.get("/config/summary")
def config_summary(
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(optional_identity),
) -> dict[str, Any]:
    cache_key = ("config_summary", _runtime_cache_key(), identity.role)
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    settings = services.settings
    _, cameras = merge_live_cameras(settings, services.repository.list_cameras())
    auth_summary = auth_configuration_summary()
    snapshot_root = settings.resolve_path(settings.persistence.snapshot_dir)
    runtime_root = settings.resolve_path(settings.persistence.runtime_dir)
    registry_path = settings.resolve_path(settings.identity.registry_path)
    camera_status = {
        "configured": len(settings.cameras),
        "enabled": sum(1 for camera in settings.cameras if camera.enabled),
        "reporting": sum(
            1
            for camera in cameras
            if str(camera.get("last_status") or camera.get("status") or "").lower()
            in {"running", "healthy", "browser_preview", "configured"}
        ),
        "abnormal": sum(
            1
            for camera in cameras
            if str(camera.get("last_status") or camera.get("status") or "").lower() in {"offline", "error", "failed"}
        ),
    }
    return _read_cache_set(cache_key, {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "user": _user_payload(identity),
        "repository_backend": services.repository.backend_name,
        "storage": {
            "requested_backend": settings.repository_backend,
            "effective_backend": services.repository.backend_name,
            "supabase_configured": bool(settings.supabase.is_configured),
            "upload_to_supabase_storage": bool(settings.persistence.upload_to_supabase_storage),
            "keep_local_copy": bool(settings.persistence.keep_local_copy),
            "use_private_bucket": bool(settings.security.use_private_bucket),
        },
        "auth": {
            "configured": bool(auth_summary["configured"]),
            "enabled_users": int(auth_summary["enabled_users"]),
            "has_admin": bool(auth_summary["has_admin"]),
            "roles": list(auth_summary["roles"]),
            "session_timeout_seconds": int(auth_summary["session_timeout_seconds"]),
        },
        "notifications": {
            "enabled": bool(settings.notifications.enabled),
            "email_enabled": bool(settings.notifications.email_enabled),
            "smtp_host_configured": bool(settings.notifications.smtp_host),
            "smtp_from_configured": bool(settings.notifications.smtp_from_email),
            "default_recipient_count": len(settings.notifications.default_recipients),
        },
        "runtime_paths": {
            "snapshot_dir": _runtime_path_state(snapshot_root),
            "runtime_dir": _runtime_path_state(runtime_root),
            "identity_registry": _runtime_path_state(registry_path),
        },
        "model": {
            "path_configured": bool(settings.model.path),
            "confidence": settings.model.confidence,
            "device": settings.model.device,
            "face_recognition_enabled": bool(settings.face_recognition.enabled),
            "ocr_enabled": bool(settings.ocr.enabled),
        },
        "cameras": {
            **camera_status,
            "items": [_camera_payload_for_identity(item, identity) for item in cameras],
        },
    })


@helmet_router.get("/accounts")
def accounts(
    _identity: TrustedIdentity = Depends(require_permission("account.manage")),
) -> dict[str, Any]:
    _ensure_environment_loaded()
    managed = {item.username for item in load_managed_auth_accounts()}
    return {"items": [_account_payload(item, editable=item.username in managed) for item in load_auth_accounts()]}


@helmet_router.post("/accounts")
def upsert_account(
    payload: AccountUpsertRequest,
    _identity: TrustedIdentity = Depends(require_permission("account.manage")),
) -> dict[str, Any]:
    _ensure_environment_loaded()
    username = payload.username.strip().lower()
    role = payload.role.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="username is required.")
    if role not in ALLOWED_ACCOUNT_ROLES:
        raise HTTPException(status_code=400, detail="Unsupported role.")

    with _AUTH_WRITE_LOCK:
        managed_accounts = {item.username: item for item in load_managed_auth_accounts()}
        existing = managed_accounts.get(username)
        bootstrap_conflict = any(item.username == username and item.username not in managed_accounts for item in load_auth_accounts())
        if bootstrap_conflict:
            raise HTTPException(status_code=409, detail="Bootstrap admin accounts are read-only.")
        if existing is None and not payload.password:
            raise HTTPException(status_code=400, detail="password is required for new accounts.")
        if existing is not None and not payload.password:
            password_hash = existing.password_hash
        else:
            password_hash = hash_password(_validate_password_for_write(payload.password))
        account = AuthAccount(
            username=username,
            role=role,
            display_name=payload.display_name.strip() or username,
            email=payload.email.strip(),
            password_hash=password_hash,
            source="managed_file",
        )
        upsert_managed_auth_account(account)
    invalidate_runtime_services()
    return {"account": _account_payload(account, editable=True)}


@helmet_router.delete("/accounts/{username}")
def delete_account(
    username: str,
    _identity: TrustedIdentity = Depends(require_permission("account.manage")),
) -> dict[str, Any]:
    _ensure_environment_loaded()
    normalized = username.strip().lower()
    with _AUTH_WRITE_LOCK:
        if normalized not in {item.username for item in load_managed_auth_accounts()}:
            raise HTTPException(status_code=404, detail="Managed account not found.")
        delete_managed_auth_account(normalized)
    invalidate_runtime_services()
    return {"deleted": normalized}


@helmet_router.get("/ops/capabilities")
def ops_capabilities(
    _identity: TrustedIdentity = Depends(require_ops_read),
) -> dict[str, Any]:
    return build_capability_matrix_payload()


@helmet_router.get("/ops/readiness")
def ops_readiness(
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(require_ops_read),
) -> dict[str, Any]:
    cache_key = ("ops_readiness", _runtime_cache_key())
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    return _read_cache_set(cache_key, build_readiness_payload(services.settings))


@helmet_router.get("/ops/services")
def ops_services(
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(require_ops_read),
) -> dict[str, Any]:
    cache_key = ("ops_services", _runtime_cache_key())
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    return _read_cache_set(cache_key, build_services_payload(services.settings, services.repository))


@helmet_router.get("/cache/stats")
def cache_stats(
    _identity: TrustedIdentity = Depends(require_ops_read),
) -> dict[str, Any]:
    cache = get_cache_manager()
    return cache.get_stats()


@helmet_router.post("/cache/clear")
def cache_clear(
    tier: str | None = None,
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    cache = get_cache_manager()
    if tier:
        normalized = str(tier).strip().lower()
        cache_tier = next(
            (
                item
                for item in CacheTier
                if item.tier_name == normalized or item.name.lower() == normalized
            ),
            None,
        )
        if cache_tier is None:
            raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}")
        count = cache.invalidate_tier(cache_tier)
        return {"status": "ok", "message": f"Cleared {count} entries from {cache_tier.tier_name} tier"}
    else:
        cache.clear()
        return {"status": "ok", "message": "Cleared all cache tiers"}


@helmet_router.post("/ops/services/{service_name}/action")
def ops_service_action(
    service_name: str,
    payload: ServiceActionRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    _require_confirm_text(payload.confirm_text)
    try:
        result = perform_service_action(
            services.settings,
            service_name=service_name,
            action=payload.action,
            actor=identity.username,
            note=payload.note.strip() or None,
            repository=services.repository,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    invalidate_runtime_services()
    return result


@helmet_router.get("/ops/identity/summary")
def ops_identity_summary(
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(require_ops_read),
) -> dict[str, Any]:
    cache_key = ("ops_identity_summary", _runtime_cache_key())
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    return _read_cache_set(cache_key, build_identity_summary(services.settings, services.directory))


@helmet_router.post("/ops/identity/sync")
def ops_identity_sync(
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    try:
        result = sync_identity_registry(services.settings)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invalidate_runtime_services()
    return {
        **result,
        "performed_by": identity.username,
        "performed_at": utc_now().isoformat(),
    }


@helmet_router.post("/ops/identity/bootstrap-defaults")
def ops_identity_bootstrap_defaults(
    payload: IdentityBootstrapRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = bootstrap_identity_defaults(
        services.settings,
        services.directory,
        apply=bool(payload.apply),
        overwrite=bool(payload.overwrite),
    )
    if result.get("updated_defaults"):
        invalidate_runtime_services()
    return {
        **result,
        "note": payload.note.strip(),
        "performed_by": identity.username,
        "performed_at": utc_now().isoformat(),
    }


@helmet_router.get("/ops/model-feedback")
def ops_model_feedback(
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(require_ops_read),
) -> dict[str, Any]:
    cache_key = ("ops_model_feedback", _runtime_cache_key())
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    return _read_cache_set(cache_key, build_model_feedback_summary(services.settings, services.repository))


@helmet_router.get("/ops/quality-summary")
def ops_quality_summary(
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(require_ops_read),
) -> dict[str, Any]:
    cache_key = ("ops_quality_summary", _runtime_cache_key())
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    return _read_cache_set(cache_key, build_quality_summary(services.settings, services.repository, services.directory))


@helmet_router.post("/ops/model-feedback/export")
def ops_model_feedback_export(
    payload: FeedbackExportRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = export_feedback_cases(
        services.settings,
        services.repository,
        limit=max(1, min(int(payload.limit), 500)),
        case_types=tuple(str(item).strip() for item in payload.case_types if str(item).strip()) or None,
        actor=identity.username,
        note=payload.note.strip() or None,
    )
    invalidate_runtime_services()
    return {
        **result,
        "export_dir": _safe_path_label(result.get("export_dir")),
        "cases": [
            {
                **item,
                "snapshot_path": _safe_path_label(item.get("snapshot_path")),
                "clip_path": _safe_path_label(item.get("clip_path")),
            }
            for item in result.get("cases", [])
        ],
    }


@helmet_router.post("/ops/model-feedback/dataset")
def ops_model_feedback_dataset(
    payload: FeedbackDatasetRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    try:
        result = build_feedback_dataset(
            services.settings,
            base_dataset_yaml=payload.base_dataset_yaml.strip() or "configs/datasets/shwd_yolo26.yaml",
            actor=identity.username,
            note=payload.note.strip() or None,
            repository=services.repository,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invalidate_runtime_services()
    return {
        **result,
        "dataset_yaml": _safe_path_label(result.get("dataset_yaml")),
        "manifest_path": _safe_path_label(result.get("manifest_path")),
        "base_dataset_yaml": _safe_path_label(result.get("base_dataset_yaml")),
    }


@helmet_router.get("/ops/evidence-delivery")
def ops_evidence_delivery(
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(require_ops_read),
) -> dict[str, Any]:
    cache_key = ("ops_evidence_delivery", _runtime_cache_key())
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    return _read_cache_set(cache_key, build_evidence_delivery_summary(services.settings, services.repository))


@helmet_router.post("/ops/evidence-delivery/validate-storage")
def ops_validate_storage(
    payload: DeliveryValidationRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = run_storage_delivery_check(
        services.settings,
        actor=identity.username,
        note=payload.note.strip() or None,
        repository=services.repository,
    )
    invalidate_runtime_services()
    return result


@helmet_router.post("/ops/evidence-delivery/validate-notification")
def ops_validate_notification(
    payload: DeliveryValidationRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = run_notification_delivery_check(
        services.settings,
        actor=identity.username,
        note=payload.note.strip() or None,
        repository=services.repository,
    )
    invalidate_runtime_services()
    return result


@helmet_router.get("/ops/backups")
def ops_backups(
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(require_ops_read),
) -> dict[str, Any]:
    cache_key = ("ops_backups", _runtime_cache_key())
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    return _read_cache_set(cache_key, build_backups_payload(services.settings))


@helmet_router.post("/ops/backups")
def ops_create_backup(
    payload: BackupCreateRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    result = create_backup(
        services.settings,
        include_captures=bool(payload.include_captures),
        backup_name=payload.backup_name.strip() or None,
        actor=identity.username,
        note=payload.note.strip() or None,
        repository=services.repository,
    )
    invalidate_runtime_services()
    return {
        **result,
        "backup_path": _safe_path_label(result.get("backup_path")),
    }


@helmet_router.post("/ops/backups/restore")
def ops_restore_backup(
    payload: BackupRestoreRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    _require_confirm_text(payload.confirm_text)
    try:
        result = restore_backup(
            services.settings,
            payload.backup_path,
            actor=identity.username,
            note=payload.note.strip() or None,
            repository=services.repository,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    invalidate_runtime_services()
    return {
        **result,
        "backup_path": _safe_path_label(result.get("backup_path")),
    }


@helmet_router.get("/ops/releases")
def ops_releases(
    services: RuntimeServices = Depends(runtime_services),
    _identity: TrustedIdentity = Depends(require_ops_read),
) -> dict[str, Any]:
    cache_key = ("ops_releases", _runtime_cache_key())
    cached = _read_cache_get(cache_key)
    if cached is not None:
        return cached
    return _read_cache_set(cache_key, build_releases_payload(services.settings))


@helmet_router.post("/ops/releases/snapshot")
def ops_release_snapshot(
    payload: ReleaseSnapshotRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    if payload.activate:
        gate = _release_gate_status(services)
        if not gate["quality_ready"] or not gate["readiness_ready"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Release activation is blocked by the quality gate or readiness blockers.",
                    "quality_status": gate["quality_payload"].get("promotion_gate", {}).get("status"),
                    "quality_reason": gate["quality_payload"].get("promotion_gate", {}).get("reason"),
                    "readiness_blockers": gate["readiness_blockers"],
                },
            )
    result = create_release_snapshot(
        services.settings,
        release_name=payload.release_name.strip() or None,
        activate=bool(payload.activate),
        actor=identity.username,
        note=payload.note.strip() or None,
        repository=services.repository,
    )
    invalidate_runtime_services()
    return {
        **result,
        "config_snapshot": _safe_path_label(result.get("config_snapshot")),
        "config_path": _safe_path_label(result.get("config_path")),
        "model_path": _safe_path_label(result.get("model_path")),
    }


@helmet_router.post("/ops/releases/activate")
def ops_release_activate(
    payload: ReleaseActionRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    _require_confirm_text(payload.confirm_text)
    gate = _release_gate_status(services)
    if not gate["quality_ready"] or not gate["readiness_ready"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Release activation is blocked by the quality gate or readiness blockers.",
                "quality_status": gate["quality_payload"].get("promotion_gate", {}).get("status"),
                "quality_reason": gate["quality_payload"].get("promotion_gate", {}).get("reason"),
                "readiness_blockers": gate["readiness_blockers"],
            },
        )
    try:
        result = activate_release(
            services.settings,
            release_name=payload.release_name.strip(),
            actor=identity.username,
            note=payload.note.strip() or None,
            repository=services.repository,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    invalidate_runtime_services()
    return {
        **result,
        "config_snapshot": _safe_path_label(result.get("config_snapshot")),
    }


@helmet_router.post("/ops/releases/rollback")
def ops_release_rollback(
    payload: ReleaseActionRequest,
    services: RuntimeServices = Depends(runtime_services),
    identity: TrustedIdentity = Depends(require_role("admin")),
) -> dict[str, Any]:
    _require_confirm_text(payload.confirm_text)
    try:
        result = rollback_release(
            services.settings,
            steps=max(1, int(payload.steps)),
            actor=identity.username,
            note=payload.note.strip() or None,
            repository=services.repository,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    invalidate_runtime_services()
    return {
        **result,
        "config_snapshot": _safe_path_label(result.get("config_snapshot")),
    }


@helmet_router.get("/media/{token}")
def media(token: str, services: RuntimeServices = Depends(runtime_services)) -> FileResponse:
    payload = _decode_signed_token(token)
    if payload.get("typ") != "media":
        raise HTTPException(status_code=401, detail="Invalid media token.")
    resolved = _resolve_safe_media_path(str(payload.get("path") or ""), services.settings)
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Media not found.")
    media_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
    return FileResponse(resolved, media_type=media_type)


def create_app() -> FastAPI:
    app = FastAPI(title="Safety Helmet Command Center")
    raw_origins = os.getenv("HELMET_CORS_ORIGINS", "*").strip()
    origins = ["*"] if raw_origins == "*" else [item.strip() for item in raw_origins.split(",") if item.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def static_cache_policy(request: Request, call_next):
        response: Response = await call_next(request)
        if request.url.path.startswith("/app"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.get("/health")
    def health() -> dict[str, Any]:
        _ensure_environment_loaded()
        summary = auth_configuration_summary()
        return {
            "status": "ok",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "auth_configured": bool(summary["configured"]),
        }

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        for candidate in _public_root_candidates():
            if candidate.exists():
                return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Landing page is not built yet.")

    @app.on_event("startup")
    async def startup_event():
        """Warm cache on startup"""
        try:
            from helmet_monitoring.api.cache_integration import warm_startup_cache
            services = get_runtime_services()
            warm_startup_cache(services)
        except Exception as e:
            print(f"Cache warmup failed: {e}")

    @app.on_event("shutdown")
    async def shutdown_event():
        invalidate_runtime_services()

    app.include_router(auth_router)
    app.include_router(helmet_router)
    app.add_api_websocket_route("/ws/alerts", websocket_alerts_handler)
    app.add_api_websocket_route("/ws/dashboard", websocket_dashboard_handler)
    app.add_api_websocket_route("/ws/cameras", websocket_cameras_handler)

    for frontend_path in _app_frontend_candidates():
        if frontend_path.exists():
            app.mount("/app", StaticFiles(directory=frontend_path, html=True), name="frontend")
            break

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    src_root = REPO_ROOT / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    uvicorn.run("helmet_monitoring.api.app:app", host="127.0.0.1", port=8112, reload=False)
