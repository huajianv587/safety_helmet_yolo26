from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[3]
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


@dataclass(slots=True, frozen=True)
class ModelSettings:
    path: str
    confidence: float = 0.45
    imgsz: int = 640
    device: str = "cpu"
    violation_labels: tuple[str, ...] = ("no_helmet", "person")
    safe_labels: tuple[str, ...] = ("helmet", "hat")


@dataclass(slots=True, frozen=True)
class EventRuleSettings:
    alert_frames: int = 6
    dedupe_seconds: int = 300
    match_distance_pixels: int = 120
    max_track_age_seconds: float = 2.5
    min_confidence_for_alert: float = 0.5


@dataclass(slots=True, frozen=True)
class PersistenceSettings:
    snapshot_dir: str = "artifacts/captures"
    runtime_dir: str = "artifacts/runtime"
    save_annotated_snapshot: bool = True
    upload_to_supabase_storage: bool = True
    storage_prefix: str = "alerts"
    keep_local_copy: bool = True


@dataclass(slots=True, frozen=True)
class MonitoringSettings:
    frame_stride: int = 3
    camera_retry_seconds: float = 5.0
    heartbeat_interval_seconds: float = 10.0
    max_frames: int = 0


@dataclass(slots=True, frozen=True)
class IdentitySettings:
    provider: str = "hybrid"
    registry_path: str = "configs/person_registry.json"
    refresh_seconds: int = 60
    unknown_person_name: str = "Unknown"


@dataclass(slots=True, frozen=True)
class FaceRecognitionSettings:
    enabled: bool = True
    provider: str = "facenet_pytorch"
    device: str = "cpu"
    similarity_threshold: float = 0.62
    review_threshold: float = 0.52
    top_k: int = 3
    face_profile_dir: str = "artifacts/identity/faces"


@dataclass(slots=True, frozen=True)
class OcrSettings:
    enabled: bool = True
    provider: str = "none"
    min_confidence: float = 0.35
    badge_roi_y_start: float = 0.22
    badge_roi_y_end: float = 0.72
    badge_roi_x_margin: float = 0.18


@dataclass(slots=True, frozen=True)
class LlmFallbackSettings:
    enabled: bool = True
    use_openai: bool = True
    use_deepseek: bool = True
    openai_model: str = "gpt-5-mini"
    deepseek_model: str = "deepseek-chat"
    timeout_seconds: float = 20.0
    max_candidates: int = 5


@dataclass(slots=True, frozen=True)
class TrackingSettings:
    enabled: bool = True
    provider: str = "builtin"
    tracker_config: str = "bytetrack.yaml"
    persist: bool = True


@dataclass(slots=True, frozen=True)
class GovernanceSettings:
    enabled: bool = True
    min_bbox_area: int = 3600
    ignore_zones: dict[str, tuple[dict[str, int], ...]] = field(default_factory=dict)
    whitelist_camera_ids: tuple[str, ...] = field(default_factory=tuple)
    night_start_hour: int = 19
    night_end_hour: int = 6
    night_confidence_boost: float = 0.08
    review_confidence_margin: float = 0.08


@dataclass(slots=True, frozen=True)
class ClipSettings:
    enabled: bool = True
    pre_seconds: int = 5
    post_seconds: int = 5
    fps: float = 12.0
    codec: str = "mp4v"


@dataclass(slots=True, frozen=True)
class NotificationSettings:
    enabled: bool = True
    email_enabled: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    use_tls: bool = True
    default_recipients: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from_email)


@dataclass(slots=True, frozen=True)
class SecuritySettings:
    use_private_bucket: bool = True
    signed_url_seconds: int = 86400
    evidence_retention_days: int = 90
    audit_enabled: bool = True


@dataclass(slots=True, frozen=True)
class CameraSettings:
    camera_id: str
    camera_name: str
    source: str
    location: str
    department: str
    enabled: bool = True
    default_person_id: str = ""
    site_name: str = "Default Site"
    building_name: str = "Main Building"
    floor_name: str = "Floor 1"
    workshop_name: str = "Workshop A"
    zone_name: str = "Zone A"
    responsible_department: str = ""
    alert_emails: tuple[str, ...] = field(default_factory=tuple)


@dataclass(slots=True, frozen=True)
class SupabaseSettings:
    url: str = ""
    service_role_key: str = ""
    storage_bucket: str = "helmet-alerts"

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.service_role_key)


