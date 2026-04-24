from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from helmet_monitoring.core.config import REPO_ROOT, AppSettings
from helmet_monitoring.core.schemas import utc_now
from helmet_monitoring.services.dashboard_api import load_raw_config, merge_live_cameras, save_raw_config
from helmet_monitoring.services.model_governance import (
    build_feedback_dataset,
    ensure_feedback_workspace,
    export_feedback_cases,
    feedback_paths,
)
from helmet_monitoring.services.operations import (
    _record_audit,
    collect_operations_status,
    create_backup,
    create_release_snapshot,
    ensure_operations_state,
    operations_paths,
    restore_backup,
    rollback_release,
    activate_release,
)
from helmet_monitoring.services.person_directory import PersonDirectory
from helmet_monitoring.services.readiness import collect_readiness_report
from helmet_monitoring.services.video_sources import is_local_device_source
from helmet_monitoring.storage.repository import AlertRepository, parse_timestamp
from helmet_monitoring.tasks.task_queue import get_queue_stats

try:
    from supabase import create_client
except ImportError:  # pragma: no cover
    create_client = None

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.bootstrap_identity_defaults import _count_face_samples
from scripts.identity_delivery_audit import build_report as build_identity_audit_report
from scripts.sync_person_registry import _sync_people
from scripts.validate_notification_delivery import run_validation as run_notification_validation
from scripts.validate_storage_delivery import run_validation as run_storage_validation


OPS_CONFIRM_TEXT = "HELMET OPS"
OPS_READ_ROLES = ("admin", "safety_manager")
OPS_WRITE_ROLES = ("admin",)
SERVICE_LAUNCHERS = {
    "dashboard": REPO_ROOT / "start_dashboard_service.cmd",
    "monitor": REPO_ROOT / "start_monitor_service.cmd",
}
SERVICE_QUERY_HINTS = {
    "dashboard": "service_supervisor.py dashboard",
    "monitor": "service_supervisor.py monitor",
}
POWERSHELL_EXECUTABLE = shutil.which("powershell") or shutil.which("pwsh")
REQUIRED_CAPABILITY_SOURCES = (
    "app.py",
    "src/helmet_monitoring/services/auth.py",
    "src/helmet_monitoring/services/dashboard_api.py",
    "src/helmet_monitoring/services/monitor.py",
    "src/helmet_monitoring/services/detector.py",
    "src/helmet_monitoring/services/event_engine.py",
    "src/helmet_monitoring/services/governance.py",
    "src/helmet_monitoring/services/identity_resolver.py",
    "src/helmet_monitoring/services/badge_ocr.py",
    "src/helmet_monitoring/services/face_recognition.py",
    "src/helmet_monitoring/services/llm_fallback.py",
    "src/helmet_monitoring/services/person_directory.py",
    "src/helmet_monitoring/services/workflow.py",
    "src/helmet_monitoring/services/notifier.py",
    "src/helmet_monitoring/services/readiness.py",
    "src/helmet_monitoring/services/operations.py",
    "src/helmet_monitoring/services/model_governance.py",
    "src/helmet_monitoring/services/service_supervisor.py",
    "src/helmet_monitoring/services/video_sources.py",
    "src/helmet_monitoring/services/runtime_profiles.py",
    "src/helmet_monitoring/services/clip_recorder.py",
    "src/helmet_monitoring/storage/repository.py",
    "src/helmet_monitoring/storage/evidence_store.py",
    "src/helmet_monitoring/storage/snapshot_store.py",
    "src/helmet_monitoring/ui/live_preview_stream.py",
    "scripts/doctor.py",
    "scripts/ops_status.py",
    "scripts/backup_system.py",
    "scripts/restore_system.py",
    "scripts/release_manager.py",
    "scripts/model_feedback_loop.py",
    "scripts/sync_person_registry.py",
    "scripts/identity_delivery_audit.py",
    "scripts/validate_storage_delivery.py",
    "scripts/validate_notification_delivery.py",
)


