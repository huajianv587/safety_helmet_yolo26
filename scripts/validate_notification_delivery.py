from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import replace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import CameraSettings, load_settings
from helmet_monitoring.core.schemas import AlertRecord, utc_now
from helmet_monitoring.services.notifier import NotificationService
from helmet_monitoring.services.runtime_profiles import local_smoke_settings
from helmet_monitoring.storage.repository import LocalAlertRepository, build_repository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate SMTP or dry-run notification delivery independently from the full smoke test.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--strict-runtime", action="store_true", help="Require the configured repository backend instead of falling back to local.")
    parser.add_argument("--mode", default="auto", choices=["auto", "smtp", "dry_run"], help="Delivery validation mode.")
    parser.add_argument("--recipient", action="append", default=[], help="Repeatable recipient override.")
    parser.add_argument("--camera-id", default=None, help="Optional camera_id override.")
    parser.add_argument("--require-success", action="store_true", help="Fail unless at least one SMTP notification is sent successfully.")
    parser.add_argument(
        "--local-runtime-dir",
        default=None,
        help="Optional local runtime dir override. Forces a local-only repository while keeping SMTP settings intact.",
    )
    return parser.parse_args()


def _select_camera(settings, camera_id: str | None) -> CameraSettings:
    if camera_id:
        for camera in settings.cameras:
            if camera.camera_id == camera_id:
                return camera
    for camera in settings.cameras:
        if camera.enabled:
            return camera
    return CameraSettings(
        camera_id="notify-cam",
        camera_name="Notification Validation Camera",
        source="0",
        location="Delivery Validation",
        department="Ops",
        enabled=True,
        site_name="Validation Site",
        building_name="HQ",
        floor_name="Floor 1",
        workshop_name="Control Room",
        zone_name="Desk 1",
        responsible_department="Ops",
    )


def _dedupe_recipients(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in values:
        recipient = str(raw).strip()
        if not recipient:
            continue
        key = recipient.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(recipient)
    return tuple(ordered)


def _resolve_mode(settings, args: argparse.Namespace) -> str:
    if args.mode != "auto":
        return args.mode
    return "smtp" if settings.notifications.is_email_configured else "dry_run"


def _resolve_recipients(settings, camera: CameraSettings, args: argparse.Namespace) -> tuple[str, ...]:
    values: list[str] = []
    values.extend(args.recipient or [])
    values.extend(camera.alert_emails)
    values.extend(settings.notifications.default_recipients)
    if settings.notifications.is_email_configured:
        fallback = settings.notifications.smtp_from_email or settings.notifications.smtp_username
        if fallback:
            values.append(fallback)
    if not values:
        values.append("delivery-check@example.local")
    return _dedupe_recipients(values)


def _build_validation_alert(camera: CameraSettings) -> AlertRecord:
    observed_at = utc_now()
    alert_id = uuid.uuid4().hex
    return AlertRecord(
        alert_id=alert_id,
        event_key=f"{camera.camera_id}:notification-check",
        event_no=f"NTF-{observed_at.strftime('%Y%m%d-%H%M%S')}-{alert_id[:6].upper()}",
        camera_id=camera.camera_id,
        camera_name=camera.camera_name,
        location=camera.location,
        department=camera.department,
        violation_type="notification_validation",
        risk_level="medium",
        confidence=1.0,
        snapshot_path="artifacts/runtime/ops/notification_validation.jpg",
        snapshot_url=None,
        status="pending",
        bbox=None,
        model_name="notification_validation",
        person_id=None,
        person_name="System Validation",
        employee_id=None,
        team=None,
        role="ops_validation",
        phone=None,
        identity_status="not_applicable",
        identity_source="system",
        clip_path=None,
        clip_url=None,
        alert_source="validate_notification_delivery",
        site_name=camera.site_name,
        building_name=camera.building_name,
        floor_name=camera.floor_name,
        workshop_name=camera.workshop_name,
        zone_name=camera.zone_name,
        responsible_department=camera.responsible_department or camera.department,
        created_at=observed_at,
    )


def run_validation(settings, args: argparse.Namespace) -> dict[str, str | int]:
    if args.local_runtime_dir:
        local_settings = local_smoke_settings(settings)
        local_runtime_dir = Path(args.local_runtime_dir).resolve()
        local_snapshot_dir = local_runtime_dir.parent / "captures"
        local_runtime_dir.mkdir(parents=True, exist_ok=True)
        local_snapshot_dir.mkdir(parents=True, exist_ok=True)
        settings = replace(
            local_settings,
            persistence=replace(
                local_settings.persistence,
                runtime_dir=str(local_runtime_dir),
                snapshot_dir=str(local_snapshot_dir),
            ),
        )
    camera = _select_camera(settings, args.camera_id)
    mode = _resolve_mode(settings, args)
    repository = LocalAlertRepository(settings.resolve_path(settings.persistence.runtime_dir))
    if args.strict_runtime:
        repository = build_repository(settings, require_requested_backend=True)
    elif mode != "dry_run":
        repository = build_repository(settings)
    notifier = NotificationService(settings, repository)
    recipients = _resolve_recipients(settings, camera, args)
    alert = _build_validation_alert(camera)
    repository.insert_alert(alert.to_record())

    if mode == "smtp":
        notifier.send_alert_email(alert, recipients)
    else:
        notifier.simulate_alert_email(alert, recipients, reason="validate_notification_delivery")

    logs = repository.list_notification_logs(alert_id=alert.alert_id, limit=20)
    if not logs:
        raise RuntimeError("Notification validation did not create any notification log records.")
    statuses = ",".join(str(item.get("status") or "--") for item in logs)
    if args.require_success and mode == "smtp":
        sent = sum(1 for item in logs if str(item.get("status") or "").strip().lower() == "sent")
        if sent <= 0:
            raise RuntimeError("Notification validation did not send any successful SMTP messages.")

    return {
        "backend": repository.backend_name,
        "event_no": alert.event_no,
        "notification_mode": mode,
        "notification_recipients": ",".join(recipients),
        "notification_statuses": statuses,
        "notifications": len(logs),
    }


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    result = run_validation(settings, args)
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
