from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from helmet_monitoring.core.config import AppSettings
from helmet_monitoring.services.operations import operations_paths
from helmet_monitoring.services.video_sources import is_local_device_source
from helmet_monitoring.storage.repository import AlertRepository, parse_timestamp


UTC = timezone.utc
CLOSED_STATUSES = {"remediated", "ignored", "false_positive", "confirmed"}


ROLE_ROUTES: dict[str, tuple[str, ...]] = {
    "admin": (
        "/dashboard",
        "/review",
        "/operations",
        "/config",
        "/cameras",
        "/reports",
        "/notifications",
        "/hard-cases",
        "/access-admin",
    ),
    "safety_manager": (
        "/dashboard",
        "/review",
        "/operations",
        "/config",
        "/cameras",
        "/reports",
        "/notifications",
        "/hard-cases",
    ),
    "team_lead": ("/dashboard", "/review", "/cameras", "/reports", "/hard-cases", "/config"),
    "viewer": ("/dashboard", "/review", "/cameras", "/reports", "/hard-cases", "/config"),
}


def visible_routes_for_role(role: str | None) -> tuple[str, ...]:
    return ROLE_ROUTES.get(str(role or "").strip().lower(), ROLE_ROUTES["viewer"])


def start_of_day(now: datetime | None = None) -> datetime:
    current = now or datetime.now(tz=UTC)
    return current.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def date_floor(days: int, now: datetime | None = None) -> datetime:
    current = now or datetime.now(tz=UTC)
    return current - timedelta(days=max(1, int(days)))


def load_monitor_runtime(settings: AppSettings) -> dict[str, Any]:
    status_path = operations_paths(settings)["monitor_health"]
    if not status_path.exists():
        return {}
    try:
        with status_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def configured_camera_payload(camera) -> dict[str, Any]:
    payload = {
        "camera_id": camera.camera_id,
        "camera_name": camera.camera_name,
        "source": str(camera.source),
        "location": camera.location,
        "department": camera.department,
        "enabled": camera.enabled,
        "default_person_id": camera.default_person_id,
        "site_name": camera.site_name,
        "building_name": camera.building_name,
        "floor_name": camera.floor_name,
        "workshop_name": camera.workshop_name,
        "zone_name": camera.zone_name,
        "responsible_department": camera.responsible_department,
        "alert_emails": list(camera.alert_emails),
    }
    if is_local_device_source(str(camera.source).strip()):
        payload.update(
            {
                "status": "browser_preview",
                "last_status": "browser_preview",
                "last_error": None,
                "last_fps": "browser",
            }
        )
    return payload