CAPABILITY_MATRIX: tuple[dict[str, Any], ...] = (
    {
        "capability_id": "legacy_streamlit_console",
        "source_module": "app.py",
        "category": "legacy",
        "title": "Legacy Streamlit console",
        "summary": "Fallback console for the original operations workflow.",
        "mode": "internal_only",
        "internal_only_reason": "Kept as a rollback surface while the SPA is the primary frontend.",
    },
    {
        "capability_id": "trusted_console_auth",
        "source_module": "src/helmet_monitoring/services/auth.py",
        "category": "auth",
        "title": "Trusted console auth and lockout policy",
        "summary": "Login, register, password change, role routing, and lockout handling.",
        "mode": "ui_surface",
        "surface_route": "/login",
    },
    {
        "capability_id": "dashboard_aggregations",
        "source_module": "src/helmet_monitoring/services/dashboard_api.py",
        "category": "platform",
        "title": "Dashboard and report aggregations",
        "summary": "Overview metrics, trends, rankings, and safe runtime config helpers.",
        "mode": "ui_surface",
        "surface_route": "/dashboard",
    },
    {
        "capability_id": "monitor_detection_pipeline",
        "source_module": "src/helmet_monitoring/services/monitor.py",
        "category": "monitoring",
        "title": "Continuous helmet monitoring pipeline",
        "summary": "Frame ingest, detection, governance, evidence capture, alert creation, and notifications.",
        "mode": "ui_surface",
        "surface_route": "/dashboard",
    },
    {
        "capability_id": "yolo_detection_engine",
        "source_module": "src/helmet_monitoring/services/detector.py",
        "category": "vision",
        "title": "YOLO detection engine",
        "summary": "Core detection engine backing monitor and browser preview inference.",
        "mode": "internal_only",
        "internal_only_reason": "Low-level model execution surfaced indirectly through review, cameras, and monitor views.",
    },
    {
        "capability_id": "violation_event_engine",
        "source_module": "src/helmet_monitoring/services/event_engine.py",
        "category": "vision",
        "title": "Violation event grouping",
        "summary": "Groups repeated frame detections into event-level alerts.",
        "mode": "internal_only",
        "internal_only_reason": "Pipeline logic is visible through created alerts, not as a separate operator action.",
    },
    {
        "capability_id": "false_positive_governance",
        "source_module": "src/helmet_monitoring/services/governance.py",
        "category": "governance",
        "title": "Governance filters and hard-case sinking",
        "summary": "Filters borderline detections and routes feedback-worthy cases.",
        "mode": "ui_surface",
        "surface_route": "/review",
    },
    {
        "capability_id": "identity_resolution_cascade",
        "source_module": "src/helmet_monitoring/services/identity_resolver.py",
        "category": "identity",
        "title": "Identity resolution cascade",
        "summary": "Badge OCR, face matching, LLM fallback, and camera defaults.",
        "mode": "ui_surface",
        "surface_route": "/review",
    },
    {
        "capability_id": "badge_ocr_hints",
        "source_module": "src/helmet_monitoring/services/badge_ocr.py",
        "category": "identity",
        "title": "Badge OCR and employee hints",
        "summary": "Reads badge regions to strengthen operator identity suggestions.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=identity",
    },
    {
        "capability_id": "face_profile_matching",
        "source_module": "src/helmet_monitoring/services/face_recognition.py",
        "category": "identity",
        "title": "Face profile matching",
        "summary": "Uses registered face embeddings when local identity extras are available.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=identity",
    },
    {
        "capability_id": "llm_identity_fallback",
        "source_module": "src/helmet_monitoring/services/llm_fallback.py",
        "category": "identity",
        "title": "LLM ambiguity fallback",
        "summary": "Resolves ambiguous badge candidates when configured.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=identity",
    },
    {
        "capability_id": "person_registry_directory",
        "source_module": "src/helmet_monitoring/services/person_directory.py",
        "category": "identity",
        "title": "Person registry and camera defaults",
        "summary": "Search, registry merge, and default person suggestions for cameras.",
        "mode": "ui_surface",
        "surface_route": "/config",
    },
    {
        "capability_id": "review_workflow",
        "source_module": "src/helmet_monitoring/services/workflow.py",
        "category": "workflow",
        "title": "Closed-loop workflow actions",
        "summary": "Assignment, remediation, false-positive closure, and hard-case feedback.",
        "mode": "ui_surface",
        "surface_route": "/review",
    },
    {
        "capability_id": "notification_delivery",
        "source_module": "src/helmet_monitoring/services/notifier.py",
        "category": "delivery",
        "title": "Outbound notification delivery",
        "summary": "SMTP or dry-run delivery logging for helmet events.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=notifications",
    },
    {
        "capability_id": "deployment_readiness_doctor",
        "source_module": "src/helmet_monitoring/services/readiness.py",
        "category": "operations",
        "title": "Deployment readiness doctor",
        "summary": "Checks dependencies, identity coverage, workspace health, and next actions.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=readiness",
    },
    {
        "capability_id": "ops_heartbeats_backups_releases",
        "source_module": "src/helmet_monitoring/services/operations.py",
        "category": "operations",
        "title": "Ops heartbeats, backups, and release registry",
        "summary": "Tracks service health, backups, releases, and audit events.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=backup-release",
    },
    {
        "capability_id": "model_feedback_exports_and_promotions",
        "source_module": "src/helmet_monitoring/services/model_governance.py",
        "category": "operations",
        "title": "Model feedback export and promotion",
        "summary": "Exports feedback cases, builds datasets, registers models, and promotes candidates.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=model-feedback",
    },
    {
        "capability_id": "managed_service_supervision",
        "source_module": "src/helmet_monitoring/services/service_supervisor.py",
        "category": "operations",
        "title": "Managed service supervision",
        "summary": "Health-based supervision specs for dashboard and monitor workers.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=services",
    },
    {
        "capability_id": "safe_camera_source_controls",
        "source_module": "src/helmet_monitoring/services/video_sources.py",
        "category": "cameras",
        "title": "Safe camera source handling",
        "summary": "Validates local devices, remote streams, and runtime camera posture.",
        "mode": "ui_surface",
        "surface_route": "/config",
    },
    {
        "capability_id": "runtime_profiles_for_smoke_flows",
        "source_module": "src/helmet_monitoring/services/runtime_profiles.py",
        "category": "operations",
        "title": "Runtime smoke profiles",
        "summary": "Utility runtime variations for validation and smoke flows.",
        "mode": "internal_only",
        "internal_only_reason": "Used by validation scripts and smoke runs, not as a direct operator control.",
    },
    {
        "capability_id": "clip_capture_pipeline",
        "source_module": "src/helmet_monitoring/services/clip_recorder.py",
        "category": "evidence",
        "title": "Clip capture pipeline",
        "summary": "Captures violation clips around detected events.",
        "mode": "ui_surface",
        "surface_route": "/review",
    },
    {
        "capability_id": "alert_repository_and_audit",
        "source_module": "src/helmet_monitoring/storage/repository.py",
        "category": "storage",
        "title": "Alert repository, logs, and audit trail",
        "summary": "Stores alerts, camera heartbeats, notifications, hard cases, and audits.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=coverage",
    },
    {
        "capability_id": "evidence_storage_delivery",
        "source_module": "src/helmet_monitoring/storage/evidence_store.py",
        "category": "storage",
        "title": "Evidence storage and delivery",
        "summary": "Writes snapshots and clips locally and optionally to Supabase storage.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=evidence-delivery",
    },
    {
        "capability_id": "snapshot_local_layout",
        "source_module": "src/helmet_monitoring/storage/snapshot_store.py",
        "category": "storage",
        "title": "Snapshot path layout",
        "summary": "Local snapshot path generation and storage layout rules.",
        "mode": "internal_only",
        "internal_only_reason": "Storage layout is consumed through evidence delivery and media views, not managed directly in the UI.",
    },
    {
        "capability_id": "browser_preview_and_mjpeg",
        "source_module": "src/helmet_monitoring/ui/live_preview_stream.py",
        "category": "cameras",
        "title": "Browser preview, MJPEG, and browser inference",
        "summary": "Streams local browser previews and monitor frames with live inference.",
        "mode": "ui_surface",
        "surface_route": "/cameras",
    },
    {
        "capability_id": "doctor_cli_bridge",
        "source_module": "scripts/doctor.py",
        "category": "operations",
        "title": "Doctor CLI bridge",
        "summary": "CLI entrypoint for readiness checks and strict deployment gating.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=readiness",
    },
    {
        "capability_id": "ops_status_cli_bridge",
        "source_module": "scripts/ops_status.py",
        "category": "operations",
        "title": "Ops status CLI bridge",
        "summary": "CLI summary for service state, backups, releases, and active model.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=services",
    },
    {
        "capability_id": "backup_cli_bridge",
        "source_module": "scripts/backup_system.py",
        "category": "operations",
        "title": "Backup creation CLI bridge",
        "summary": "CLI wrapper for backup creation.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=backup-release",
    },
    {
        "capability_id": "restore_cli_bridge",
        "source_module": "scripts/restore_system.py",
        "category": "operations",
        "title": "Backup restore CLI bridge",
        "summary": "CLI wrapper for archive restore.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=backup-release",
    },
    {
        "capability_id": "release_manager_cli_bridge",
        "source_module": "scripts/release_manager.py",
        "category": "operations",
        "title": "Release manager CLI bridge",
        "summary": "CLI wrapper for snapshots, activation, and rollback.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=backup-release",
    },
    {
        "capability_id": "model_feedback_cli_bridge",
        "source_module": "scripts/model_feedback_loop.py",
        "category": "operations",
        "title": "Model feedback CLI bridge",
        "summary": "CLI wrapper for feedback export, dataset build, and promotion workflows.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=model-feedback",
    },
    {
        "capability_id": "registry_sync_cli_bridge",
        "source_module": "scripts/sync_person_registry.py",
        "category": "identity",
        "title": "Registry sync CLI bridge",
        "summary": "Syncs the person registry into the configured data backend.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=identity",
    },
    {
        "capability_id": "identity_delivery_audit_cli_bridge",
        "source_module": "scripts/identity_delivery_audit.py",
        "category": "identity",
        "title": "Identity delivery audit CLI bridge",
        "summary": "Audits aliases, badge keywords, camera bindings, and face sample coverage.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=identity",
    },
    {
        "capability_id": "storage_validation_cli_bridge",
        "source_module": "scripts/validate_storage_delivery.py",
        "category": "delivery",
        "title": "Storage validation bridge",
        "summary": "Validates object upload, access URL, and cleanup behavior.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=evidence-delivery",
    },
    {
        "capability_id": "notification_validation_cli_bridge",
        "source_module": "scripts/validate_notification_delivery.py",
        "category": "delivery",
        "title": "Notification validation bridge",
        "summary": "Validates SMTP or dry-run delivery independently from the full monitor flow.",
        "mode": "ui_surface",
        "surface_route": "/operations?section=notifications",
    },
)


def _path_state(path: Path) -> dict[str, Any]:
    target = path.resolve()
    return {
        "label": target.name or str(target),
        "exists": target.exists(),
        "is_dir": target.is_dir(),
        "is_file": target.is_file(),
        "writable": os.access(target if target.exists() else target.parent, os.W_OK),
    }