@dataclass(slots=True, frozen=True)
class AppSettings:
    repository_backend: str
    model: ModelSettings
    event_rules: EventRuleSettings
    persistence: PersistenceSettings
    monitoring: MonitoringSettings
    identity: IdentitySettings
    face_recognition: FaceRecognitionSettings
    ocr: OcrSettings
    llm_fallback: LlmFallbackSettings
    tracking: TrackingSettings
    governance: GovernanceSettings
    clip: ClipSettings
    notifications: NotificationSettings
    security: SecuritySettings
    supabase: SupabaseSettings
    cameras: tuple[CameraSettings, ...] = field(default_factory=tuple)
    config_path: Path = field(default=REPO_ROOT / "configs" / "runtime.json")

    def resolve_path(self, path_value: str) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        return (REPO_ROOT / path).resolve()


def _load_env_files() -> None:
    load_dotenv(REPO_ROOT / ".env", override=False)
    load_dotenv(REPO_ROOT / "configs" / ".env", override=False)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _tuple_from_labels(labels: list[str] | tuple[str, ...] | None, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not labels:
        return fallback
    return tuple(str(item).strip() for item in labels if str(item).strip())


def _tuple_from_strings(values: list[str] | tuple[str, ...] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        items = [item.strip() for item in values.split(",")]
    else:
        items = [str(item).strip() for item in values]
    return tuple(item for item in items if item)


def _normalize_env_text(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = str(value).strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _env_flag(*names: str) -> bool:
    for name in names:
        raw = os.getenv(name)
        if raw is None and name.lower() != name:
            raw = os.getenv(name.lower())
        if raw is None and name.upper() != name:
            raw = os.getenv(name.upper())
        if raw is None:
            continue
        return _normalize_env_text(raw).lower() in {"1", "true", "yes", "on"}
    return False


def _resolve_env_placeholder(value: str | None) -> str:
    cleaned = _normalize_env_text(value)
    if not cleaned.startswith("${") or not cleaned.endswith("}"):
        return cleaned
    inner = cleaned[2:-1].strip()
    if not inner:
        return ""
    env_name, separator, fallback = inner.partition(":")
    resolved = _normalize_env_text(os.getenv(env_name.strip(), ""))
    if resolved:
        return resolved
    if separator:
        return fallback.strip()
    return ""


def _normalize_supabase_url(value: str | None) -> str:
    cleaned = _normalize_env_text(value)
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return cleaned
    if "supabase.co" in lowered:
        return f"https://{cleaned}"
    if lowered.startswith(("localhost", "127.0.0.1")):
        return f"http://{cleaned}"
    return cleaned


def _parse_ignore_zones(raw_value: dict[str, Any] | None) -> dict[str, tuple[dict[str, int], ...]]:
    if not raw_value:
        return {}
    output: dict[str, tuple[dict[str, int], ...]] = {}
    for camera_id, zones in raw_value.items():
        zone_records: list[dict[str, int]] = []
        for zone in zones or []:
            zone_records.append(
                {
                    "x1": int(zone.get("x1", 0)),
                    "y1": int(zone.get("y1", 0)),
                    "x2": int(zone.get("x2", 0)),
                    "y2": int(zone.get("y2", 0)),
                }
            )
        output[str(camera_id)] = tuple(zone_records)
    return output


def _looks_like_local_camera(camera: dict[str, Any]) -> bool:
    source = _resolve_env_placeholder(str(camera.get("source", ""))).strip()
    if source.isdigit():
        return True
    camera_id = str(camera.get("camera_id", "")).strip().lower()
    camera_name = str(camera.get("camera_name", "")).strip().lower()
    local_markers = ("local", "laptop", "webcam", "desktop")
    return any(marker in camera_id or marker in camera_name for marker in local_markers)


def _apply_laptop_camera_override(cameras_raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _env_flag("camera_use_laptop_camera", "CAMERA_USE_LAPTOP_CAMERA"):
        return [dict(camera) for camera in cameras_raw]

    cameras = [dict(camera) for camera in cameras_raw]
    local_index = next((idx for idx, camera in enumerate(cameras) if _looks_like_local_camera(camera)), None)
    if local_index is None:
        if not cameras:
            return cameras
        cameras[0]["source"] = "0"
        cameras[0]["enabled"] = True
        for idx in range(1, len(cameras)):
            cameras[idx]["enabled"] = False
        return cameras

    for idx, camera in enumerate(cameras):
        camera["enabled"] = idx == local_index
    return cameras


def load_settings(config_path: str | Path | None = None) -> AppSettings:
    _load_env_files()
    env_config_path = os.getenv("HELMET_CONFIG_PATH", "configs/runtime.json")
    target = Path(config_path or env_config_path)
    if not target.is_absolute():
        target = (REPO_ROOT / target).resolve()
    if not target.exists():
        raise FileNotFoundError(f"Runtime config not found: {target}")

    raw = _load_json(target)

    model_raw = raw.get("model", {})
    event_raw = raw.get("event_rules", {})
    persistence_raw = raw.get("persistence", {})
    monitoring_raw = raw.get("monitoring", {})
    identity_raw = raw.get("identity", {})
    face_raw = raw.get("face_recognition", {})
    ocr_raw = raw.get("ocr", {})
    llm_raw = raw.get("llm_fallback", {})
    tracking_raw = raw.get("tracking", {})
    governance_raw = raw.get("governance", {})
    clip_raw = raw.get("clip", {})
    notification_raw = raw.get("notifications", {})
    security_raw = raw.get("security", {})
    cameras_raw = _apply_laptop_camera_override(raw.get("cameras", []))

    default_recipients = os.getenv("ALERT_EMAIL_RECIPIENTS", "")

    settings = AppSettings(
        repository_backend=os.getenv("HELMET_STORAGE_BACKEND", raw.get("repository_backend", "supabase")).strip().lower(),
        model=ModelSettings(
            path=str(model_raw.get("path", "artifacts/training_runs/helmet_project/cpu_test3/weights/best.pt")),
            confidence=float(model_raw.get("confidence", 0.45)),
            imgsz=int(model_raw.get("imgsz", 640)),
            device=str(model_raw.get("device", "cpu")),
            violation_labels=_tuple_from_labels(model_raw.get("violation_labels"), ("no_helmet", "person")),
            safe_labels=_tuple_from_labels(model_raw.get("safe_labels"), ("helmet", "hat")),
        ),
        event_rules=EventRuleSettings(
            alert_frames=int(event_raw.get("alert_frames", 6)),
            dedupe_seconds=int(event_raw.get("dedupe_seconds", 300)),
            match_distance_pixels=int(event_raw.get("match_distance_pixels", 120)),
            max_track_age_seconds=float(event_raw.get("max_track_age_seconds", 2.5)),
            min_confidence_for_alert=float(event_raw.get("min_confidence_for_alert", 0.5)),
        ),
        persistence=PersistenceSettings(
            snapshot_dir=str(persistence_raw.get("snapshot_dir", "artifacts/captures")),
            runtime_dir=str(persistence_raw.get("runtime_dir", "artifacts/runtime")),
            save_annotated_snapshot=bool(persistence_raw.get("save_annotated_snapshot", True)),
            upload_to_supabase_storage=bool(persistence_raw.get("upload_to_supabase_storage", True)),
            storage_prefix=str(persistence_raw.get("storage_prefix", "alerts")),
            keep_local_copy=bool(persistence_raw.get("keep_local_copy", True)),
        ),
        monitoring=MonitoringSettings(
            frame_stride=max(1, int(monitoring_raw.get("frame_stride", 3))),
            camera_retry_seconds=float(monitoring_raw.get("camera_retry_seconds", 5.0)),
            heartbeat_interval_seconds=float(monitoring_raw.get("heartbeat_interval_seconds", 10.0)),
            max_frames=int(monitoring_raw.get("max_frames", 0)),
        ),
        identity=IdentitySettings(
            provider=str(identity_raw.get("provider", "hybrid")).strip().lower() or "hybrid",
            registry_path=str(identity_raw.get("registry_path", "configs/person_registry.json")),
            refresh_seconds=max(5, int(identity_raw.get("refresh_seconds", 60))),
            unknown_person_name=str(identity_raw.get("unknown_person_name", "Unknown")),
        ),
        face_recognition=FaceRecognitionSettings(
            enabled=bool(face_raw.get("enabled", True)),
            provider=str(face_raw.get("provider", "facenet_pytorch")).strip().lower() or "facenet_pytorch",
            device=str(face_raw.get("device", "cpu")),
            similarity_threshold=float(face_raw.get("similarity_threshold", 0.62)),
            review_threshold=float(face_raw.get("review_threshold", 0.52)),
            top_k=max(1, int(face_raw.get("top_k", 3))),
            face_profile_dir=str(face_raw.get("face_profile_dir", "artifacts/identity/faces")),
        ),
        ocr=OcrSettings(
            enabled=bool(ocr_raw.get("enabled", True)),
            provider=str(ocr_raw.get("provider", "none")).strip().lower() or "none",
            min_confidence=float(ocr_raw.get("min_confidence", 0.35)),
            badge_roi_y_start=float(ocr_raw.get("badge_roi_y_start", 0.22)),
            badge_roi_y_end=float(ocr_raw.get("badge_roi_y_end", 0.72)),
            badge_roi_x_margin=float(ocr_raw.get("badge_roi_x_margin", 0.18)),
        ),
        llm_fallback=LlmFallbackSettings(
            enabled=bool(llm_raw.get("enabled", True)),
            use_openai=bool(llm_raw.get("use_openai", True)),
            use_deepseek=bool(llm_raw.get("use_deepseek", True)),
            openai_model=str(llm_raw.get("openai_model", "gpt-5-mini")),
            deepseek_model=str(llm_raw.get("deepseek_model", "deepseek-chat")),
            timeout_seconds=float(llm_raw.get("timeout_seconds", 20.0)),
            max_candidates=max(1, int(llm_raw.get("max_candidates", 5))),
        ),
        tracking=TrackingSettings(
            enabled=bool(tracking_raw.get("enabled", True)),
            provider=str(tracking_raw.get("provider", "builtin")).strip().lower() or "builtin",
            tracker_config=str(tracking_raw.get("tracker_config", "bytetrack.yaml")),
            persist=bool(tracking_raw.get("persist", True)),
        ),
        governance=GovernanceSettings(
            enabled=bool(governance_raw.get("enabled", True)),
            min_bbox_area=max(0, int(governance_raw.get("min_bbox_area", 3600))),
            ignore_zones=_parse_ignore_zones(governance_raw.get("ignore_zones")),
            whitelist_camera_ids=_tuple_from_strings(governance_raw.get("whitelist_camera_ids")),
            night_start_hour=int(governance_raw.get("night_start_hour", 19)),
            night_end_hour=int(governance_raw.get("night_end_hour", 6)),
            night_confidence_boost=float(governance_raw.get("night_confidence_boost", 0.08)),
            review_confidence_margin=float(governance_raw.get("review_confidence_margin", 0.08)),
        ),
        clip=ClipSettings(
            enabled=bool(clip_raw.get("enabled", True)),
            pre_seconds=max(1, int(clip_raw.get("pre_seconds", 5))),
            post_seconds=max(1, int(clip_raw.get("post_seconds", 5))),
            fps=max(1.0, float(clip_raw.get("fps", 12.0))),
            codec=str(clip_raw.get("codec", "mp4v")),
        ),
        notifications=NotificationSettings(
            enabled=bool(notification_raw.get("enabled", True)),
            email_enabled=bool(notification_raw.get("email_enabled", True)),
            smtp_host=_normalize_env_text(os.getenv("SMTP_HOST", str(notification_raw.get("smtp_host", "")))),
            smtp_port=int(os.getenv("SMTP_PORT", notification_raw.get("smtp_port", 587))),
            smtp_username=_normalize_env_text(os.getenv("SMTP_USERNAME", str(notification_raw.get("smtp_username", "")))),
            smtp_password=_normalize_env_text(os.getenv("SMTP_PASSWORD", str(notification_raw.get("smtp_password", "")))),
            smtp_from_email=_normalize_env_text(os.getenv("SMTP_FROM_EMAIL", str(notification_raw.get("smtp_from_email", "")))),
            use_tls=str(os.getenv("SMTP_USE_TLS", notification_raw.get("use_tls", True))).strip().lower()
            not in {"false", "0", "no"},
            default_recipients=_tuple_from_strings(
                default_recipients or notification_raw.get("default_recipients", ())
            ),
        ),
        security=SecuritySettings(
            use_private_bucket=bool(security_raw.get("use_private_bucket", False)),
            signed_url_seconds=max(60, int(security_raw.get("signed_url_seconds", 86400))),
            evidence_retention_days=max(1, int(security_raw.get("evidence_retention_days", 90))),
            audit_enabled=bool(security_raw.get("audit_enabled", True)),
        ),
        supabase=SupabaseSettings(
            url=_normalize_supabase_url(os.getenv("SUPABASE_URL", "")),
            service_role_key=_normalize_env_text(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")),
            storage_bucket=_normalize_env_text(os.getenv("SUPABASE_STORAGE_BUCKET", "helmet-alerts")) or "helmet-alerts",
        ),
        cameras=tuple(
            CameraSettings(
                camera_id=str(camera["camera_id"]),
                camera_name=str(camera.get("camera_name", camera["camera_id"])),
                source=_resolve_env_placeholder(str(camera.get("source", "0"))),
                location=str(camera.get("location", "Unknown")),
                department=str(camera.get("department", "Unknown")),
                enabled=bool(camera.get("enabled", True)),
                default_person_id=str(camera.get("default_person_id", "")).strip(),
                site_name=str(camera.get("site_name", "Default Site")),
                building_name=str(camera.get("building_name", "Main Building")),
                floor_name=str(camera.get("floor_name", "Floor 1")),
                workshop_name=str(camera.get("workshop_name", "Workshop A")),
                zone_name=str(camera.get("zone_name", "Zone A")),
                responsible_department=str(camera.get("responsible_department", camera.get("department", "Unknown"))),
                alert_emails=_tuple_from_strings(camera.get("alert_emails")),
            )
            for camera in cameras_raw
        ),
        config_path=target,
    )
    return settings