def merge_live_cameras(settings: AppSettings, cameras: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    monitor_runtime = load_monitor_runtime(settings)
    status_by_camera = {
        str(item.get("camera_id")): item
        for item in monitor_runtime.get("camera_statuses", [])
        if isinstance(item, dict) and item.get("camera_id")
    }
    merged_by_camera: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def merge_item(item: dict[str, Any]) -> None:
        camera_id = str(item.get("camera_id") or "").strip()
        if not camera_id:
            return
        if camera_id not in merged_by_camera:
            merged_by_camera[camera_id] = {}
            order.append(camera_id)
        merged_by_camera[camera_id].update(dict(item))

    for item in cameras:
        merge_item(item)
    for payload in status_by_camera.values():
        merge_item(payload)
    for configured in settings.cameras:
        merge_item(configured_camera_payload(configured))

    return monitor_runtime, [merged_by_camera[camera_id] for camera_id in order]


def filter_alerts(
    alerts: list[dict[str, Any]],
    *,
    text_query: str = "",
    statuses: set[str] | None = None,
    departments: set[str] | None = None,
    camera_ids: set[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    query = text_query.strip().lower()
    for alert in alerts:
        created_at = parse_timestamp(alert.get("created_at"))
        if statuses and str(alert.get("status") or "") not in statuses:
            continue
        if departments and str(alert.get("department") or "") not in departments:
            continue
        if camera_ids and str(alert.get("camera_id") or "") not in camera_ids:
            continue
        if date_from and created_at < date_from:
            continue
        if date_to and created_at > date_to:
            continue
        haystack = " ".join(
            str(alert.get(key, ""))
            for key in (
                "event_no",
                "alert_id",
                "camera_name",
                "camera_id",
                "person_name",
                "employee_id",
                "department",
                "location",
                "assigned_to",
            )
        ).lower()
        if query and query not in haystack:
            continue
        results.append(alert)
    return results


def sort_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(alerts, key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)


def summarize_alerts(alerts: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(alerts),
        "pending": sum(1 for item in alerts if item.get("status") == "pending"),
        "assigned": sum(1 for item in alerts if item.get("status") == "assigned"),
        "review_required": sum(1 for item in alerts if item.get("identity_status") in {"review_required", "unresolved"}),
        "resolved_identity": sum(1 for item in alerts if item.get("identity_status") == "resolved"),
        "remediated": sum(1 for item in alerts if item.get("status") == "remediated"),
        "false_positive": sum(1 for item in alerts if item.get("status") == "false_positive"),
        "closed": sum(1 for item in alerts if item.get("status") in CLOSED_STATUSES),
    }


def camera_summary(settings: AppSettings, cameras: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, int]:
    current = now or datetime.now(tz=UTC)
    reporting = 0
    abnormal = 0
    for camera in cameras:
        status = str(camera.get("last_status") or camera.get("status") or "").lower()
        if status in {"offline", "error", "failed"}:
            abnormal += 1
        if status == "browser_preview":
            reporting += 1
            continue
        last_seen = parse_timestamp(camera.get("last_seen_at"))
        if last_seen != datetime.min.replace(tzinfo=UTC) and (current - last_seen) <= timedelta(minutes=10):
            reporting += 1
    return {
        "configured": len(settings.cameras),
        "enabled": sum(1 for camera in settings.cameras if camera.enabled),
        "reporting": reporting,
        "abnormal": abnormal,
    }


def hourly_trend(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(parse_timestamp(item.get("created_at")).hour for item in alerts)
    return [{"hour": f"{hour:02d}:00", "alerts": int(counts.get(hour, 0))} for hour in range(24)]


def daily_trend(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for item in alerts:
        parsed = parse_timestamp(item.get("created_at"))
        if parsed != datetime.min.replace(tzinfo=UTC):
            counts[parsed.date().isoformat()] += 1
    return [{"date": key, "alerts": int(value)} for key, value in sorted(counts.items())]


def status_mix(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(str(item.get("status") or "unknown") for item in alerts)
    return [{"status": key, "count": int(value)} for key, value in counts.most_common()]


def department_ranking(alerts: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    counts = Counter(str(item.get("department") or "Unknown") for item in alerts)
    return [{"department": key, "alerts": int(value)} for key, value in counts.most_common(limit)]


def zone_ranking(alerts: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    counts = Counter(str(item.get("zone_name") or item.get("location") or "Unknown") for item in alerts)
    return [{"zone_name": key, "alerts": int(value)} for key, value in counts.most_common(limit)]


def people_ranking(alerts: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    for item in alerts:
        name = str(item.get("person_name") or "Unknown")
        employee_id = str(item.get("employee_id") or "--")
        counts[(name, employee_id)] += 1
    return [
        {"person_name": name, "employee_id": employee_id, "alerts": int(value)}
        for (name, employee_id), value in counts.most_common(limit)
    ]


def identity_source_mix(alerts: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    counts = Counter(str(item.get("identity_source") or "unknown") for item in alerts)
    return [{"identity_source": key, "count": int(value)} for key, value in counts.most_common(limit)]


def camera_ranking(alerts: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    for item in alerts:
        camera_id = str(item.get("camera_id") or "--")
        camera_name = str(item.get("camera_name") or camera_id)
        counts[(camera_name, camera_id)] += 1
    return [
        {"camera_name": camera_name, "camera_id": camera_id, "alerts": int(value)}
        for (camera_name, camera_id), value in counts.most_common(limit)
    ]


def visitor_evidence_summary(records: list[dict[str, Any]], *, limit: int = 6) -> dict[str, Any]:
    items = sorted(records, key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)
    recent = items[: max(1, int(limit))]
    return {
        "total": len(items),
        "latest_at": recent[0].get("created_at") if recent else None,
        "items": recent,
    }


def mixed_hotspots(todays_alerts: list[dict[str, Any]], fallback_alerts: list[dict[str, Any]]) -> dict[str, Any]:
    source_alerts = todays_alerts if todays_alerts else fallback_alerts
    mode = "today" if todays_alerts else "fallback_7d"
    return {
        "mode": mode,
        "departments": department_ranking(source_alerts, limit=5),
        "zones": zone_ranking(source_alerts, limit=5),
        "cameras": camera_ranking(source_alerts, limit=5),
    }


def build_overview_payload(
    settings: AppSettings,
    repository: AlertRepository,
    *,
    days: int = 7,
    recent_limit: int = 12,
    evidence_limit: int = 6,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(tz=UTC)
    since = date_floor(days, now=current)
    raw_cameras = repository.list_cameras()
    monitor_runtime, cameras = merge_live_cameras(settings, raw_cameras)
    aggregates = repository.get_dashboard_aggregates(days=days, now=current, preview_limit=max(recent_limit * 4, evidence_limit * 4, 24))
    filtered = sort_alerts(list(aggregates.get("recent_alerts") or []))
    recent_page = repository.list_alerts_page(limit=max(recent_limit * 4, evidence_limit * 4, 24), since=since)
    recent_items = sort_alerts(list(recent_page.get("items") or []))
    todays_alerts = filter_alerts(recent_items, date_from=start_of_day(current))
    visitor_records = filter_alerts(
        repository.list_visitor_evidence(limit=100),
        date_from=since,
    )
    metrics = dict(aggregates.get("metrics") or {})
    latest_event = recent_items[0].get("event_no") or recent_items[0].get("alert_id") if recent_items else "--"
    top_department = (aggregates.get("department_ranking") or [])[:1]

    return {
        "generated_at": current.isoformat(),
        "repository_backend": repository.backend_name,
        "monitor_runtime": monitor_runtime,
        "window_days": max(1, int(days)),
        "metrics": {
            "today_alerts": int(metrics.get("today_alerts") or 0),
            "pending_queue": int(metrics.get("pending_queue") or 0),
            "review_required": int(metrics.get("review_required") or 0),
            "resolved_identity": int(metrics.get("resolved_identity") or 0),
            "false_positive": int(metrics.get("false_positive") or 0),
            "closure_rate": float(metrics.get("closure_rate") or 0.0),
        },
        "signals": {
            "remediated_today": summarize_alerts(todays_alerts)["remediated"],
            "focus_department": top_department[0].get("department") if top_department else "--",
            "latest_event": latest_event,
            "data_backend": repository.backend_name.upper(),
        },
        "camera_summary": camera_summary(settings, cameras, now=current),
        "hourly_trend": list(aggregates.get("hourly_trend") or hourly_trend(todays_alerts)),
        "department_ranking": list(aggregates.get("department_ranking") or department_ranking(todays_alerts)),
        "hotspots": {
            "mode": "today" if todays_alerts else "fallback_7d",
            "departments": list((aggregates.get("department_ranking") or [])[:5]),
            "zones": list((aggregates.get("zone_ranking") or [])[:5]),
            "cameras": list((aggregates.get("camera_ranking") or [])[:5]),
        },
        "status_mix": list(aggregates.get("status_mix") or status_mix(recent_items)),
        "recent_alerts": recent_items[: max(1, int(recent_limit))],
        "evidence_alerts": [
            item
            for item in recent_items
            if item.get("snapshot_path") or item.get("snapshot_url")
        ][: max(1, int(evidence_limit))],
        "visitor_evidence_summary": visitor_evidence_summary(visitor_records, limit=evidence_limit),
        "cameras": cameras,
    }


def build_reports_payload(
    alerts: list[dict[str, Any]],
    *,
    days: int = 30,
    preview_limit: int = 20,
    include_rows: bool = False,
    row_offset: int = 0,
    row_limit: int = 200,
    status_filters: set[str] | None = None,
    camera_filters: set[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(tz=UTC)
    filtered = filter_alerts(
        sort_alerts(alerts),
        date_from=date_floor(days, now=current),
        statuses=status_filters,
        camera_ids=camera_filters,
    )
    summary = summarize_alerts(filtered)
    total = len(filtered)
    offset = max(0, int(row_offset))
    capped_preview = max(0, min(int(preview_limit), 100))
    capped_row_limit = max(1, min(int(row_limit), 1000))
    preview_rows = filtered[:capped_preview]
    rows = filtered[offset : offset + capped_row_limit] if include_rows else preview_rows
    unique_people = len({str(item.get("employee_id") or item.get("person_name") or "unknown") for item in filtered}) if filtered else 0
    closure_rate = round((summary["closed"] / total) * 100, 2) if total else 0.0
    false_positive_rate = round((summary["false_positive"] / total) * 100, 2) if total else 0.0
    return {
        "generated_at": current.isoformat(),
        "window_days": max(1, int(days)),
        "metrics": {
            "alert_volume": total,
            "people_impacted": unique_people,
            "closure_rate": closure_rate,
            "open_cases": summary["pending"] + summary["assigned"],
            "false_positive_rate": false_positive_rate,
        },
        "daily_trend": daily_trend(filtered),
        "status_mix": status_mix(filtered),
        "department_ranking": department_ranking(filtered),
        "people_ranking": people_ranking(filtered),
        "identity_source_mix": identity_source_mix(filtered),
        "camera_ranking": camera_ranking(filtered),
        "applied_filters": {
            "statuses": sorted(status_filters or []),
            "camera_ids": sorted(camera_filters or []),
        },
        "preview_rows": preview_rows,
        "rows": rows,
        "rows_total": total,
        "rows_offset": offset if include_rows else 0,
        "rows_limit": capped_row_limit if include_rows else capped_preview,
        "rows_truncated": not include_rows and total > len(preview_rows),
    }


def load_raw_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def save_raw_config(config_path: Path, payload: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, config_path)


def upsert_runtime_camera(config_path: Path, camera_payload: dict[str, Any]) -> None:
    raw = load_raw_config(config_path)
    cameras = raw.setdefault("cameras", [])
    if not isinstance(cameras, list):
        cameras = []
        raw["cameras"] = cameras
    replaced = False
    for index, item in enumerate(cameras):
        if isinstance(item, dict) and item.get("camera_id") == camera_payload["camera_id"]:
            cameras[index] = camera_payload
            replaced = True
            break
    if not replaced:
        cameras.append(camera_payload)
    save_raw_config(config_path, raw)


def runtime_camera_source(config_path: Path, camera_id: str | None) -> str:
    if not camera_id or not config_path.exists():
        return ""
    raw = load_raw_config(config_path)
    for item in raw.get("cameras", []):
        if isinstance(item, dict) and item.get("camera_id") == camera_id:
            return str(item.get("source", "")).strip()
    return ""


def is_safe_camera_source_reference(value: str) -> bool:
    source = str(value).strip()
    if not source:
        return False
    if source.startswith("${") and source.endswith("}"):
        return True
    if source.startswith("env:"):
        return True
    if "://" in source:
        return False
    return True