def _repo_rel_label(path_value: str | Path | None) -> str | None:
    if not path_value:
        return None
    target = Path(path_value)
    if not target.is_absolute():
        target = (REPO_ROOT / target).resolve()
    else:
        target = target.resolve()
    try:
        return str(target.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return target.name


def _replace_path_tokens(text: str | None) -> str:
    value = str(text or "")
    if not value:
        return ""
    replacements = {
        str(REPO_ROOT.resolve()): "<repo>",
    }
    for raw, token in replacements.items():
        if raw:
            value = value.replace(raw, token).replace(raw.replace("\\", "/"), token)
    return value


def _service_summary(summary: dict[str, Any]) -> dict[str, Any]:
    payload = dict(summary or {})
    payload.pop("path", None)
    nested = dict(payload.pop("payload", {}) or {})
    safe_nested = {}
    for key in ("service", "status", "detail", "processed_frames", "last_alert_event_no", "updated_at", "latency_ms", "url"):
        if key in nested:
            safe_nested[key] = _replace_path_tokens(str(nested[key])) if isinstance(nested[key], str) else nested[key]
    if "camera_statuses" in nested and isinstance(nested["camera_statuses"], list):
        safe_nested["camera_statuses"] = nested["camera_statuses"][:8]
    payload["detail"] = _replace_path_tokens(str(payload.get("detail") or ""))
    if safe_nested:
        payload["payload"] = safe_nested
    return payload


def build_readiness_payload(settings: AppSettings) -> dict[str, Any]:
    report = collect_readiness_report(settings)
    checks = [
        {
            "check_id": str(item.get("check_id") or ""),
            "status": str(item.get("status") or ""),
            "detail": _replace_path_tokens(str(item.get("detail") or "")),
        }
        for item in report.get("checks", [])
        if isinstance(item, dict)
    ]
    dependencies = report.get("dependencies", {})
    workspace = report.get("workspace", {})
    identity = report.get("identity", {})
    cameras = report.get("cameras", {})
    services = report.get("services", {})
    return {
        "generated_at": utc_now().isoformat(),
        "python": {
            "version": str(report.get("python", {}).get("version") or ""),
        },
        "config": {
            "repository_backend": str(report.get("config", {}).get("repository_backend") or settings.repository_backend),
            "runtime_config": _repo_rel_label(report.get("config", {}).get("path")),
        },
        "model": {
            "configured": bool(report.get("model", {}).get("exists")),
            "label": _repo_rel_label(report.get("model", {}).get("path")),
        },
        "cameras": {
            "configured": int(cameras.get("configured") or 0),
            "enabled": int(cameras.get("enabled") or 0),
        },
        "identity": {
            "provider": settings.identity.provider,
            "registry_exists": bool(identity.get("registry_exists")),
            "registry_people": int(identity.get("registry_people") or 0),
            "people_with_aliases": int(identity.get("people_with_aliases") or 0),
            "people_with_badge_keywords": int(identity.get("people_with_badge_keywords") or 0),
            "people_with_camera_bindings": int(identity.get("people_with_camera_bindings") or 0),
            "people_with_face_samples": int(identity.get("people_with_face_samples") or 0),
            "registry_label": _repo_rel_label(identity.get("registry_path")),
            "face_profile_label": _repo_rel_label(identity.get("face_profile_dir")),
        },
        "dataset": {
            "exists": bool(report.get("dataset", {}).get("exists")),
            "train_images": int(report.get("dataset", {}).get("train_images") or 0),
            "val_images": int(report.get("dataset", {}).get("val_images") or 0),
            "label": _repo_rel_label(report.get("dataset", {}).get("root")),
        },
        "workspace": {
            "required_paths": [
                _repo_rel_label(item) or str(item)
                for item in report.get("workspace", {}).get("required_paths", [])
            ],
            "missing_paths": [
                _repo_rel_label(item) or str(item)
                for item in workspace.get("missing_paths", [])
            ],
        },
        "services": services,
        "dependencies": dependencies,
        "checks": checks,
        "next_actions": [str(item) for item in report.get("next_actions", [])],
    }


def validate_capability_matrix() -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    covered_sources = {str(item.get("source_module") or "") for item in CAPABILITY_MATRIX}
    for entry in CAPABILITY_MATRIX:
        capability_id = str(entry.get("capability_id") or "").strip()
        if not capability_id:
            errors.append("Missing capability_id in capability matrix entry.")
            continue
        if capability_id in seen_ids:
            errors.append(f"Duplicate capability_id: {capability_id}")
        seen_ids.add(capability_id)
        mode = str(entry.get("mode") or "").strip()
        if mode not in {"ui_surface", "internal_only"}:
            errors.append(f"{capability_id}: unsupported mode {mode!r}")
        if mode == "ui_surface" and not str(entry.get("surface_route") or "").strip():
            errors.append(f"{capability_id}: ui_surface entries require surface_route")
        if mode == "internal_only" and not str(entry.get("internal_only_reason") or "").strip():
            errors.append(f"{capability_id}: internal_only entries require internal_only_reason")
        source = str(entry.get("source_module") or "").strip()
        if source and not (REPO_ROOT / source).exists():
            errors.append(f"{capability_id}: source file not found -> {source}")
    for source in REQUIRED_CAPABILITY_SOURCES:
        if source not in covered_sources:
            errors.append(f"Missing capability coverage for source module: {source}")
    return errors


def build_capability_matrix_payload() -> dict[str, Any]:
    errors = validate_capability_matrix()
    counts = {"ui_surface": 0, "internal_only": 0}
    rows: list[dict[str, Any]] = []
    for entry in CAPABILITY_MATRIX:
        row = dict(entry)
        mode = str(row.get("mode") or "internal_only")
        counts[mode] = counts.get(mode, 0) + 1
        rows.append(row)
    rows.sort(key=lambda item: (str(item.get("category") or ""), str(item.get("capability_id") or "")))
    return {
        "generated_at": utc_now().isoformat(),
        "items": rows,
        "summary": {
            "total": len(rows),
            "ui_surface": counts.get("ui_surface", 0),
            "internal_only": counts.get("internal_only", 0),
            "covered_sources": len({item["source_module"] for item in rows}),
            "required_sources": len(REQUIRED_CAPABILITY_SOURCES),
        },
        "coverage_errors": errors,
    }


def _service_control_supported(service_name: str) -> tuple[bool, str, Path | None]:
    launcher = SERVICE_LAUNCHERS.get(service_name)
    if launcher is None:
        return False, "Unsupported managed service.", None
    if not sys.platform.startswith("win"):
        return False, "Service control is available only on Windows hosts.", launcher
    if not POWERSHELL_EXECUTABLE:
        return False, "PowerShell is not available on this host.", launcher
    if not launcher.exists():
        return False, f"Missing launcher script: {launcher.name}", launcher
    return True, "ready", launcher


def _powershell_json(script: str) -> list[dict[str, Any]]:
    if not POWERSHELL_EXECUTABLE:
        return []
    try:
        completed = subprocess.run(
            [POWERSHELL_EXECUTABLE, "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return []
    if completed.returncode != 0:
        return []
    text = (completed.stdout or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        return [payload]
    return [item for item in payload if isinstance(item, dict)]


def service_processes(service_name: str) -> list[dict[str, Any]]:
    supported, _, _ = _service_control_supported(service_name)
    if not supported:
        return []
    hint = SERVICE_QUERY_HINTS.get(service_name, "")
    script = (
        "Get-CimInstance Win32_Process "
        "| Where-Object { $_.CommandLine -and $_.CommandLine -like '*"
        + hint.replace("'", "''")
        + "*' } "
        "| Select-Object ProcessId, Name, CommandLine "
        "| ConvertTo-Json -Compress"
    )
    rows = _powershell_json(script)
    return [
        {
            "pid": int(item.get("ProcessId") or 0),
            "name": str(item.get("Name") or ""),
            "command_line": str(item.get("CommandLine") or ""),
        }
        for item in rows
        if int(item.get("ProcessId") or 0) > 0
    ]


def _spawn_service_launcher(launcher: Path) -> None:
    subprocess.Popen(
        ["cmd", "/c", "start", "", str(launcher)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def _kill_service_processes(service_name: str) -> int:
    killed = 0
    for item in service_processes(service_name):
        pid = int(item.get("pid") or 0)
        if pid <= 0:
            continue
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=20,
            check=False,
        )
        killed += 1
    return killed


def build_services_payload(settings: AppSettings, repository: AlertRepository) -> dict[str, Any]:
    status = collect_operations_status(settings)
    ops_paths = operations_paths(settings)
    _, cameras = merge_live_cameras(settings, repository.list_cameras())  # type: ignore[name-defined]
    local_camera_ids = [
        camera.camera_id
        for camera in settings.cameras
        if camera.enabled and is_local_device_source(str(camera.source).strip())
    ]
    live_frames = 0
    live_frames_dir = ops_paths["live_frames_dir"]
    if live_frames_dir.exists():
        live_frames = len(list(live_frames_dir.glob("*.jpg")))
    preview_available = bool(local_camera_ids or live_frames)
    runtime_modes = [
        {
            "mode_id": "browser_local_preview",
            "label": "Browser local preview",
            "description": "Reads the local browser camera and can draw live helmet overlays.",
            "available": bool(local_camera_ids),
            "active": bool(local_camera_ids),
            "entry": "/cameras",
            "launcher": "browser preview is opened from the SPA",
        },
        {
            "mode_id": "desktop_realtime_viewer",
            "label": "Desktop realtime viewer",
            "description": "Standalone local desktop viewer for quick host-side preview.",
            "available": (REPO_ROOT / "start_realtime_webcam.cmd").exists(),
            "active": False,
            "entry": "start_realtime_webcam.cmd",
            "launcher": "start_realtime_webcam.cmd",
        },
        {
            "mode_id": "managed_services",
            "label": "Managed dashboard + monitor",
            "description": "Supervisor-managed dashboard and monitor workers for regular host operations.",
            "available": all(path.exists() for path in SERVICE_LAUNCHERS.values()),
            "active": any(item["status"] == "ready" for item in status["services"].values()),
            "entry": "/operations?section=services",
            "launcher": "start_host_services.cmd",
        },
    ]
    for name in ("dashboard", "monitor"):
        supported, detail, launcher = _service_control_supported(name)
        status["services"][name] = _service_summary(status["services"].get(name, {}))
        status["services"][name]["control"] = {
            "supported": supported,
            "detail": detail,
            "launcher": launcher.name if launcher else None,
            "processes": service_processes(name) if supported else [],
        }
    status["services"]["api"] = {
        "service": "api",
        "status": "ready",
        "detail": "FastAPI server is serving the SPA API.",
        "updated_at": utc_now().isoformat(),
        "age_seconds": 0.0,
    }
    status["services"]["camera_preview"] = {
        "service": "camera_preview",
        "status": "ready" if preview_available else "warn",
        "detail": (
            f"Local preview cameras={len(local_camera_ids)} live_frames={live_frames}."
            if preview_available
            else "No live frames or local preview cameras are currently available."
        ),
        "updated_at": utc_now().isoformat(),
        "age_seconds": 0.0,
    }
    return {
        "generated_at": utc_now().isoformat(),
        "services": status["services"],
        "backups": status["backups"],
        "releases": status["releases"],
        "models": status["models"],
        "runtime_modes": runtime_modes,
        "camera_summary": {
            "configured": len(settings.cameras),
            "enabled": sum(1 for camera in settings.cameras if camera.enabled),
            "local_preview": len(local_camera_ids),
            "live_frames": live_frames,
            "reporting": len(cameras),
        },
    }


def perform_service_action(
    settings: AppSettings,
    *,
    service_name: str,
    action: str,
    actor: str,
    note: str | None = None,
    repository: AlertRepository | None = None,
) -> dict[str, Any]:
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"start", "stop", "restart"}:
        raise ValueError("Unsupported service action.")
    supported, detail, launcher = _service_control_supported(service_name)
    if not supported or launcher is None:
        raise RuntimeError(detail)

    killed = 0
    if normalized_action in {"stop", "restart"}:
        killed = _kill_service_processes(service_name)
    if normalized_action in {"start", "restart"}:
        _spawn_service_launcher(launcher)
        time.sleep(1.2)

    result = {
        "service_name": service_name,
        "action": normalized_action,
        "killed_processes": killed,
        "launcher": launcher.name,
        "performed_at": utc_now().isoformat(),
        "processes": service_processes(service_name),
    }
    _record_audit(
        repository,
        entity_type="ops_service",
        entity_id=service_name,
        action_type=f"{normalized_action}_service",
        actor=actor,
        actor_role="admin",
        payload={**result, "note": note},
    )
    return result


def build_identity_summary(settings: AppSettings, directory: PersonDirectory, *, limit: int = 20) -> dict[str, Any]:
    report = build_identity_audit_report(settings)
    people = directory.get_people()
    face_root = settings.resolve_path(settings.face_recognition.face_profile_dir)
    incomplete_rows = list(report.get("incomplete_people", []))[: max(1, int(limit))]
    suggestion_rows: list[dict[str, Any]] = []
    for camera in settings.cameras:
        suggestion = directory.suggest_default_person_for_camera(camera)
        suggestion_rows.append(
            {
                "camera_id": camera.camera_id,
                "camera_name": camera.camera_name,
                "current_default_person_id": camera.default_person_id or "",
                "suggested_person_id": str(suggestion.get("person_id") or "") if suggestion else "",
                "suggested_name": str(suggestion.get("name") or "") if suggestion else "",
                "suggested_score": suggestion.get("_default_match_score") if suggestion else None,
                "face_samples": _count_face_samples(face_root, str(suggestion.get("person_id") or "")) if suggestion else 0,
            }
        )
    return {
        "generated_at": utc_now().isoformat(),
        "provider": settings.identity.provider,
        "registry_label": _repo_rel_label(report.get("registry_path")),
        "face_profile_label": _repo_rel_label(report.get("face_profile_dir")),
        "active_people": report.get("active_people", 0),
        "people_with_aliases": report.get("people_with_aliases", 0),
        "people_with_badge_keywords": report.get("people_with_badge_keywords", 0),
        "people_with_camera_bindings": report.get("people_with_camera_bindings", 0),
        "people_with_face_samples": report.get("people_with_face_samples", 0),
        "ocr": {
            "enabled": bool(settings.ocr.enabled),
            "provider": settings.ocr.provider,
        },
        "face_recognition": {
            "enabled": bool(settings.face_recognition.enabled),
        },
        "llm_fallback": {
            "enabled": bool(settings.llm_fallback.enabled),
            "openai_key_present": bool(os.getenv("OPENAI_API_KEY", "").strip()),
            "deepseek_key_present": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
        },
        "people_preview": [
            {
                "person_id": str(item.get("person_id") or ""),
                "name": str(item.get("name") or ""),
                "employee_id": str(item.get("employee_id") or ""),
                "department": str(item.get("department") or ""),
            }
            for item in people[: min(20, len(people))]
        ],
        "incomplete_people": incomplete_rows,
        "camera_default_suggestions": suggestion_rows,
    }


def sync_identity_registry(settings: AppSettings) -> dict[str, Any]:
    registry_path = settings.resolve_path(settings.identity.registry_path)
    if not registry_path.exists():
        raise FileNotFoundError(f"Person registry not found: {registry_path}")
    if not settings.supabase.is_configured or create_client is None:
        return {
            "status": "skipped",
            "detail": "Supabase sync is unavailable because credentials or dependencies are missing.",
            "synced_people": 0,
            "ignored_columns": [],
        }
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    client = create_client(settings.supabase.url, settings.supabase.service_role_key)
    ignored_columns = sorted(_sync_people(client, payload))
    return {
        "status": "synced",
        "detail": "Registry synced to Supabase persons.",
        "synced_people": len(payload) if isinstance(payload, list) else 0,
        "ignored_columns": ignored_columns,
    }


def bootstrap_identity_defaults(
    settings: AppSettings,
    directory: PersonDirectory,
    *,
    apply: bool,
    overwrite: bool,
) -> dict[str, Any]:
    config_payload = load_raw_config(settings.config_path)
    cameras = list(config_payload.get("cameras", []))
    face_root = settings.resolve_path(settings.face_recognition.face_profile_dir)
    updated = 0
    suggestions: list[dict[str, Any]] = []

    for camera_payload in cameras:
        if not isinstance(camera_payload, dict):
            continue
        camera_id = str(camera_payload.get("camera_id") or "")
        camera = next((item for item in settings.cameras if item.camera_id == camera_id), None)
        if camera is None:
            continue
        suggestion = directory.suggest_default_person_for_camera(camera)
        current_default = str(camera_payload.get("default_person_id") or "").strip()
        suggested_person_id = str(suggestion.get("person_id") or "") if suggestion else ""
        should_apply = bool(
            apply
            and suggested_person_id
            and (not current_default or overwrite)
            and current_default != suggested_person_id
        )
        if should_apply:
            camera_payload["default_person_id"] = suggested_person_id
            updated += 1
        suggestions.append(
            {
                "camera_id": camera.camera_id,
                "camera_name": camera.camera_name,
                "current_default_person_id": current_default,
                "suggested_person_id": suggested_person_id,
                "suggested_name": str(suggestion.get("name") or "") if suggestion else "",
                "suggested_score": suggestion.get("_default_match_score") if suggestion else None,
                "face_samples": _count_face_samples(face_root, suggested_person_id) if suggested_person_id else 0,
                "applied": should_apply,
            }
        )

    if updated:
        config_payload["cameras"] = cameras
        save_raw_config(settings.config_path, config_payload)

    return {
        "apply": bool(apply),
        "overwrite": bool(overwrite),
        "updated_defaults": updated,
        "suggestions": suggestions,
    }


def build_model_feedback_summary(settings: AppSettings, repository: AlertRepository) -> dict[str, Any]:
    ensure_feedback_workspace(settings)
    ops_paths = operations_paths(settings)
    feedback_workspace = feedback_paths(settings)
    registry = json.loads(ops_paths["model_feedback_registry"].read_text(encoding="utf-8")) if ops_paths["model_feedback_registry"].exists() else {"exports": [], "datasets": []}
    model_registry = json.loads(ops_paths["model_registry"].read_text(encoding="utf-8")) if ops_paths["model_registry"].exists() else {"active_model": None, "models": [], "promotion_history": []}
    cases = repository.list_hard_cases(limit=500)
    by_type: dict[str, int] = {}
    for item in cases:
        case_type = str(item.get("case_type") or "unknown")
        by_type[case_type] = by_type.get(case_type, 0) + 1
    return {
        "generated_at": utc_now().isoformat(),
        "hard_cases_total": len(cases),
        "hard_cases_by_type": by_type,
        "exports": [
            {
                **item,
                "export_dir": _repo_rel_label(item.get("export_dir")),
            }
            for item in list(registry.get("exports", []))
        ],
        "datasets": [
            {
                **item,
                "dataset_yaml": _repo_rel_label(item.get("dataset_yaml")),
                "manifest_path": _repo_rel_label(item.get("manifest_path")),
            }
            for item in list(registry.get("datasets", []))
        ],
        "workspace": {
            "feedback_exports": _path_state(feedback_workspace["feedback_exports_dir"]),
            "false_positive_dir": _path_state(feedback_workspace["false_positive_dir"]),
            "missed_detection_dir": _path_state(feedback_workspace["missed_detection_dir"]),
            "night_shift_dir": _path_state(feedback_workspace["night_shift_dir"]),
        },
        "models": {
            "active_model": model_registry.get("active_model"),
            "registered": len(model_registry.get("models", [])),
            "promotion_history": list(model_registry.get("promotion_history", []))[:20],
        },
        "recent_cases": [
            {
                key: value
                for key, value in case.items()
                if key not in {"snapshot_path", "snapshot_url", "clip_path", "clip_url"}
            }
            for case in cases[:20]
        ],
    }


def build_evidence_delivery_summary(settings: AppSettings, repository: AlertRepository) -> dict[str, Any]:
    ops = ensure_operations_state(settings)
    notification_logs = repository.list_notification_logs(limit=20)
    validation_logs = [
        item
        for item in repository.list_audit_logs(limit=100)
        if str(item.get("entity_type") or "") in {"ops_storage_validation", "ops_notification_validation"}
    ][:20]
    return {
        "generated_at": utc_now().isoformat(),
        "storage": {
            "requested_backend": settings.repository_backend,
            "upload_to_supabase_storage": bool(settings.persistence.upload_to_supabase_storage),
            "keep_local_copy": bool(settings.persistence.keep_local_copy),
            "private_bucket": bool(settings.security.use_private_bucket),
        },
        "paths": {
            "snapshot_dir": _path_state(settings.resolve_path(settings.persistence.snapshot_dir)),
            "runtime_dir": _path_state(settings.resolve_path(settings.persistence.runtime_dir)),
            "live_frames_dir": _path_state(ops["live_frames_dir"]),
        },
        "notifications": {
            "enabled": bool(settings.notifications.enabled),
            "email_enabled": bool(settings.notifications.email_enabled),
            "default_recipients": list(settings.notifications.default_recipients),
            "recent_logs": notification_logs,
        },
        "validation_logs": validation_logs,
    }


def run_storage_delivery_check(
    settings: AppSettings,
    *,
    actor: str,
    note: str | None = None,
    repository: AlertRepository | None = None,
) -> dict[str, Any]:
    result = run_storage_validation(settings, require_success=False)
    payload = {"status": "completed", **result, "performed_at": utc_now().isoformat(), "note": note}
    _record_audit(
        repository,
        entity_type="ops_storage_validation",
        entity_id=str(result.get("object_path") or "storage-validation"),
        action_type="validate_storage_delivery",
        actor=actor,
        actor_role="admin",
        payload=payload,
    )
    return payload


def run_notification_delivery_check(
    settings: AppSettings,
    *,
    actor: str,
    note: str | None = None,
    repository: AlertRepository | None = None,
) -> dict[str, Any]:
    class _Args:
        strict_runtime = False
        mode = "auto"
        recipient: list[str] = []
        camera_id = None
        require_success = False
        local_runtime_dir = None

    result = run_notification_validation(settings, _Args())
    payload = {"status": "completed", **result, "performed_at": utc_now().isoformat(), "note": note}
    _record_audit(
        repository,
        entity_type="ops_notification_validation",
        entity_id=str(result.get("event_no") or "notification-validation"),
        action_type="validate_notification_delivery",
        actor=actor,
        actor_role="admin",
        payload=payload,
    )
    return payload


def build_backups_payload(settings: AppSettings) -> dict[str, Any]:
    ops = ensure_operations_state(settings)
    registry = json.loads(ops["backup_registry"].read_text(encoding="utf-8")) if ops["backup_registry"].exists() else {"backups": []}
    items = []
    for record in list(registry.get("backups", [])):
        item = dict(record)
        item["backup_path"] = _repo_rel_label(item.get("backup_path"))
        items.append(item)
    return {
        "generated_at": utc_now().isoformat(),
        "items": items,
        "count": len(items),
        "latest": items[-1] if items else None,
    }


def build_releases_payload(settings: AppSettings) -> dict[str, Any]:
    ops = ensure_operations_state(settings)
    release_registry = json.loads(ops["release_registry"].read_text(encoding="utf-8")) if ops["release_registry"].exists() else {"active_release": None, "releases": [], "activation_history": []}
    model_registry = json.loads(ops["model_registry"].read_text(encoding="utf-8")) if ops["model_registry"].exists() else {"active_model": None, "models": [], "promotion_history": []}
    releases = []
    for record in list(release_registry.get("releases", [])):
        item = dict(record)
        item["config_snapshot"] = _repo_rel_label(item.get("config_snapshot"))
        item["config_path"] = _repo_rel_label(item.get("config_path"))
        item["model_path"] = _repo_rel_label(item.get("model_path"))
        releases.append(item)
    models = []
    for record in list(model_registry.get("models", [])):
        item = dict(record)
        item["model_path"] = _repo_rel_label(item.get("model_path"))
        item["dataset_manifest_path"] = _repo_rel_label(item.get("dataset_manifest_path"))
        models.append(item)
    return {
        "generated_at": utc_now().isoformat(),
        "active_release": release_registry.get("active_release"),
        "releases": releases,
        "activation_history": list(release_registry.get("activation_history", [])),
        "active_model": model_registry.get("active_model"),
        "models": models,
        "promotion_history": list(model_registry.get("promotion_history", [])),
    }


def _safe_json_load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)
    return payload if isinstance(payload, dict) else dict(default)


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN guard
        return None
    return number


def _ratio(part: Any, total: Any) -> float:
    try:
        denominator = max(float(total), 0.0)
        numerator = max(float(part), 0.0)
    except (TypeError, ValueError):
        return 0.0
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _quality_reports_dir() -> Path:
    path = REPO_ROOT / "artifacts" / "reports" / "quality"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _training_run_root_from_model_path(model_path: str | None) -> Path | None:
    if not model_path:
        return None
    target = Path(model_path)
    if not target.is_absolute():
        target = (REPO_ROOT / target).resolve()
    else:
        target = target.resolve()
    if target.name.lower() == "best.pt" and target.parent.name == "weights":
        return target.parent.parent
    if target.is_dir():
        return target
    return None


def _parse_results_metrics(results_csv: Path) -> dict[str, Any]:
    if not results_csv.exists():
        return {}
    try:
        with results_csv.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [row for row in reader if isinstance(row, dict) and row]
    except OSError:
        return {}
    if not rows:
        return {}
    latest = rows[-1]
    precision = _float_or_none(latest.get("metrics/precision(B)"))
    recall = _float_or_none(latest.get("metrics/recall(B)"))
    map50 = _float_or_none(latest.get("metrics/mAP50(B)"))
    map5095 = _float_or_none(latest.get("metrics/mAP50-95(B)"))
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = round((2 * precision * recall) / (precision + recall), 4)
    return {
        "epoch": int(float(latest.get("epoch") or 0)),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "map50": map50,
        "map50_95": map5095,
    }


def _detector_quality_state(
    metrics: dict[str, Any],
    *,
    settings: AppSettings,
    hard_cases_total: int,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    precision = _float_or_none(metrics.get("precision"))
    recall = _float_or_none(metrics.get("recall"))
    f1 = _float_or_none(metrics.get("f1"))
    if precision is None or recall is None:
        return "review_required", [
            "Site holdout metrics are missing. Freeze train / val / site_holdout before running another evaluation."
        ]
    if (
        precision < max(0.0, float(settings.quality.precision_threshold) - 0.07)
        or recall < max(0.0, float(settings.quality.recall_threshold) - 0.10)
        or (f1 is not None and f1 < max(0.0, float(settings.quality.f1_threshold) - 0.06))
    ):
        notes.append("Detector metrics are still below the balanced promotion gate. Retrain on the site benchmark and replay thresholds first.")
        return "invalid", notes
    if hard_cases_total > 12:
        notes.append("The hard-case pool is still large. Keep collecting night, backlight, and occlusion samples.")
    if (
        precision >= float(settings.quality.precision_threshold)
        and recall >= float(settings.quality.recall_threshold)
        and (f1 or 0.0) >= float(settings.quality.f1_threshold)
        and hard_cases_total <= 12
    ):
        notes.append("The detector is close to the balanced promotion gate and can move into stricter pilot video replay.")
        return "ready", notes
    notes.append("The detector can keep running, but it still needs a stronger site benchmark and hard-case reinforcement.")
    return "review_required", notes


def _identity_quality_state(*, enabled: bool, coverage_rate: float, strict_threshold_ok: bool, missing_message: str) -> tuple[str, list[str]]:
    if not enabled:
        return "invalid", [missing_message]
    if coverage_rate >= 0.9 and strict_threshold_ok:
        return "ready", ["Automation coverage is close to product grade, so we can gradually open more auto-resolve paths."]
    notes = []
    if coverage_rate < 0.9:
        notes.append("Registry coverage is still too low. Keep adding samples, aliases, and badge keywords.")
    if not strict_threshold_ok:
        notes.append("Current thresholds are still too loose for high-automation identity confirmation.")
    return "review_required", notes


def _run_summary(run_dir: Path) -> dict[str, Any]:
    results_csv = run_dir / "results.csv"
    weights = run_dir / "weights" / "best.pt"
    metrics = _parse_results_metrics(results_csv)
    latest_mtime = max(
        [path.stat().st_mtime for path in (results_csv, weights) if path.exists()] or [run_dir.stat().st_mtime]
    )
    return {
        "run_id": run_dir.name,
        "results_csv": _repo_rel_label(results_csv),
        "best_weights": _repo_rel_label(weights),
        "updated_at": datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat(),
        "metrics": metrics,
    }


def _latest_training_runs(limit: int = 5) -> list[dict[str, Any]]:
    root = REPO_ROOT / "artifacts" / "training_runs" / "helmet_project"
    if not root.exists():
        return []
    run_dirs = [item for item in root.iterdir() if item.is_dir()]
    run_dirs.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return [_run_summary(item) for item in run_dirs[: max(1, int(limit))]]


def _hard_case_scene_breakdown(cases: list[dict[str, Any]]) -> dict[str, int]:
    buckets = {
        "false_positive": 0,
        "missed_detection": 0,
        "night": 0,
        "backlight": 0,
        "crowd": 0,
        "occlusion": 0,
    }
    for case in cases:
        label = str(case.get("case_type") or "").lower()
        if "false" in label:
            buckets["false_positive"] += 1
        if "miss" in label:
            buckets["missed_detection"] += 1
        if "night" in label:
            buckets["night"] += 1
        if "back" in label or "glare" in label:
            buckets["backlight"] += 1
        if "crowd" in label or "group" in label:
            buckets["crowd"] += 1
        if "occl" in label or "cover" in label:
            buckets["occlusion"] += 1
    return buckets


def _stable_site_split(camera_id: str, date_key: str) -> str:
    seed = f"{camera_id}|{date_key}".encode("utf-8")
    bucket = int(hashlib.sha256(seed).hexdigest()[:8], 16) % 10
    if bucket < 6:
        return "train"
    if bucket < 8:
        return "val"
    return "site_holdout"


def _scene_tags(*values: Any) -> list[str]:
    text = " ".join(str(item or "") for item in values).lower()
    tags: list[str] = []
    if any(token in text for token in ("night", "dark", "晚", "夜")):
        tags.append("night")
    if any(token in text for token in ("backlight", "back_light", "glare", "逆光", "背光")):
        tags.append("backlight")
    if any(token in text for token in ("crowd", "group", "dense", "密集", "人群")):
        tags.append("crowd")
    if any(token in text for token in ("occlusion", "occluded", "cover", "遮挡")):
        tags.append("occlusion")
    return tags


def _label_bucket(*values: Any) -> str:
    text = " ".join(str(item or "") for item in values).strip().lower()
    if "no_helmet" in text or "without_helmet" in text or "violation" in text:
        return "no_helmet"
    return "helmet"


def _site_benchmark_status(summary: dict[str, Any]) -> tuple[str, list[str]]:
    notes: list[str] = []
    split_counts = summary.get("splits", {})
    if not split_counts.get("site_holdout"):
        notes.append("The site benchmark is missing a site_holdout split, so promotion cannot proceed yet.")
    if int(summary.get("camera_count") or 0) < 2:
        notes.append("The site benchmark needs data from at least two cameras before it is trustworthy.")
    if int(summary.get("date_count") or 0) < 3:
        notes.append("The site benchmark should cover at least three dates before it is used as a gate.")
    if not summary.get("labels", {}).get("helmet"):
        notes.append("The benchmark currently lacks stable helmet samples, so no_helmet alone is not enough for promotion.")
    return ("ready" if not notes else "review_required", notes)


def _write_json_artifact(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return _repo_rel_label(path) or path.name


def _build_site_benchmark_manifest(repository: AlertRepository, hard_case_breakdown: dict[str, int]) -> dict[str, Any]:
    alerts = repository.list_alerts(limit=5000)
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    split_counts = {"train": 0, "val": 0, "site_holdout": 0}
    labels = {"helmet": 0, "no_helmet": 0}
    scenes = {"night": 0, "backlight": 0, "crowd": 0, "occlusion": 0}
    cameras: set[str] = set()
    dates: set[str] = set()

    for alert in alerts:
        camera_id = str(alert.get("camera_id") or "unknown")
        created_at = parse_timestamp(alert.get("created_at"))
        if created_at == datetime.min.replace(tzinfo=timezone.utc):
            continue
        date_key = created_at.date().isoformat()
        split = _stable_site_split(camera_id, date_key)
        entry_key = ("alert", str(alert.get("alert_id") or alert.get("event_no") or ""))
        if entry_key in seen:
            continue
        seen.add(entry_key)
        scene_tags = _scene_tags(
            alert.get("review_note"),
            alert.get("governance_note"),
            alert.get("location"),
            alert.get("zone_name"),
            alert.get("workshop_name"),
        )
        if created_at.hour >= 19 or created_at.hour <= 6:
            scene_tags = sorted(set(scene_tags + ["night"]))
        for tag in scene_tags:
            scenes[tag] = scenes.get(tag, 0) + 1
        label = _label_bucket(alert.get("violation_type"), alert.get("status"), alert.get("event_no"))
        labels[label] = labels.get(label, 0) + 1
        split_counts[split] += 1
        cameras.add(camera_id)
        dates.add(date_key)
        items.append(
            {
                "source": "alert",
                "id": str(alert.get("alert_id") or alert.get("event_no") or ""),
                "event_no": alert.get("event_no"),
                "camera_id": camera_id,
                "camera_name": alert.get("camera_name"),
                "date": date_key,
                "split": split,
                "label_bucket": label,
                "scene_tags": scene_tags,
                "snapshot_path": _repo_rel_label(Path(str(alert.get("snapshot_path")))) if alert.get("snapshot_path") else None,
                "clip_path": _repo_rel_label(Path(str(alert.get("clip_path")))) if alert.get("clip_path") else None,
            }
        )

    summary = {
        "total": len(items),
        "splits": split_counts,
        "camera_count": len(cameras),
        "date_count": len(dates),
        "labels": labels,
        "scene_breakdown": {
            "night": scenes.get("night", 0) + int(hard_case_breakdown.get("night") or 0),
            "backlight": scenes.get("backlight", 0) + int(hard_case_breakdown.get("backlight") or 0),
            "crowd": scenes.get("crowd", 0) + int(hard_case_breakdown.get("crowd") or 0),
            "occlusion": scenes.get("occlusion", 0) + int(hard_case_breakdown.get("occlusion") or 0),
        },
    }
    status, notes = _site_benchmark_status(summary)
    payload = {
        "generated_at": utc_now().isoformat(),
        "status": status,
        "notes": notes,
        "summary": summary,
        "items": items,
        "dataset_yaml": "configs/datasets/shwd_yolo26.yaml",
        "rules": {
            "split_unit": "camera_id + date",
            "allowed_labels": ["helmet", "no_helmet"],
        },
    }
    manifest_path = _quality_reports_dir() / "site_benchmark_manifest.json"
    payload["artifact_path"] = _write_json_artifact(manifest_path, payload)
    return payload


def _build_pilot_video_eval(settings: AppSettings, hard_case_breakdown: dict[str, int]) -> dict[str, Any]:
    clip_root = REPO_ROOT / "artifacts" / "captures" / "clips"
    clip_paths = sorted(clip_root.rglob("*.mp4")) if clip_root.exists() else []
    recent = clip_paths[-120:]
    camera_ids = {path.parent.name for path in recent}
    date_keys = {path.parent.parent.name for path in recent if path.parent.parent}
    payload = {
        "generated_at": utc_now().isoformat(),
        "status": "review_required",
        "evaluation_mode": "inventory_replay_proxy",
        "sampled_cases": len(recent),
        "sampled_clips": len(recent),
        "camera_count": len(camera_ids),
        "date_count": len(date_keys),
        "false_positive": int(hard_case_breakdown.get("false_positive") or 0),
        "missed_detection": int(hard_case_breakdown.get("missed_detection") or 0),
        "mean_latency_ms": None,
        "p95_latency_ms": None,
        "clip_hit_rate": None,
        "temporal_stability": None,
        "average_latency_ms": None,
        "notes": [
            "The current pilot video replay is still an inventory proxy built from local clips and hard-case counts.",
            "Do not treat this as a promotion pass until a real pilot video run confirms both false-positive and missed-detection behavior.",
        ],
    }
    if (
        len(recent) >= int(settings.quality.pilot_replay_min_samples)
        and payload["false_positive"] == 0
        and payload["missed_detection"] == 0
    ):
        payload["status"] = "ready"
    pilot_path = _quality_reports_dir() / "pilot_video_eval.json"
    payload["artifact_path"] = _write_json_artifact(pilot_path, payload)
    return payload


QUALITY_TEXT_NORMALIZATION = {}


def _normalize_quality_text(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return QUALITY_TEXT_NORMALIZATION.get(text, text)


def _normalize_quality_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _normalize_quality_text(value)
    if isinstance(value, list):
        return [_normalize_quality_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_quality_payload(item) for key, item in value.items()}
    return value


def _load_latest_compare_report() -> dict[str, Any] | None:
    target = _quality_reports_dir() / "detector_compare_report.json"
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_quality_json(name: str) -> dict[str, Any] | None:
    target = _quality_reports_dir() / name
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _pilot_video_gate_status(settings: AppSettings, pilot_video_eval: dict[str, Any]) -> tuple[bool, list[str]]:
    notes: list[str] = []
    sampled_cases = int(pilot_video_eval.get("sampled_cases") or pilot_video_eval.get("sampled_clips") or 0)
    mean_latency_ms = _float_or_none(pilot_video_eval.get("mean_latency_ms") or pilot_video_eval.get("average_latency_ms"))
    p95_latency_ms = _float_or_none(pilot_video_eval.get("p95_latency_ms"))
    if sampled_cases < int(settings.quality.pilot_replay_min_samples):
        notes.append("pilot replay sampled cases below threshold")
    if mean_latency_ms is None:
        notes.append("pilot replay mean latency missing")
    elif mean_latency_ms > float(settings.quality.mean_latency_ms_threshold):
        notes.append("pilot replay mean latency above threshold")
    if p95_latency_ms is None:
        notes.append("pilot replay p95 latency missing")
    elif p95_latency_ms > float(settings.quality.p95_latency_ms_threshold):
        notes.append("pilot replay p95 latency above threshold")
    if pilot_video_eval.get("status") == "invalid":
        notes.append("pilot replay reported invalid")
    return (not notes, notes)


def _runtime_quality_context(settings: AppSettings) -> dict[str, Any]:
    runtime_db = settings.resolve_path(settings.persistence.runtime_dir) / "helmet_monitoring.db"
    dead_letter = 0
    if runtime_db.exists():
        try:
            with sqlite3.connect(str(runtime_db), timeout=5) as conn:
                row = conn.execute("SELECT COUNT(*) FROM task_queue WHERE status = 'dead_letter'").fetchone()
                dead_letter = int(row[0] or 0) if row else 0
        except Exception:
            dead_letter = 0
    queue_stats = {}
    try:
        queue_stats = get_queue_stats()
    except Exception:
        queue_stats = {}
    return {
        "onnxruntime_available": importlib.util.find_spec("onnxruntime") is not None,
        "sqlite_db": {
            "configured": True,
            "exists": runtime_db.exists(),
            "label": _repo_rel_label(runtime_db) or runtime_db.name,
        },
        "task_queue": {
            "dead_letter": dead_letter,
            "stats": queue_stats,
        },
        "websocket": {
            "status": "configured",
            "topics": ["alerts", "dashboard", "cameras"],
        },
        "ci": {
            "configured": (REPO_ROOT / ".github" / "workflows").exists(),
        },
        "docker": {
            "configured": any((REPO_ROOT / name).exists() for name in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml")),
        },
    }


def _write_quality_artifacts(payload: dict[str, Any]) -> dict[str, str]:
    target_dir = _quality_reports_dir()
    json_path = target_dir / "latest_quality_summary.json"
    markdown_path = target_dir / "latest_quality_summary.md"
    text_path = target_dir / "latest_quality_summary.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Safety Helmet Quality Lab",
        "",
        f"- Generated at: {payload.get('generated_at', '--')}",
        f"- Detector state: {payload.get('detector', {}).get('state', '--')}",
        f"- Badge OCR state: {payload.get('badge_ocr', {}).get('state', '--')}",
        f"- Face identity state: {payload.get('face_identity', {}).get('state', '--')}",
        "",
        "## Active Thresholds",
        f"- Detector / Alert: {payload.get('active_thresholds', {}).get('detector_confidence', '--')} / {payload.get('active_thresholds', {}).get('alert_confidence', '--')}",
        f"- OCR: {payload.get('active_thresholds', {}).get('ocr_min_confidence', '--')}",
        f"- Face Similarity / Review: {payload.get('active_thresholds', {}).get('face_similarity_threshold', '--')} / {payload.get('active_thresholds', {}).get('face_review_threshold', '--')}",
        "",
        "## Detector",
        f"- Active model: {payload.get('detector', {}).get('active_model', '--')}",
        f"- Precision: {payload.get('detector', {}).get('active_run', {}).get('metrics', {}).get('precision', '--')}",
        f"- Recall: {payload.get('detector', {}).get('active_run', {}).get('metrics', {}).get('recall', '--')}",
        f"- F1: {payload.get('detector', {}).get('active_run', {}).get('metrics', {}).get('f1', '--')}",
        "",
        "## Site Benchmark",
        f"- Status: {payload.get('site_benchmark', {}).get('status', '--')}",
        f"- Summary: {payload.get('site_benchmark', {}).get('summary', {}).get('total', '--')} items",
        "",
        "## Pilot Video",
        f"- Status: {payload.get('pilot_video_eval', {}).get('status', '--')}",
        f"- Sampled clips: {payload.get('pilot_video_eval', {}).get('sampled_clips', '--')}",
        "",
        "## Recommendations",
    ]
    for item in payload.get("next_actions", []):
        lines.append(f"- {item}")
    latest_compare = payload.get("latest_compare_report") or {}
    if latest_compare:
        lines.extend(
            [
                "",
                "## Latest Compare Report",
                f"- Baseline: {latest_compare.get('baseline_model', '--')}",
                f"- Candidate: {latest_compare.get('candidate_model', '--')}",
                f"- Conclusion: {latest_compare.get('conclusion', '--')}",
            ]
        )
        for reason in latest_compare.get("block_reasons", []):
            lines.append(f"- Block reason: {reason}")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    plain_lines = [
        "Safety Helmet Quality Lab",
        f"Generated at: {payload.get('generated_at', '--')}",
        "",
        "Active thresholds",
        f"  detector_confidence={payload.get('active_thresholds', {}).get('detector_confidence', '--')}",
        f"  alert_confidence={payload.get('active_thresholds', {}).get('alert_confidence', '--')}",
        f"  ocr_min_confidence={payload.get('active_thresholds', {}).get('ocr_min_confidence', '--')}",
        f"  face_similarity_threshold={payload.get('active_thresholds', {}).get('face_similarity_threshold', '--')}",
        f"  face_review_threshold={payload.get('active_thresholds', {}).get('face_review_threshold', '--')}",
        "",
        "Promotion gate",
        f"  status={payload.get('promotion_gate', {}).get('status', '--')}",
        f"  reason={payload.get('promotion_gate', {}).get('reason', '--')}",
        "",
        "Latest compare report",
        f"  baseline={latest_compare.get('baseline_model', '--')}",
        f"  candidate={latest_compare.get('candidate_model', '--')}",
        f"  conclusion={latest_compare.get('conclusion', '--')}",
    ]
    for reason in latest_compare.get("block_reasons", []):
        plain_lines.append(f"  block_reason={reason}")
    plain_lines.extend(
        [
            "",
        "Next actions",
        ]
    )
    for item in payload.get("next_actions", []):
        plain_lines.append(f"  - {item}")
    text_path.write_text("\n".join(plain_lines), encoding="utf-8")
    return {
        "summary_json": _repo_rel_label(json_path) or json_path.name,
        "summary_markdown": _repo_rel_label(markdown_path) or markdown_path.name,
        "summary_text": _repo_rel_label(text_path) or text_path.name,
    }


def build_quality_summary(settings: AppSettings, repository: AlertRepository, directory: PersonDirectory) -> dict[str, Any]:
    identity = build_identity_summary(settings, directory, limit=20)
    releases = build_releases_payload(settings)
    model_registry = _safe_json_load(operations_paths(settings)["model_registry"], {"active_model": None, "models": []})
    active_model = str(model_registry.get("active_model") or "")
    active_record = next((item for item in model_registry.get("models", []) if str(item.get("model_id") or "") == active_model), None)
    active_run_root = _training_run_root_from_model_path(active_record.get("model_path") if isinstance(active_record, dict) else None)
    active_run = _run_summary(active_run_root) if active_run_root else {}
    latest_runs = _latest_training_runs(limit=5)
    hard_cases = repository.list_hard_cases(limit=500)
    hard_case_breakdown = _hard_case_scene_breakdown(hard_cases)
    site_benchmark = _load_quality_json("site_benchmark_manifest.json") or _build_site_benchmark_manifest(repository, hard_case_breakdown)
    pilot_video_eval = _load_quality_json("pilot_video_eval.json") or _build_pilot_video_eval(settings, hard_case_breakdown)
    latest_compare_report = _load_latest_compare_report()
    runtime_health = _runtime_quality_context(settings)

    detector_state, detector_notes = _detector_quality_state(
        active_run.get("metrics", {}) if isinstance(active_run, dict) else {},
        settings=settings,
        hard_cases_total=len(hard_cases),
    )

    active_people = int(identity.get("active_people") or 0)
    badge_people = int(identity.get("people_with_badge_keywords") or 0)
    face_people = int(identity.get("people_with_face_samples") or 0)
    badge_coverage = _ratio(badge_people, active_people)
    face_coverage = _ratio(face_people, active_people)

    badge_state, badge_notes = _identity_quality_state(
        enabled=bool(settings.ocr.enabled) and str(settings.ocr.provider or "none").lower() != "none",
        coverage_rate=badge_coverage,
        strict_threshold_ok=float(settings.ocr.min_confidence) >= 0.55,
        missing_message="OCR provider is disabled, so high-automation badge recognition cannot be enabled.",
    )
    face_state, face_notes = _identity_quality_state(
        enabled=bool(settings.face_recognition.enabled),
        coverage_rate=face_coverage,
        strict_threshold_ok=float(settings.face_recognition.similarity_threshold) >= 0.72 and float(settings.face_recognition.review_threshold) >= 0.58,
        missing_message="Face recognition is disabled, so identity cannot be auto-confirmed.",
    )

    active_thresholds = {
        "detector_confidence": round(float(settings.model.confidence), 2),
        "alert_confidence": round(float(settings.event_rules.min_confidence_for_alert), 2),
        "ocr_min_confidence": round(float(settings.ocr.min_confidence), 2),
        "face_similarity_threshold": round(float(settings.face_recognition.similarity_threshold), 2),
        "face_review_threshold": round(float(settings.face_recognition.review_threshold), 2),
        "review_confidence_margin": round(float(settings.governance.review_confidence_margin), 2),
    }
    recommended_thresholds = {
        "detector_confidence": round(max(float(settings.model.confidence), 0.52), 2),
        "alert_confidence": round(max(float(settings.event_rules.min_confidence_for_alert), 0.58), 2),
        "ocr_min_confidence": round(max(float(settings.ocr.min_confidence), 0.55), 2),
        "face_similarity_threshold": round(max(float(settings.face_recognition.similarity_threshold), 0.72), 2),
        "face_review_threshold": round(max(float(settings.face_recognition.review_threshold), 0.58), 2),
        "review_confidence_margin": round(max(float(settings.governance.review_confidence_margin), 0.08), 2),
    }

    detector_notes = [_normalize_quality_text(item) for item in detector_notes if _normalize_quality_text(item)]
    badge_notes = [_normalize_quality_text(item) for item in badge_notes if _normalize_quality_text(item)]
    face_notes = [_normalize_quality_text(item) for item in face_notes if _normalize_quality_text(item)]

    benchmark_ready = site_benchmark.get("status") == "ready"
    if settings.quality.site_holdout_required and not site_benchmark.get("summary", {}).get("splits", {}).get("site_holdout"):
        benchmark_ready = False
    pilot_ready, pilot_gate_notes = _pilot_video_gate_status(settings, pilot_video_eval)
    if detector_state == "invalid":
        promotion_status = "invalid"
        promotion_reason = "Detector metrics are still below the balanced promotion gate. Finish the local benchmark and hard-case retraining first."
    elif detector_state == "ready" and benchmark_ready and pilot_ready:
        promotion_status = "ready"
        promotion_reason = "Pilot video replay and site holdout both passed, so this detector can move into a stricter release review."
    else:
        promotion_status = "review_required"
        blockers: list[str] = []
        if not benchmark_ready:
            blockers.append("site benchmark not ready")
        if not pilot_ready:
            blockers.append("pilot video replay not ready")
        if detector_state != "ready":
            blockers.append("detector metrics still need work")
        promotion_reason = " / ".join(blockers) if blockers else "Detector quality still needs review."

    next_actions: list[str] = []
    next_actions.extend(detector_notes)
    next_actions.extend(badge_notes)
    next_actions.extend(face_notes)
    if detector_state != "ready":
        next_actions.append("Freeze the site holdout split by camera and date before running the next detector retraining cycle.")
    if not benchmark_ready:
        next_actions.append("Add more night, backlight, occlusion, and crowd hard-cases, then regenerate the site benchmark manifest.")
    if not pilot_ready:
        next_actions.append("Run a real pilot video replay to measure false positives, misses, and latency instead of relying on mAP alone.")
    next_actions.extend(pilot_gate_notes)
    if badge_state != "ready":
        next_actions.append("Build a badge OCR eval set and tune ROI plus preprocessing before considering custom OCR training.")
    if face_state != "ready":
        next_actions.append("Collect more face samples and enforce top-1 plus top-2 margin gating before allowing automatic identity confirmation.")

    deduped_actions: list[str] = []
    seen_actions: set[str] = set()
    for item in next_actions:
        normalized = _normalize_quality_text(item)
        if not normalized or normalized in seen_actions:
            continue
        seen_actions.add(normalized)
        deduped_actions.append(normalized)

    payload = {
        "generated_at": utc_now().isoformat(),
        "strategy": {
            "frontend_style": "Refined terminal feel",
            "detector_priority": "Balanced",
            "identity_policy": "High automation with strict gates",
        },
        "thresholds": active_thresholds,
        "active_thresholds": active_thresholds,
        "recommended_thresholds": recommended_thresholds,
        "detector": {
            "state": detector_state,
            "active_model": active_model or None,
            "active_release": releases.get("active_release"),
            "active_run": active_run,
            "latest_runs": latest_runs,
            "hard_cases_total": len(hard_cases),
            "hard_case_breakdown": hard_case_breakdown,
            "recommended_confidence": recommended_thresholds["detector_confidence"],
            "recommended_alert_confidence": recommended_thresholds["alert_confidence"],
            "notes": detector_notes,
            "needs_site_retraining": detector_state != "ready" or not benchmark_ready,
        },
        "badge_ocr": {
            "state": badge_state,
            "enabled": bool(settings.ocr.enabled),
            "provider": settings.ocr.provider,
            "coverage_rate": badge_coverage,
            "people_with_badge_keywords": badge_people,
            "active_people": active_people,
            "thresholds": {
                "current": active_thresholds["ocr_min_confidence"],
                "recommended": recommended_thresholds["ocr_min_confidence"],
            },
            "notes": badge_notes,
            "needs_custom_training": False,
            "training_gate": "Only consider custom OCR training after site eval still misses target post ROI and policy tuning.",
        },
        "face_identity": {
            "state": face_state,
            "enabled": bool(settings.face_recognition.enabled),
            "coverage_rate": face_coverage,
            "people_with_face_samples": face_people,
            "active_people": active_people,
            "thresholds": {
                "similarity": active_thresholds["face_similarity_threshold"],
                "review": active_thresholds["face_review_threshold"],
                "recommended_similarity": recommended_thresholds["face_similarity_threshold"],
                "recommended_review": recommended_thresholds["face_review_threshold"],
                "recommended_top1_margin": recommended_thresholds["review_confidence_margin"],
            },
            "notes": face_notes,
            "needs_custom_training": False,
            "training_gate": "Only consider custom metric-learning after threshold recalibration and more face samples still fail the site benchmark.",
        },
        "latest_benchmark_runs": latest_runs,
        "identity_coverage": {
            "aliases": identity.get("people_with_aliases"),
            "camera_bindings": identity.get("people_with_camera_bindings"),
            "registry_label": identity.get("registry_label"),
            "face_profile_label": identity.get("face_profile_label"),
        },
        "site_benchmark": site_benchmark,
        "pilot_video_eval": pilot_video_eval,
        "runtime_health": runtime_health,
        "hard_case_scene_breakdown": site_benchmark.get("summary", {}).get("scene_breakdown", hard_case_breakdown),
        "latest_compare_report": latest_compare_report,
        "promotion_gate": {
            "status": promotion_status,
            "reason": promotion_reason,
            "requirements": {
                "detector_ready": detector_state == "ready",
                "site_benchmark_ready": benchmark_ready,
                "pilot_video_ready": pilot_ready,
                "onnxruntime_available": bool(runtime_health.get("onnxruntime_available")),
                "sqlite_ready": bool(runtime_health.get("sqlite_db", {}).get("exists")),
                "task_queue_dead_letter": int(runtime_health.get("task_queue", {}).get("dead_letter") or 0),
            },
        },
        "next_actions": deduped_actions[:12],
    }
    payload = _normalize_quality_payload(payload)
    payload["artifacts"] = _write_quality_artifacts(payload)
    return payload
