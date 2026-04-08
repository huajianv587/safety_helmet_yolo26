from __future__ import annotations

import html
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st


REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.notifier import NotificationService
from helmet_monitoring.services.operations import operations_paths
from helmet_monitoring.services.person_directory import PersonDirectory
from helmet_monitoring.services.workflow import AlertWorkflowService
from helmet_monitoring.storage.evidence_store import EvidenceStore
from helmet_monitoring.storage.repository import build_repository, parse_timestamp


UTC = timezone.utc
LANGUAGE_OPTIONS = {"zh": "中文", "en": "English"}
STATUS_LABELS = {
    "pending": {"zh": "待处理", "en": "Pending"},
    "confirmed": {"zh": "已确认", "en": "Confirmed"},
    "remediated": {"zh": "已整改", "en": "Remediated"},
    "false_positive": {"zh": "误报", "en": "False Positive"},
    "ignored": {"zh": "已忽略", "en": "Ignored"},
    "assigned": {"zh": "已转派", "en": "Assigned"},
}
IDENTITY_LABELS = {
    "resolved": {"zh": "已解析", "en": "Resolved"},
    "review_required": {"zh": "待复核", "en": "Review Required"},
    "unresolved": {"zh": "未识别", "en": "Unresolved"},
    "none": {"zh": "未启用", "en": "Disabled"},
}
ROLE_OPTIONS = {
    "admin": {"zh": "管理员", "en": "Admin"},
    "team_lead": {"zh": "班组长", "en": "Team Lead"},
    "safety_manager": {"zh": "安监负责人", "en": "Safety Manager"},
    "viewer": {"zh": "只读访客", "en": "Viewer"},
}
ROLE_PAGES = {
    "admin": ["总览", "人工复核台", "摄像头管理", "统计报表", "通知中心", "Hard Cases"],
    "safety_manager": ["总览", "人工复核台", "统计报表", "通知中心", "Hard Cases"],
    "team_lead": ["总览", "人工复核台", "统计报表"],
    "viewer": ["总览", "统计报表"],
}
PAGE_META = {
    "总览": {
        "kicker": "INDUSTRIAL SAFETY INTELLIGENCE",
        "title": "Safety Helmet Command Center",
        "description": "工业现场实时告警、身份识别、复核流转与治理闭环的一体化控制界面。",
        "nav": "Overview / 总览",
    },
    "人工复核台": {
        "kicker": "REVIEW WORKFLOW HUB",
        "title": "人工复核与处置工作台",
        "description": "围绕证据、身份、通知、处置动作的一站式工单操作面板。",
        "nav": "Review Desk / 人工复核台",
    },
    "摄像头管理": {
        "kicker": "CAMERA FABRIC CONTROL",
        "title": "摄像头编排与运行态势",
        "description": "统一维护设备接入、责任部门、默认识别人员与告警触达配置。",
        "nav": "Cameras / 摄像头管理",
    },
    "统计报表": {
        "kicker": "SAFETY ANALYTICS",
        "title": "统计报表与治理洞察",
        "description": "从部门、人员、状态、时间维度观察违章分布与闭环效率。",
        "nav": "Reports / 统计报表",
    },
    "通知中心": {
        "kicker": "NOTIFICATION ORCHESTRATION",
        "title": "通知中心与触达验证",
        "description": "统一查看发送记录、验证通知能力并保障闭环触达。",
        "nav": "Notifications / 通知中心",
    },
    "Hard Cases": {
        "kicker": "FEEDBACK LOOP",
        "title": "Hard Cases 回流池",
        "description": "沉淀误报与难例，为后续模型优化和策略升级提供输入。",
        "nav": "Hard Cases / 回流池",
    },
}

ROLE_LABELS = {
    "admin": {"zh": "管理员", "en": "Admin"},
    "team_lead": {"zh": "班组长", "en": "Team Lead"},
    "safety_manager": {"zh": "安监负责人", "en": "Safety Manager"},
    "viewer": {"zh": "只读访客", "en": "Viewer"},
}

PAGE_META_I18N = {
    "总览": {
        "kicker": {"zh": "工业安全智能中枢", "en": "INDUSTRIAL SAFETY INTELLIGENCE"},
        "title": {"zh": "工业安全总览", "en": "Safety Overview"},
        "description": {
            "zh": "工业现场实时告警、身份识别、复核流转与治理闭环的一体化控制界面。",
            "en": "A unified console for live alerts, identity resolution, review workflow, and safety governance.",
        },
        "nav": {"zh": "总览", "en": "Overview"},
    },
    "人工复核台": {
        "kicker": {"zh": "复核工作流", "en": "REVIEW WORKFLOW HUB"},
        "title": {"zh": "人工复核工作台", "en": "Review Desk"},
        "description": {
            "zh": "围绕证据、身份、通知与处置动作的一站式工单操作面板。",
            "en": "A single review desk for evidence, identity resolution, notifications, and case actions.",
        },
        "nav": {"zh": "人工复核台", "en": "Review Desk"},
    },
    "摄像头管理": {
        "kicker": {"zh": "摄像头编排", "en": "CAMERA FABRIC CONTROL"},
        "title": {"zh": "摄像头运行态势", "en": "Camera Fabric"},
        "description": {
            "zh": "统一维护设备接入、责任部门、默认识别人员与告警触达配置。",
            "en": "Manage device access, ownership, default identities, and alert delivery in one place.",
        },
        "nav": {"zh": "摄像头管理", "en": "Cameras"},
    },
    "统计报表": {
        "kicker": {"zh": "统计治理", "en": "SAFETY ANALYTICS"},
        "title": {"zh": "统计治理洞察", "en": "Reports & Insights"},
        "description": {
            "zh": "从部门、人员、状态与时间维度观察违章分布和闭环效率。",
            "en": "Observe violations and closure efficiency across departments, people, status, and time.",
        },
        "nav": {"zh": "统计报表", "en": "Reports"},
    },
    "通知中心": {
        "kicker": {"zh": "通知编排", "en": "NOTIFICATION ORCHESTRATION"},
        "title": {"zh": "通知中心验证", "en": "Notification Center"},
        "description": {
            "zh": "统一查看发送记录、验证通知能力并保障闭环触达。",
            "en": "Review delivery logs, verify channels, and keep notification loops reliable.",
        },
        "nav": {"zh": "通知中心", "en": "Notifications"},
    },
    "Hard Cases": {
        "kicker": {"zh": "反馈回流", "en": "FEEDBACK LOOP"},
        "title": {"zh": "Hard Cases 回流", "en": "Hard Cases"},
        "description": {
            "zh": "沉淀误报与难例，为后续模型优化和策略升级提供输入。",
            "en": "Capture hard cases and false positives to drive model and policy improvements.",
        },
        "nav": {"zh": "回流池", "en": "Hard Cases"},
    },
}


PAGE_META_RUNTIME_I18N = {
    "总览": {
        "kicker": "INDUSTRIAL SAFETY INTELLIGENCE",
        "title": {"zh": "工业安全总览", "en": "Safety Overview"},
        "description": {
            "zh": "面向实时告警、身份识别、复核流转与安全治理的一体化总览界面。",
            "en": "A unified console for live alerts, identity resolution, review workflow, and safety governance.",
        },
        "nav": {"zh": "总览", "en": "Overview"},
    },
    "人工复核台": {
        "kicker": "REVIEW WORKFLOW HUB",
        "title": {"zh": "人工复核台", "en": "Review Desk"},
        "description": {
            "zh": "围绕证据、身份、通知与处置动作的一站式人工复核工作台。",
            "en": "A single review desk for evidence, identity resolution, notifications, and case actions.",
        },
        "nav": {"zh": "人工复核台", "en": "Review Desk"},
    },
    "摄像头管理": {
        "kicker": "CAMERA FABRIC CONTROL",
        "title": {"zh": "摄像头运行态势", "en": "Camera Fabric"},
        "description": {
            "zh": "统一维护设备接入、责任归属、默认身份与告警触达配置。",
            "en": "Manage device access, ownership, default identities, and alert delivery in one place.",
        },
        "nav": {"zh": "摄像头管理", "en": "Cameras"},
    },
    "统计报表": {
        "kicker": "SAFETY ANALYTICS",
        "title": {"zh": "统计治理洞察", "en": "Reports & Insights"},
        "description": {
            "zh": "从部门、人员、状态与时间维度观察违章分布和闭环效率。",
            "en": "Observe violations and closure efficiency across departments, people, status, and time.",
        },
        "nav": {"zh": "统计报表", "en": "Reports"},
    },
    "通知中心": {
        "kicker": "NOTIFICATION ORCHESTRATION",
        "title": {"zh": "通知中心验证", "en": "Notification Center"},
        "description": {
            "zh": "统一查看发送记录、验证通知链路并保障闭环触达稳定性。",
            "en": "Review delivery logs, verify channels, and keep notification loops reliable.",
        },
        "nav": {"zh": "通知中心", "en": "Notifications"},
    },
    "Hard Cases": {
        "kicker": "FEEDBACK LOOP",
        "title": {"zh": "Hard Cases 回流", "en": "Hard Cases"},
        "description": {
            "zh": "沉淀误报与难例，为模型与规则优化提供持续输入。",
            "en": "Capture hard cases and false positives to drive model and policy improvements.",
        },
        "nav": {"zh": "回流池", "en": "Hard Cases"},
    },
}


def _start_of_day() -> datetime:
    now = datetime.now(tz=UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _display_optional_media(alert: dict, url_key: str, path_key: str) -> str | None:
    media_url = alert.get(url_key)
    if media_url:
        return str(media_url)
    media_path = alert.get(path_key)
    if not media_path:
        return None
    path = Path(media_path)
    if path.exists():
        return str(path)
    return None


def _safe_text(value: object, default: str = "--") -> str:
    if value is None or value == "":
        return default
    return html.escape(str(value))


def _txt(language: str, zh: str, en: str) -> str:
    return zh if language == "zh" else en


def _page_meta(page: str, language: str) -> dict[str, str]:
    meta = PAGE_META_RUNTIME_I18N[page]
    return {
        "kicker": meta["kicker"],
        "title": meta["title"][language],
        "description": meta["description"][language],
        "nav": meta["nav"][language],
    }


def _role_label(role: str, language: str) -> str:
    return ROLE_LABELS.get(role, ROLE_LABELS["viewer"])[language]


def _status_label(value: str | None, language: str = "zh") -> str:
    if not value:
        return _txt(language, "未知", "Unknown")
    label = STATUS_LABELS.get(value)
    if not label:
        return str(value)
    return label.get(language, label["zh"])


def _identity_label(value: str | None, language: str = "zh") -> str:
    if not value:
        return _txt(language, "未知", "Unknown")
    label = IDENTITY_LABELS.get(value)
    if not label:
        return str(value)
    return label.get(language, label["zh"])


def _camera_status_label(value: str | None, language: str = "zh") -> str:
    mapping = {
        "running": {"zh": "运行中", "en": "Running"},
        "healthy": {"zh": "健康", "en": "Healthy"},
        "configured": {"zh": "已配置", "en": "Configured"},
        "offline": {"zh": "离线", "en": "Offline"},
        "error": {"zh": "异常", "en": "Error"},
    }
    if not value:
        return _txt(language, "未知", "Unknown")
    label = mapping.get(value)
    if not label:
        return str(value)
    return label.get(language, label["zh"])


def _format_timestamp(value: str | None) -> str:
    parsed = parse_timestamp(value)
    if parsed == datetime.min.replace(tzinfo=UTC):
        return "--"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _format_confidence(value: object) -> str:
    if value is None or value == "":
        return "--"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if 0.0 <= numeric <= 1.0:
        return f"{numeric:.1%}"
    return f"{numeric:.2f}"


def _status_tone(value: str | None) -> str:
    if value in {"remediated", "confirmed"}:
        return "positive"
    if value in {"pending", "assigned"}:
        return "warning"
    if value == "false_positive":
        return "danger"
    return "neutral"


def _identity_tone(value: str | None) -> str:
    if value == "resolved":
        return "positive"
    if value == "review_required":
        return "warning"
    if value == "unresolved":
        return "danger"
    return "neutral"


def _camera_tone(camera: dict) -> str:
    status = str(camera.get("last_status") or "").lower()
    if status in {"running", "healthy"}:
        return "positive"
    if status in {"offline", "error"}:
        return "danger"
    if camera.get("last_seen_at"):
        return "warning"
    return "neutral"


def _camera_frame(cameras: list[dict]) -> pd.DataFrame:
    if not cameras:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "摄像头ID": item.get("camera_id"),
                "名称": item.get("camera_name"),
                "园区": item.get("site_name"),
                "楼栋": item.get("building_name"),
                "楼层": item.get("floor_name"),
                "车间": item.get("workshop_name"),
                "区域": item.get("zone_name"),
                "部门": item.get("department"),
                "状态": _camera_status_label(item.get("last_status")),
                "最后心跳": _format_timestamp(item.get("last_seen_at")),
                "FPS": item.get("last_fps") or "--",
                "重连次数": item.get("reconnect_count") or 0,
                "最近错误": item.get("last_error") or "--",
            }
            for item in cameras
        ]
    )


def _notification_status_label(value: str | None, language: str = "zh") -> str:
    mapping = {
        "sent": {"zh": "已发送", "en": "Sent"},
        "delivered": {"zh": "已送达", "en": "Delivered"},
        "queued": {"zh": "排队中", "en": "Queued"},
        "pending": {"zh": "待发送", "en": "Pending"},
        "skipped": {"zh": "已跳过", "en": "Skipped"},
        "failed": {"zh": "失败", "en": "Failed"},
        "error": {"zh": "异常", "en": "Error"},
    }
    if not value:
        return _txt(language, "未知", "Unknown")
    label = mapping.get(str(value).lower())
    if not label:
        return str(value)
    return label[language]


def _case_type_label(value: str | None, language: str = "zh") -> str:
    mapping = {
        "false_positive": {"zh": "误报", "en": "False Positive"},
        "hard_case": {"zh": "难例", "en": "Hard Case"},
        "review_required": {"zh": "待复核", "en": "Review Required"},
    }
    if not value:
        return _txt(language, "未标注", "Unlabeled")
    label = mapping.get(str(value).lower())
    if not label:
        return str(value)
    return label[language]


def _compact_path(value: object) -> str:
    if not value:
        return "--"
    text = str(value)
    if "://" in text:
        return text.rsplit("/", 1)[-1] or text
    try:
        return Path(text).name or text
    except OSError:
        return text


def _notification_frame(logs: list[dict], language: str) -> pd.DataFrame:
    if not logs:
        return pd.DataFrame()
    rows = []
    for item in logs:
        rows.append(
            {
                _txt(language, "发送时间", "Sent At"): _format_timestamp(
                    item.get("created_at") or item.get("sent_at") or item.get("updated_at")
                ),
                _txt(language, "事件编号", "Event No"): item.get("event_no") or item.get("alert_event_no") or "--",
                _txt(language, "接收对象", "Recipient"): item.get("recipient") or item.get("recipient_email") or item.get("to") or "--",
                _txt(language, "通道", "Channel"): item.get("channel") or item.get("type") or "email",
                _txt(language, "状态", "Status"): _notification_status_label(item.get("status") or item.get("result"), language),
                _txt(language, "说明", "Detail"): item.get("error") or item.get("message") or item.get("note") or "--",
            }
        )
    return pd.DataFrame(rows)


def _hard_cases_frame(cases: list[dict], language: str) -> pd.DataFrame:
    if not cases:
        return pd.DataFrame()
    rows = []
    for item in cases:
        rows.append(
            {
                _txt(language, "回流时间", "Captured At"): _format_timestamp(item.get("created_at")),
                _txt(language, "事件编号", "Event No"): item.get("event_no") or "--",
                _txt(language, "类型", "Case Type"): _case_type_label(item.get("case_type"), language),
                _txt(language, "摄像头", "Camera"): item.get("camera_name") or item.get("camera_id") or "--",
                _txt(language, "部门", "Department"): item.get("department") or "--",
                _txt(language, "证据", "Evidence"): _compact_path(item.get("snapshot_path") or item.get("snapshot_url")),
            }
        )
    return pd.DataFrame(rows)


def _load_monitor_runtime(settings) -> dict:
    status_path = operations_paths(settings)["monitor_health"]
    if not status_path.exists():
        return {}
    try:
        with status_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def _merge_live_cameras(settings, cameras: list[dict]) -> tuple[dict, list[dict]]:
    monitor_runtime = _load_monitor_runtime(settings)
    status_by_camera = {
        str(item.get("camera_id")): item
        for item in monitor_runtime.get("camera_statuses", [])
        if item.get("camera_id")
    }
    merged: list[dict] = []
    seen: set[str] = set()
    for item in cameras:
        camera_id = str(item.get("camera_id") or "")
        payload = dict(item)
        payload.update(status_by_camera.get(camera_id, {}))
        merged.append(payload)
        if camera_id:
            seen.add(camera_id)
    for camera_id, payload in status_by_camera.items():
        if camera_id in seen:
            continue
        merged.append(dict(payload))
    return monitor_runtime, merged


def _render_live_monitor(settings, cameras: list[dict]) -> None:
    monitor_runtime, live_cameras = _merge_live_cameras(settings, cameras)
    _section_header("LIVE MONITOR", "实时监控", "直接查看最新检测画面、运行状态和最近一次告警，不再只看状态表。")

    status_label = _camera_status_label(monitor_runtime.get("status"))
    processed_frames = str(monitor_runtime.get("processed_frames") or 0)
    latest_alert = str(monitor_runtime.get("last_alert_event_no") or "--")
    updated_at = _format_timestamp(monitor_runtime.get("updated_at"))
    _render_detail_cards(
        [
            ("监控状态", status_label, "当前监控 worker 的最新心跳状态"),
            ("已处理帧", processed_frames, "从本轮启动到现在累计处理的帧数"),
            ("最近告警", latest_alert, "最新一次落库的告警编号"),
            ("最后更新", updated_at, "监控心跳最近一次刷新时间"),
        ]
    )

    if monitor_runtime.get("status") == "running" and not monitor_runtime.get("last_alert_event_no"):
        st.info("监控在线，正在持续读流；当前还没有触发未戴安全帽告警。开启总览页自动刷新后，最新画面会持续更新。")
    elif not monitor_runtime:
        st.warning("暂时还没有拿到监控进程心跳，通常是 monitor 尚未启动或刚启动。")

    if not live_cameras:
        _render_empty_panel("当前没有可展示的实时监控画面。")
        return

    column_count = min(2, max(1, len(live_cameras)))
    columns = st.columns(column_count)
    for index, camera in enumerate(live_cameras):
        with columns[index % column_count]:
            camera_name = str(camera.get("camera_name") or camera.get("camera_id") or "Camera")
            camera_status = _camera_status_label(camera.get("status") or camera.get("last_status"))
            st.markdown(f"**{_safe_text(camera_name)}**")

            preview_path = camera.get("preview_path")
            preview_file = Path(preview_path) if preview_path else None
            if preview_file and preview_file.exists():
                st.image(str(preview_file), use_container_width=True)
            else:
                _render_empty_panel("最新预览帧还没有落盘，稍等几秒后会自动出现。")

            st.caption(
                " | ".join(
                    [
                        f"状态：{camera_status}",
                        f"FPS：{camera.get('last_fps') or '--'}",
                        f"更新时间：{_format_timestamp(camera.get('preview_updated_at') or monitor_runtime.get('updated_at'))}",
                    ]
                )
            )
            if camera.get("last_error"):
                st.warning(str(camera["last_error"]))


def _table_cell(value: object, *, emphasis: bool = False) -> str:
    class_name = "signal-table__cell signal-table__cell--emphasis" if emphasis else "signal-table__cell"
    return f"<td class='{class_name}'>{_safe_text(value)}</td>"


def _render_table_surface(
    frame: pd.DataFrame,
    *,
    empty_message: str,
    max_visible_rows: int | None = None,
    scroll_label: str | None = None,
) -> None:
    if frame.empty:
        _render_empty_panel(empty_message)
        return
    headers = "".join(f"<th>{html.escape(str(column))}</th>" for column in frame.columns)
    rows: list[str] = []
    for row in frame.itertuples(index=False, name=None):
        cells = [_table_cell(value, emphasis=index == 0) for index, value in enumerate(row)]
        rows.append(f"<tr>{''.join(cells)}</tr>")
    shell_classes = ["table-shell"]
    shell_style = ""
    shell_meta = ""
    if max_visible_rows:
        shell_classes.append("table-shell--scrollable")
        shell_style = f" style='--table-visible-rows:{max(1, int(max_visible_rows))};'"
        if scroll_label:
            shell_meta = f"<div class='table-shell__meta'>{html.escape(scroll_label)}</div>"
    st.markdown(
        (
            f"<div class='{' '.join(shell_classes)}'{shell_style}>"
            f"{shell_meta}"
            "<div class='table-shell__viewport'>"
            "<table class='signal-table'>"
            f"<thead><tr>{headers}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _feed_pill(label: str, value: object) -> str:
    return (
        "<span class='feed-pill'>"
        f"<span class='feed-pill__label'>{html.escape(label)}</span>"
        f"<span class='feed-pill__value'>{_safe_text(value)}</span>"
        "</span>"
    )


def _render_command_strip_panel(settings, alerts: list[dict], cameras: list[dict]) -> None:
    alert_summary = _alert_summary(alerts)
    camera_summary = _camera_summary(settings, cameras)
    total = alert_summary["total"]
    open_cases = alert_summary["pending"] + alert_summary["assigned"]
    resolved_rate = _safe_ratio(alert_summary["resolved_identity"], total)
    closure_rate = _safe_ratio(alert_summary["remediated"] + alert_summary["false_positive"], total)
    online_rate = _safe_ratio(camera_summary["reporting"], camera_summary["enabled"])
    review_pressure = _safe_ratio(alert_summary["review"], total)
    cards = [
        ("Identity Resolved", f"{resolved_rate:.0%}", "自动识别或人工确认完成的占比", resolved_rate),
        ("Closure Progress", f"{closure_rate:.0%}", "已整改与误报归档的综合进度", closure_rate),
        ("Device Online", f"{online_rate:.0%}", "最近 10 分钟有心跳的启用设备占比", online_rate),
        ("Review Pressure", str(open_cases if open_cases else alert_summary["review"]), "待处理与待复核案件的即时规模", review_pressure if total else 0.0),
    ]
    accents = ["cyan", "amber", "green", "red"]
    body: list[str] = []
    for index, (label, value, meta, progress) in enumerate(cards):
        width = max(6, min(100, round(progress * 100))) if progress > 0 else 6
        accent = accents[index % len(accents)]
        body.append(
            (
                f"<article class='brief-card brief-card--{accent}'>"
                "<div class='brief-topline'>"
                f"<div class='brief-label'>{html.escape(label)}</div>"
                f"<div class='brief-dot brief-dot--{accent}'></div>"
                "</div>"
                f"<div class='brief-value'>{html.escape(value)}</div>"
                f"<div class='brief-meta'>{html.escape(meta)}</div>"
                "<div class='brief-bar'>"
                f"<div class='brief-fill brief-fill--{accent}' style='width:{width}%;'></div>"
                "</div>"
                "</article>"
            )
        )
    st.markdown(f"<div class='brief-strip'>{''.join(body)}</div>", unsafe_allow_html=True)


def _render_live_monitor_panel(settings, cameras: list[dict]) -> None:
    monitor_runtime, live_cameras = _merge_live_cameras(settings, cameras)
    enabled_map = {camera.camera_id: camera.enabled for camera in settings.cameras}
    filtered_cameras = [
        camera
        for camera in live_cameras
        if enabled_map.get(str(camera.get("camera_id") or ""), True)
    ]

    def _preview_exists(camera: dict) -> bool:
        preview_path = camera.get("preview_path")
        return bool(preview_path and Path(preview_path).exists())

    filtered_cameras.sort(
        key=lambda camera: (
            0 if _preview_exists(camera) else 1,
            0 if str(camera.get("status") or camera.get("last_status") or "").lower() in {"running", "healthy"} else 1,
            str(camera.get("camera_name") or camera.get("camera_id") or ""),
        )
    )

    _section_header("LIVE MONITOR", "实时监控", "把在线画面、状态和最新错误汇成统一监控面板，而不是只看状态表。")
    status_label = _camera_status_label(monitor_runtime.get("status"))
    processed_frames = str(monitor_runtime.get("processed_frames") or 0)
    latest_alert = str(monitor_runtime.get("last_alert_event_no") or "--")
    updated_at = _format_timestamp(monitor_runtime.get("updated_at"))
    _render_detail_cards(
        [
            ("监控状态", status_label, "当前 monitor worker 的最新运行状态"),
            ("已处理帧", processed_frames, "从本轮启动到现在累计处理的帧数"),
            ("最近告警", latest_alert, "最近一次落库的告警编号"),
            ("最后更新", updated_at, "心跳最近一次刷新的时间"),
        ]
    )

    if monitor_runtime.get("status") == "running" and not monitor_runtime.get("last_alert_event_no"):
        st.info("监控在线，正在持续读流。当前还没有触发未戴安全帽告警，预览画面会随着自动刷新持续更新。")
    elif not monitor_runtime:
        st.warning("暂时还没有拿到监控进程心跳，通常是 monitor 尚未启动或刚启动。")

    if not filtered_cameras:
        _render_empty_panel("当前没有可展示的实时监控画面。")
        return

    column_count = min(2, max(1, len(filtered_cameras)))
    columns = st.columns(column_count)
    for index, camera in enumerate(filtered_cameras):
        with columns[index % column_count]:
            camera_name = str(camera.get("camera_name") or camera.get("camera_id") or "Camera")
            status_value = camera.get("status") or camera.get("last_status")
            status_label = _camera_status_label(status_value)
            status_tone = _camera_tone({"last_status": status_value, "last_seen_at": camera.get("last_seen_at")})
            location_text = " / ".join(
                str(part)
                for part in [
                    camera.get("site_name"),
                    camera.get("building_name"),
                    camera.get("floor_name"),
                    camera.get("zone_name"),
                ]
                if part
            ) or str(camera.get("camera_id") or "--")
            st.markdown(
                (
                    "<div class='camera-feed-head'>"
                    "<div>"
                    f"<div class='camera-feed-name'>{html.escape(camera_name)}</div>"
                    f"<div class='camera-feed-location'>{html.escape(location_text)}</div>"
                    "</div>"
                    f"{_status_chip(status_label, status_tone)}"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

            preview_path = camera.get("preview_path")
            preview_file = Path(preview_path) if preview_path else None
            if preview_file and preview_file.exists():
                st.image(str(preview_file), use_container_width=True)
            else:
                st.markdown(
                    (
                        "<div class='camera-placeholder'>"
                        "<div class='camera-placeholder__title'>Awaiting Live Preview</div>"
                        "<div class='camera-placeholder__meta'>监控已经接管该路设备，等下一帧预览落盘后会自动显示。</div>"
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )

            st.markdown(
                (
                    "<div class='camera-feed-meta'>"
                    f"{_feed_pill('Status', status_label)}"
                    f"{_feed_pill('FPS', camera.get('last_fps') or '--')}"
                    f"{_feed_pill('Updated', _format_timestamp(camera.get('preview_updated_at') or monitor_runtime.get('updated_at')))}"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            if camera.get("last_error"):
                st.markdown(
                    f"<div class='camera-feed-warning'>{html.escape(str(camera['last_error']))}</div>",
                    unsafe_allow_html=True,
                )


def _alerts_frame(alerts: list[dict]) -> pd.DataFrame:
    if not alerts:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "告警编号": _compact_identifier(alert.get("event_no")),
                "时间": _format_timestamp_compact(alert.get("created_at")),
                "摄像头": alert.get("camera_name", alert.get("camera_id")),
                "人员": alert.get("person_name", "Unknown"),
                "工号": alert.get("employee_id") or "--",
                "部门": alert.get("department") or "--",
                "工单状态": _status_label(alert.get("status")),
                "身份状态": _identity_label(alert.get("identity_status")),
                "识别来源": alert.get("identity_source") or "--",
                "识别置信度": _format_confidence(alert.get("identity_confidence")),
                "风险等级": alert.get("risk_level") or "--",
                "负责人": alert.get("assigned_to") or "--",
            }
            for alert in alerts
        ]
    )


def _load_raw_config(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_raw_config(config_path: Path, payload: dict) -> None:
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _upsert_runtime_camera(config_path: Path, camera_payload: dict) -> None:
    raw = _load_raw_config(config_path)
    cameras = raw.setdefault("cameras", [])
    replaced = False
    for index, item in enumerate(cameras):
        if item.get("camera_id") == camera_payload["camera_id"]:
            cameras[index] = camera_payload
            replaced = True
            break
    if not replaced:
        cameras.append(camera_payload)
    _save_raw_config(config_path, raw)


def _runtime_camera_source(config_path: Path, camera_id: str | None) -> str:
    if not camera_id or not config_path.exists():
        return ""
    raw = _load_raw_config(config_path)
    for item in raw.get("cameras", []):
        if item.get("camera_id") == camera_id:
            return str(item.get("source", "")).strip()
    return ""


def _is_safe_camera_source_reference(value: str) -> bool:
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


def _filter_alerts(
    alerts: list[dict],
    *,
    text_query: str = "",
    statuses: set[str] | None = None,
    departments: set[str] | None = None,
    camera_ids: set[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict]:
    results: list[dict] = []
    query = text_query.strip().lower()
    for alert in alerts:
        created_at = parse_timestamp(alert.get("created_at"))
        if statuses and alert.get("status") not in statuses:
            continue
        if departments and alert.get("department") not in departments:
            continue
        if camera_ids and alert.get("camera_id") not in camera_ids:
            continue
        if date_from and created_at < date_from:
            continue
        if date_to and created_at > date_to:
            continue
        haystack = " ".join(
            str(alert.get(key, ""))
            for key in [
                "event_no",
                "camera_name",
                "camera_id",
                "person_name",
                "employee_id",
                "department",
                "location",
                "assigned_to",
            ]
        ).lower()
        if query and query not in haystack:
            continue
        results.append(alert)
    return results


def _build_chart_theme() -> alt.ThemeConfig:
    axis = {
        "domain": False,
        "grid": True,
        "gridColor": "rgba(163, 190, 255, 0.12)",
        "gridDash": [4, 6],
        "labelColor": "#98A9C8",
        "labelFont": "IBM Plex Sans",
        "labelFontSize": 11,
        "tickColor": "rgba(163, 190, 255, 0.12)",
        "title": None,
    }
    return {
        "background": "transparent",
        "config": {
            "view": {"stroke": "transparent"},
            "axis": axis,
            "legend": {
                "labelColor": "#C7D6F2",
                "titleColor": "#E7F1FF",
                "labelFont": "IBM Plex Sans",
                "titleFont": "Space Grotesk",
            },
            "header": {"labelColor": "#E7F1FF", "titleColor": "#E7F1FF"},
            "range": {"category": ["#00E4FF", "#7CFFB2", "#FFAA3D", "#FF6E7F", "#7A95FF"]},
        },
    }


def _inject_theme() -> None:
    try:
        alt.themes.register("safety_helmet_console", _build_chart_theme)
    except ValueError:
        pass
    alt.themes.enable("safety_helmet_console")
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap');

        :root {
            --bg: #07101d;
            --panel: rgba(12, 22, 38, 0.82);
            --border: rgba(121, 156, 222, 0.18);
            --text: #ECF4FF;
            --muted: #9BAECC;
            --cyan: #00E4FF;
            --amber: #FFAA3D;
            --green: #7CFFB2;
            --red: #FF6E7F;
            --shadow: 0 24px 72px rgba(3, 9, 18, 0.52);
        }

        html, body, [class*="css"] {
            font-family: "IBM Plex Sans", sans-serif;
        }

        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at 18% 0%, rgba(0, 228, 255, 0.14), transparent 26%),
                radial-gradient(circle at 100% 0%, rgba(255, 170, 61, 0.10), transparent 24%),
                linear-gradient(180deg, #050B14 0%, #091220 36%, #07111C 100%);
            color: var(--text);
        }

        [data-testid="stHeader"] {
            background: rgba(4, 10, 20, 0.48);
            backdrop-filter: blur(14px);
        }

        [data-testid="stSidebar"] {
            background:
                linear-gradient(180deg, rgba(6, 13, 24, 0.98), rgba(8, 17, 30, 0.92)),
                radial-gradient(circle at top, rgba(0, 228, 255, 0.12), transparent 40%);
            border-right: 1px solid var(--border);
        }

        .block-container {
            max-width: 1520px;
            padding-top: 2rem;
            padding-bottom: 4rem;
        }

        .block-container::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background-image:
                linear-gradient(rgba(135, 156, 196, 0.05) 1px, transparent 1px),
                linear-gradient(90deg, rgba(135, 156, 196, 0.04) 1px, transparent 1px);
            background-size: 86px 86px;
            mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.6), transparent 92%);
        }

        h1, h2, h3, h4 {
            font-family: "Space Grotesk", sans-serif;
            color: var(--text);
            letter-spacing: -0.03em;
        }

        p, span, label, .stCaption, .stMarkdown {
            color: var(--muted);
        }

        .sidebar-brand {
            position: relative;
            margin-bottom: 1.15rem;
            padding: 1.05rem 1rem 1rem;
            border: 1px solid var(--border);
            border-radius: 22px;
            background:
                linear-gradient(180deg, rgba(13, 23, 39, 0.88), rgba(11, 18, 30, 0.96)),
                radial-gradient(circle at top right, rgba(0, 228, 255, 0.14), transparent 42%);
            box-shadow: var(--shadow);
            overflow: hidden;
        }

        .sidebar-kicker,
        .hero-kicker,
        .section-kicker {
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.75rem;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: #79E8FF;
        }

        .sidebar-title {
            margin-top: 0.45rem;
            font-family: "Space Grotesk", sans-serif;
            font-size: 1.45rem;
            font-weight: 700;
            color: var(--text);
        }

        .sidebar-copy {
            margin-top: 0.45rem;
            line-height: 1.55;
            font-size: 0.92rem;
        }

        .hero-shell {
            margin-bottom: 1rem;
            padding: 1.2rem 1.25rem;
            border: 1px solid var(--border);
            border-radius: 28px;
            background:
                linear-gradient(135deg, rgba(10, 19, 34, 0.95), rgba(15, 26, 44, 0.78)),
                radial-gradient(circle at 85% 15%, rgba(255, 170, 61, 0.18), transparent 22%);
            box-shadow: var(--shadow);
            position: relative;
            overflow: hidden;
        }

        .hero-shell::before {
            content: "";
            position: absolute;
            inset: 0;
            background:
                linear-gradient(90deg, rgba(0, 228, 255, 0.08) 1px, transparent 1px),
                linear-gradient(rgba(0, 228, 255, 0.05) 1px, transparent 1px);
            background-size: 48px 48px;
            opacity: 0.25;
            pointer-events: none;
        }

        .hero-grid {
            position: relative;
            display: grid;
            grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.95fr);
            gap: 1rem;
            align-items: start;
        }

        .hero-main {
            display: grid;
            gap: 0.7rem;
            align-content: start;
            max-width: 760px;
        }

        .hero-title {
            margin: 0.2rem 0 0.35rem;
            font-family: "Space Grotesk", sans-serif;
            font-size: clamp(1.58rem, 2.35vw, 2.28rem);
            line-height: 1.02;
            color: var(--text);
            letter-spacing: -0.045em;
            max-width: none;
            white-space: nowrap;
        }

        .hero-copy {
            max-width: 700px;
            font-size: 0.94rem;
            line-height: 1.58;
            color: #B2C4E4;
        }

        .pill-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin-top: 0.2rem;
        }

        .pill {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.42rem 0.72rem;
            border-radius: 999px;
            border: 1px solid var(--border);
            background: rgba(10, 19, 32, 0.72);
            color: #DCE9FF;
            font-size: 0.78rem;
            font-weight: 500;
        }

        .pill-positive { background: rgba(124, 255, 178, 0.18); border-color: rgba(124, 255, 178, 0.35); }
        .pill-warning { background: rgba(255, 170, 61, 0.18); border-color: rgba(255, 170, 61, 0.35); }
        .pill-danger { background: rgba(255, 110, 127, 0.18); border-color: rgba(255, 110, 127, 0.35); }

        .hero-board {
            position: relative;
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.7rem;
            padding: 0.85rem;
            border-radius: 24px;
            border: 1px solid rgba(121, 156, 222, 0.2);
            background: linear-gradient(180deg, rgba(9, 18, 31, 0.92), rgba(9, 17, 28, 0.7));
            align-content: start;
        }

        .board-topline {
            grid-column: 1 / -1;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.8rem;
            margin-bottom: 0;
        }

        .live-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            color: #D8EEFF;
            font-size: 0.78rem;
        }

        .live-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--green);
            box-shadow: 0 0 0 0 rgba(124, 255, 178, 0.45);
            animation: heroPulse 2s infinite;
        }

        @keyframes heroPulse {
            0% { box-shadow: 0 0 0 0 rgba(124, 255, 178, 0.45); }
            70% { box-shadow: 0 0 0 12px rgba(124, 255, 178, 0); }
            100% { box-shadow: 0 0 0 0 rgba(124, 255, 178, 0); }
        }

        .signal-item {
            min-height: 116px;
            padding: 0.72rem 0.78rem;
            border-radius: 18px;
            border: 1px solid var(--border);
            background: rgba(14, 24, 41, 0.68);
        }

        .signal-label { font-size: 0.78rem; letter-spacing: 0.04em; text-transform: uppercase; color: #8FB0D8; }
        .signal-value { margin-top: 0.18rem; font-family: "Space Grotesk", sans-serif; font-size: 1.2rem; font-weight: 700; color: var(--text); }
        .signal-note { margin-top: 0.22rem; font-size: 0.8rem; line-height: 1.45; color: #9DAFCA; }

        .section-head { margin: 0.4rem 0 0.9rem; }
        .section-title { margin: 0.4rem 0 0.25rem; font-size: 1.45rem; font-weight: 700; color: var(--text); }
        .section-copy { margin: 0; line-height: 1.65; color: #93A8CB; }

        .metric-card {
            min-height: 160px;
            padding: 1.1rem 1rem 1rem;
            border-radius: 22px;
            border: 1px solid var(--border);
            background: linear-gradient(180deg, rgba(13, 22, 37, 0.92), rgba(10, 18, 31, 0.76));
            box-shadow: var(--shadow);
        }

        .metric-card.neutral { box-shadow: inset 0 1px 0 rgba(0, 228, 255, 0.06), var(--shadow); }
        .metric-card.positive { box-shadow: inset 0 1px 0 rgba(124, 255, 178, 0.10), 0 18px 54px rgba(23, 91, 65, 0.16); }
        .metric-card.warning { box-shadow: inset 0 1px 0 rgba(255, 170, 61, 0.12), 0 18px 54px rgba(130, 73, 4, 0.16); }
        .metric-card.danger { box-shadow: inset 0 1px 0 rgba(255, 110, 127, 0.12), 0 18px 54px rgba(118, 31, 43, 0.18); }

        .metric-label { font-size: 0.86rem; letter-spacing: 0.06em; text-transform: uppercase; color: #9AB0D1; }
        .metric-value { margin-top: 0.55rem; font-family: "Space Grotesk", sans-serif; font-size: clamp(2rem, 3vw, 2.85rem); line-height: 1; color: var(--text); }
        .metric-note { margin-top: 0.65rem; font-size: 0.92rem; line-height: 1.55; color: #B7C8E4; }
        .metric-foot { margin-top: 0.85rem; font-family: "IBM Plex Mono", monospace; font-size: 0.78rem; color: #79E8FF; }

        .rank-stack, .detail-stack { display: flex; flex-direction: column; gap: 0.72rem; }

        .rank-card, .detail-card {
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 0.9rem;
            align-items: center;
            padding: 0.88rem 0.95rem;
            border-radius: 18px;
            border: 1px solid var(--border);
            background: rgba(12, 22, 38, 0.78);
        }

        .rank-index {
            width: 40px;
            height: 40px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 14px;
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.82rem;
            color: #78E6FF;
            background: rgba(0, 228, 255, 0.12);
        }

        .rank-name, .detail-key { color: var(--text); font-weight: 600; }
        .rank-meta, .detail-meta { margin-top: 0.12rem; font-size: 0.84rem; color: #92A4C3; }
        .rank-value, .detail-value { font-family: "Space Grotesk", sans-serif; font-size: 1.18rem; color: var(--text); }

        .detail-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 0.85rem;
            margin-bottom: 0.9rem;
        }

        .detail-card {
            grid-template-columns: auto 1fr;
            grid-template-areas:
                "index body"
                "value value";
            align-items: start;
            gap: 0.9rem;
            min-height: 148px;
            padding: 1rem 1rem 1.05rem;
            border-radius: 24px;
            background:
                linear-gradient(180deg, rgba(9, 18, 31, 0.95), rgba(11, 20, 35, 0.74)),
                radial-gradient(circle at top right, rgba(0, 228, 255, 0.10), transparent 42%);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04), var(--shadow);
            position: relative;
            overflow: hidden;
        }

        .detail-card::before {
            content: "";
            position: absolute;
            inset: 0 auto 0 0;
            width: 3px;
            background: linear-gradient(180deg, rgba(0, 228, 255, 0.95), rgba(30, 102, 255, 0.22));
        }

        .detail-card:nth-child(2)::before { background: linear-gradient(180deg, rgba(255, 170, 61, 0.95), rgba(255, 170, 61, 0.22)); }
        .detail-card:nth-child(3)::before { background: linear-gradient(180deg, rgba(124, 255, 178, 0.95), rgba(124, 255, 178, 0.22)); }
        .detail-card:nth-child(4)::before { background: linear-gradient(180deg, rgba(255, 110, 127, 0.95), rgba(255, 110, 127, 0.22)); }

        .detail-index {
            grid-area: index;
            width: 44px;
            height: 44px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 15px;
            background: rgba(0, 228, 255, 0.10);
            color: #8EEFFF;
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.84rem;
        }

        .detail-body { grid-area: body; }
        .detail-key { margin-top: 0.28rem; font-size: 1rem; font-weight: 600; }
        .detail-value { grid-area: value; font-size: clamp(1.6rem, 2.6vw, 2.45rem); line-height: 1; letter-spacing: -0.04em; }

        .empty-panel {
            padding: 1.25rem;
            border-radius: 20px;
            border: 1px dashed rgba(121, 156, 222, 0.25);
            background: rgba(12, 22, 38, 0.6);
            color: #A9BBDD;
            line-height: 1.7;
        }

        .evidence-caption {
            margin-top: 0.45rem;
            font-size: 0.83rem;
            color: #9CB2D6;
            line-height: 1.5;
        }

        .brief-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.8rem;
            margin-bottom: 1.35rem;
        }

        .brief-card {
            position: relative;
            overflow: hidden;
            min-height: 182px;
            padding: 1rem;
            border-radius: 24px;
            border: 1px solid var(--border);
            background:
                linear-gradient(180deg, rgba(10, 18, 31, 0.94), rgba(9, 17, 29, 0.76)),
                radial-gradient(circle at top right, rgba(0, 228, 255, 0.08), transparent 42%);
            box-shadow: var(--shadow);
        }

        .brief-card::before {
            content: "";
            position: absolute;
            inset: 0 auto auto 0;
            width: 100%;
            height: 2px;
            background: linear-gradient(90deg, rgba(0, 228, 255, 0.95), transparent 70%);
        }

        .brief-card--amber::before { background: linear-gradient(90deg, rgba(255, 170, 61, 0.95), transparent 70%); }
        .brief-card--green::before { background: linear-gradient(90deg, rgba(124, 255, 178, 0.95), transparent 70%); }
        .brief-card--red::before { background: linear-gradient(90deg, rgba(255, 110, 127, 0.95), transparent 70%); }

        .brief-topline {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.85rem;
        }

        .brief-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            box-shadow: 0 0 18px currentColor;
        }

        .brief-dot--cyan { color: #00E4FF; background: #00E4FF; }
        .brief-dot--amber { color: #FFAA3D; background: #FFAA3D; }
        .brief-dot--green { color: #7CFFB2; background: #7CFFB2; }
        .brief-dot--red { color: #FF6E7F; background: #FF6E7F; }

        .brief-label {
            font-size: 0.8rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #93ABD1;
        }

        .brief-value {
            margin-top: 0.45rem;
            font-family: "Space Grotesk", sans-serif;
            font-size: 1.7rem;
            color: var(--text);
        }

        .brief-meta {
            margin-top: 0.22rem;
            font-size: 0.84rem;
            color: #96A9C8;
        }

        .brief-bar {
            margin-top: 0.85rem;
            height: 8px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.05);
            overflow: hidden;
        }

        .brief-fill {
            height: 100%;
            border-radius: inherit;
            background: linear-gradient(90deg, rgba(0, 228, 255, 0.9), rgba(124, 255, 178, 0.85));
        }

        .brief-fill--cyan { background: linear-gradient(90deg, rgba(0, 228, 255, 0.95), rgba(52, 178, 255, 0.85)); }
        .brief-fill--amber { background: linear-gradient(90deg, rgba(255, 170, 61, 0.95), rgba(255, 120, 68, 0.88)); }
        .brief-fill--green { background: linear-gradient(90deg, rgba(124, 255, 178, 0.95), rgba(58, 210, 151, 0.88)); }
        .brief-fill--red { background: linear-gradient(90deg, rgba(255, 110, 127, 0.95), rgba(255, 82, 135, 0.88)); }

        .status-chip {
            display: inline-flex;
            align-items: center;
            padding: 0.36rem 0.75rem;
            border-radius: 999px;
            border: 1px solid var(--border);
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.03em;
            text-transform: uppercase;
        }

        .chip-positive { background: rgba(124, 255, 178, 0.16); border-color: rgba(124, 255, 178, 0.35); color: #DBFFEA; }
        .chip-warning { background: rgba(255, 170, 61, 0.16); border-color: rgba(255, 170, 61, 0.35); color: #FFE4BF; }
        .chip-danger { background: rgba(255, 110, 127, 0.16); border-color: rgba(255, 110, 127, 0.35); color: #FFD8DE; }
        .chip-neutral { background: rgba(0, 228, 255, 0.10); border-color: rgba(0, 228, 255, 0.24); color: #CFF9FF; }

        .chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.6rem;
            margin: 0.4rem 0 1rem;
        }

        .filter-shell {
            margin-bottom: 1rem;
            padding: 1rem 1rem 0.2rem;
            border-radius: 22px;
            border: 1px solid var(--border);
            background: rgba(11, 20, 35, 0.78);
            box-shadow: var(--shadow);
        }

        [data-testid="stForm"],
        [data-testid="stDataFrame"],
        [data-testid="stImage"],
        [data-testid="stVideo"],
        [data-testid="stFileUploader"] section {
            border-radius: 22px !important;
            border: 1px solid var(--border) !important;
            background: var(--panel) !important;
            box-shadow: var(--shadow) !important;
        }

        [data-testid="stForm"] { padding: 1rem 1rem 0.6rem; }

        [data-testid="stAlert"] {
            border-radius: 18px !important;
            border: 1px solid var(--border) !important;
            background: rgba(13, 23, 39, 0.78) !important;
        }

        [data-baseweb="select"] > div,
        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input,
        .stDateInput input {
            border-radius: 16px !important;
            border: 1px solid var(--border) !important;
            background: rgba(8, 15, 28, 0.92) !important;
            color: var(--text) !important;
        }

        .stButton button,
        .stDownloadButton button {
            border-radius: 16px !important;
            border: 1px solid rgba(0, 228, 255, 0.26) !important;
            background: linear-gradient(135deg, rgba(0, 228, 255, 0.18), rgba(30, 102, 255, 0.18)) !important;
            color: var(--text) !important;
            font-weight: 600 !important;
        }

        .stButton button[kind="primary"],
        .stFormSubmitButton button {
            border: 1px solid rgba(255, 170, 61, 0.32) !important;
            background: linear-gradient(135deg, rgba(255, 170, 61, 0.24), rgba(255, 132, 0, 0.18)) !important;
        }

        .platform-shell { padding: 1rem 0 0.2rem; }
        .platform-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.75rem; }
        .platform-card { padding: 0.95rem; border-radius: 18px; border: 1px solid var(--border); background: rgba(12, 22, 38, 0.72); }
        .platform-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: #8CA5CB; }
        .platform-value { margin-top: 0.38rem; line-height: 1.55; color: var(--text); word-break: break-word; }

        .table-shell {
            overflow-x: auto;
            border-radius: 24px;
            border: 1px solid var(--border);
            background:
                linear-gradient(180deg, rgba(10, 18, 31, 0.95), rgba(8, 15, 27, 0.82)),
                radial-gradient(circle at top right, rgba(0, 228, 255, 0.07), transparent 38%);
            box-shadow: var(--shadow);
        }

        .table-shell__meta {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            padding: 0.72rem 1rem 0.58rem;
            border-bottom: 1px solid rgba(121, 156, 222, 0.12);
            color: #89a7d6;
            font-size: 0.78rem;
            letter-spacing: 0.04em;
        }

        .table-shell__viewport {
            overflow-x: auto;
            overflow-y: visible;
        }

        .table-shell--scrollable .table-shell__viewport {
            max-height: calc(3.25rem + (5.8rem * var(--table-visible-rows, 5)));
            overflow-y: auto;
            scrollbar-width: thin;
            scrollbar-color: rgba(110, 209, 255, 0.72) rgba(9, 17, 30, 0.56);
        }

        .table-shell--scrollable .table-shell__viewport::-webkit-scrollbar {
            width: 10px;
            height: 10px;
        }

        .table-shell--scrollable .table-shell__viewport::-webkit-scrollbar-track {
            background: rgba(9, 17, 30, 0.76);
            border-left: 1px solid rgba(121, 156, 222, 0.12);
        }

        .table-shell--scrollable .table-shell__viewport::-webkit-scrollbar-thumb {
            background: linear-gradient(180deg, rgba(0, 228, 255, 0.78), rgba(53, 145, 255, 0.72));
            border-radius: 999px;
            border: 2px solid rgba(9, 17, 30, 0.82);
        }

        .signal-table {
            width: 100%;
            min-width: 760px;
            border-collapse: collapse;
        }

        .signal-table thead th {
            padding: 0.9rem 1rem;
            text-align: left;
            font-size: 0.79rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #8DB4E3;
            background: rgba(12, 22, 38, 0.96);
            border-bottom: 1px solid rgba(121, 156, 222, 0.16);
            white-space: nowrap;
            position: sticky;
            top: 0;
            z-index: 2;
        }

        .signal-table tbody tr:nth-child(odd) {
            background: rgba(255, 255, 255, 0.015);
        }

        .signal-table tbody tr:hover {
            background: rgba(0, 228, 255, 0.06);
        }

        .signal-table__cell {
            padding: 0.88rem 1rem;
            color: #DDE9FB;
            border-top: 1px solid rgba(121, 156, 222, 0.10);
            white-space: nowrap;
            vertical-align: top;
        }

        .signal-table__cell--emphasis {
            font-family: "IBM Plex Mono", monospace;
            color: #9CEEFF;
        }

        .camera-feed-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.8rem;
        }

        .camera-feed-name {
            font-family: "Space Grotesk", sans-serif;
            font-size: 1.18rem;
            font-weight: 700;
            color: var(--text);
        }

        .camera-feed-location {
            margin-top: 0.18rem;
            font-size: 0.84rem;
            color: #90A8CB;
        }

        .camera-placeholder {
            min-height: 320px;
            display: grid;
            place-items: center;
            padding: 1.4rem;
            border-radius: 24px;
            border: 1px dashed rgba(121, 156, 222, 0.28);
            background:
                linear-gradient(180deg, rgba(9, 18, 31, 0.92), rgba(10, 18, 31, 0.72)),
                radial-gradient(circle at center, rgba(0, 228, 255, 0.08), transparent 48%);
            text-align: center;
        }

        .camera-placeholder__title {
            font-family: "Space Grotesk", sans-serif;
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--text);
        }

        .camera-placeholder__meta {
            margin-top: 0.45rem;
            max-width: 420px;
            line-height: 1.65;
            color: #96ABD0;
        }

        .camera-feed-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            margin-top: 0.85rem;
            margin-bottom: 0.55rem;
        }

        .feed-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.45rem 0.72rem;
            border-radius: 999px;
            border: 1px solid rgba(121, 156, 222, 0.18);
            background: rgba(10, 18, 31, 0.74);
        }

        .feed-pill__label {
            font-size: 0.76rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #7EB3E8;
        }

        .feed-pill__value {
            font-size: 0.84rem;
            color: #E8F3FF;
        }

        .camera-feed-warning {
            padding: 0.85rem 0.95rem;
            border-radius: 18px;
            border: 1px solid rgba(255, 170, 61, 0.18);
            background: rgba(255, 170, 61, 0.08);
            color: #FFD8A6;
            line-height: 1.6;
        }

        [data-testid="stDataFrame"] [role="grid"] {
            border-radius: 20px !important;
            overflow: hidden !important;
            background: linear-gradient(180deg, rgba(11, 20, 35, 0.94), rgba(10, 18, 31, 0.84)) !important;
        }

        [data-testid="stDataFrame"] [role="columnheader"] {
            background: rgba(12, 22, 38, 0.96) !important;
            color: #93B7E6 !important;
            border-color: rgba(121, 156, 222, 0.12) !important;
        }

        [data-testid="stDataFrame"] [role="gridcell"] {
            background: transparent !important;
            color: #DCEAFF !important;
            border-color: rgba(121, 156, 222, 0.08) !important;
        }

        [data-testid="stImage"] img {
            border-radius: 24px !important;
            border: 1px solid rgba(121, 156, 222, 0.18) !important;
            box-shadow: 0 18px 56px rgba(3, 9, 18, 0.34) !important;
        }

        .streamlit-expanderHeader {
            border-radius: 16px !important;
            border: 1px solid var(--border) !important;
            background: rgba(11, 20, 35, 0.78) !important;
        }

        @media (max-width: 1200px) {
            .hero-grid { grid-template-columns: 1fr; }
            .hero-main { max-width: none; }
            .platform-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .brief-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }

        @media (max-width: 768px) {
            .block-container { padding-top: 1rem; }
            .hero-shell { padding: 1.2rem; }
            .hero-board { grid-template-columns: 1fr; }
            .board-topline { grid-column: auto; }
            .hero-title { max-width: none; font-size: clamp(1.7rem, 9vw, 2.35rem); white-space: normal; }
            .platform-grid { grid-template-columns: 1fr; }
            .brief-strip { grid-template-columns: 1fr; }
            .detail-grid { grid-template-columns: 1fr; }
            .signal-table { min-width: 620px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar_brand() -> None:
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-kicker">SAFETY OS / INDUSTRIAL EDITION</div>
            <div class="sidebar-title">工业安全控制台</div>
            <div class="sidebar-copy">
                面向现场管理、复核流转、设备编排、通知触达和数据治理的产品化工作界面。
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _pill(text: str, tone: str = "neutral") -> str:
    return f"<span class='pill pill-{tone}'>{html.escape(text)}</span>"


def _signal_item(label: str, value: str, note: str) -> str:
    return (
        "<div class='signal-item'>"
        f"<div class='signal-label'>{html.escape(label)}</div>"
        f"<div class='signal-value'>{html.escape(value)}</div>"
        f"<div class='signal-note'>{html.escape(note)}</div>"
        "</div>"
    )


def _section_header(kicker: str, title: str, description: str) -> None:
    st.markdown(
        f"""
        <div class="section-head">
            <div class="section-kicker">{html.escape(kicker)}</div>
            <div class="section-title">{html.escape(title)}</div>
            <p class="section-copy">{html.escape(description)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_metric_cards(cards: list[dict[str, str]]) -> None:
    columns = st.columns(len(cards))
    for column, card in zip(columns, cards):
        with column:
            st.markdown(
                f"""
                <div class="metric-card {card.get('tone', 'neutral')}">
                    <div class="metric-label">{html.escape(card['label'])}</div>
                    <div class="metric-value">{html.escape(card['value'])}</div>
                    <div class="metric-note">{html.escape(card['note'])}</div>
                    <div class="metric-foot">{html.escape(card.get('foot', ''))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _render_rank_list(
    items: list[tuple[str, str, str]],
    *,
    empty_message: str,
) -> None:
    if not items:
        _render_empty_panel(empty_message)
        return
    body = []
    for index, (name, meta, value) in enumerate(items, start=1):
        body.append(
            (
                f"<div class='rank-card'>"
                f"<div class='rank-index'>{index:02d}</div>"
                "<div>"
                f"<div class='rank-name'>{html.escape(name)}</div>"
                f"<div class='rank-meta'>{html.escape(meta)}</div>"
                "</div>"
                f"<div class='rank-value'>{html.escape(value)}</div>"
                "</div>"
            )
        )
    st.markdown(f"<div class='rank-stack'>{''.join(body)}</div>", unsafe_allow_html=True)


def _render_detail_cards(items: list[tuple[str, str, str]]) -> None:
    body = []
    for index, (key, value, meta) in enumerate(items, start=1):
        body.append(
            (
                "<article class='detail-card'>"
                f"<div class='detail-index'>{index:02d}</div>"
                "<div class='detail-body'>"
                f"<div class='detail-meta'>{html.escape(meta)}</div>"
                f"<div class='detail-key'>{html.escape(key)}</div>"
                "</div>"
                f"<div class='detail-value'>{html.escape(value)}</div>"
                "</article>"
            )
        )
    st.markdown(f"<div class='detail-grid'>{''.join(body)}</div>", unsafe_allow_html=True)


def _render_empty_panel(message: str) -> None:
    st.markdown(f"<div class='empty-panel'>{html.escape(message)}</div>", unsafe_allow_html=True)


def _status_chip(label: str, tone: str = "neutral") -> str:
    return f"<span class='status-chip chip-{tone}'>{html.escape(label)}</span>"


def _alert_summary(alerts: list[dict]) -> dict[str, int]:
    return {
        "total": len(alerts),
        "pending": sum(1 for item in alerts if item.get("status") == "pending"),
        "assigned": sum(1 for item in alerts if item.get("status") == "assigned"),
        "review": sum(1 for item in alerts if item.get("identity_status") in {"review_required", "unresolved"}),
        "resolved_identity": sum(1 for item in alerts if item.get("identity_status") == "resolved"),
        "remediated": sum(1 for item in alerts if item.get("status") == "remediated"),
        "false_positive": sum(1 for item in alerts if item.get("status") == "false_positive"),
    }


def _camera_summary(settings, cameras: list[dict]) -> dict[str, int]:
    cutoff = datetime.now(tz=UTC) - timedelta(minutes=10)
    configured = len(settings.cameras)
    enabled = sum(1 for item in settings.cameras if item.enabled)
    reporting = sum(1 for item in cameras if parse_timestamp(item.get("last_seen_at")) >= cutoff)
    abnormal = sum(1 for item in cameras if _camera_tone(item) == "danger")
    return {
        "configured": configured,
        "enabled": enabled,
        "reporting": reporting,
        "abnormal": abnormal,
    }


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _render_command_strip(settings, alerts: list[dict], cameras: list[dict]) -> None:
    alert_summary = _alert_summary(alerts)
    camera_summary = _camera_summary(settings, cameras)
    total = alert_summary["total"]
    open_cases = alert_summary["pending"] + alert_summary["assigned"]
    resolved_rate = _safe_ratio(alert_summary["resolved_identity"], total)
    closure_rate = _safe_ratio(alert_summary["remediated"] + alert_summary["false_positive"], total)
    online_rate = _safe_ratio(camera_summary["reporting"], camera_summary["enabled"])
    review_pressure = _safe_ratio(alert_summary["review"], total)
    cards = [
        ("身份解析率", f"{resolved_rate:.0%}", "自动识别或人工确认完成的占比", resolved_rate),
        ("工单闭环率", f"{closure_rate:.0%}", "已整改与误报归档的综合进度", closure_rate),
        ("设备在线率", f"{online_rate:.0%}", "最近 10 分钟有心跳的启用设备占比", online_rate),
        ("复核压力", str(open_cases if open_cases else alert_summary["review"]), "待处理与待复核案件的即时规模", review_pressure if total else 0.0),
    ]
    body = []
    for label, value, meta, progress in cards:
        width = max(6, min(100, round(progress * 100))) if progress > 0 else 6
        body.append(
            f"""
            <div class="brief-card">
                <div class="brief-label">{html.escape(label)}</div>
                <div class="brief-value">{html.escape(value)}</div>
                <div class="brief-meta">{html.escape(meta)}</div>
                <div class="brief-bar"><div class="brief-fill" style="width:{width}%;"></div></div>
            </div>
            """
        )
    st.markdown(f"<div class='brief-strip'>{''.join(body)}</div>", unsafe_allow_html=True)


def _render_page_hero(
    page: str,
    *,
    settings,
    repository,
    alerts: list[dict],
    cameras: list[dict],
    role: str,
    operator: str,
    auto_refresh: bool,
    refresh_seconds: int,
) -> None:
    meta = PAGE_META[page]
    alert_summary = _alert_summary(alerts)
    camera_summary = _camera_summary(settings, cameras)
    tags = [
        _pill(f"Backend {repository.backend_name.upper()}", "positive"),
        _pill(f"Role {ROLE_OPTIONS[role]}", "neutral"),
        _pill(f"Identity {settings.identity.provider}", "warning"),
        _pill("Email Ready" if settings.notifications.is_email_configured else "Email Pending", "positive" if settings.notifications.is_email_configured else "warning"),
        _pill(f"Auto Refresh {refresh_seconds}s" if auto_refresh else "Manual Refresh", "neutral"),
    ]
    board_items = [
        _signal_item("告警池", str(alert_summary["total"]), "当前筛选窗口内告警总量"),
        _signal_item("待处置", str(alert_summary["pending"] + alert_summary["assigned"]), "待处理与已转派工单"),
        _signal_item("身份已解析", str(alert_summary["resolved_identity"]), "已完成人员命中或人工确认"),
        _signal_item("上报摄像头", f"{camera_summary['reporting']} / {camera_summary['enabled']}", "最近 10 分钟内有心跳的启用设备"),
    ]
    st.markdown(
        f"""
        <section class="hero-shell">
            <div class="hero-grid">
                <div class="hero-main">
                    <div class="hero-kicker">{html.escape(meta['kicker'])}</div>
                    <div class="hero-title">{html.escape(meta['title'])}</div>
                    <div class="hero-copy">{html.escape(meta['description'])}</div>
                    <div class="pill-row">{''.join(tags)}</div>
                </div>
                <div class="hero-board">
                    <div class="board-topline">
                        <div class="live-chip"><span class="live-dot"></span><span>Operator {html.escape(operator)}</span></div>
                        <div class="pill">{html.escape(datetime.now().strftime('%Y-%m-%d %H:%M'))}</div>
                    </div>
                    {''.join(board_items)}
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _build_hourly_chart(alerts: list[dict]) -> alt.Chart | None:
    if not alerts:
        return None
    frame = pd.DataFrame(alerts)
    frame["created_at"] = frame["created_at"].apply(parse_timestamp)
    frame["hour"] = frame["created_at"].dt.strftime("%H:00")
    hourly = frame.groupby("hour").size().rename("alerts").reset_index()
    order = hourly["hour"].tolist()
    base = alt.Chart(hourly).encode(
        x=alt.X("hour:N", sort=order, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("alerts:Q"),
        tooltip=[alt.Tooltip("hour:N", title="时间"), alt.Tooltip("alerts:Q", title="告警数")],
    )
    area = base.mark_area(color="#00E4FF", opacity=0.12)
    line = base.mark_line(color="#6CEFFF", strokeWidth=3)
    points = base.mark_point(color="#FFAA3D", size=78, filled=True)
    return (area + line + points).properties(height=320)


def _build_daily_chart(report_df: pd.DataFrame) -> alt.Chart | None:
    if report_df.empty:
        return None
    daily = report_df.groupby(report_df["created_at_dt"].dt.strftime("%Y-%m-%d")).size().rename("alerts").reset_index()
    base = alt.Chart(daily).encode(
        x=alt.X("created_at_dt:N", title=None),
        y=alt.Y("alerts:Q", title=None),
        tooltip=[alt.Tooltip("created_at_dt:N", title="日期"), alt.Tooltip("alerts:Q", title="告警数")],
    )
    area = base.mark_area(color="#00E4FF", opacity=0.12)
    line = base.mark_line(color="#6CEFFF", strokeWidth=3)
    return (area + line).properties(height=300)


def _build_department_chart(report_df: pd.DataFrame, *, limit: int = 6, height: int = 280) -> alt.Chart | None:
    if report_df.empty or "department" not in report_df:
        return None
    ranking = (
        report_df.assign(department=report_df["department"].fillna("Unknown"))
        .groupby("department")
        .size()
        .rename("alerts")
        .reset_index()
        .sort_values("alerts", ascending=False)
        .head(limit)
    )
    return (
        alt.Chart(ranking)
        .mark_bar(cornerRadiusTopRight=8, cornerRadiusBottomRight=8)
        .encode(
            x=alt.X("alerts:Q", title=None),
            y=alt.Y("department:N", sort="-x", title=None),
            color=alt.value("#00E4FF"),
            tooltip=[alt.Tooltip("department:N", title="部门"), alt.Tooltip("alerts:Q", title="告警数")],
        )
        .properties(height=height)
    )


def _build_status_chart(report_df: pd.DataFrame) -> alt.Chart | None:
    if report_df.empty:
        return None
    status_dist = report_df.groupby("status").size().rename("alerts").reset_index()
    status_dist["status_label"] = status_dist["status"].map(_status_label)
    return (
        alt.Chart(status_dist)
        .mark_bar(cornerRadiusTopLeft=8, cornerRadiusTopRight=8)
        .encode(
            x=alt.X("status_label:N", sort=None),
            y=alt.Y("alerts:Q"),
            color=alt.Color("status_label:N", legend=None),
            tooltip=[alt.Tooltip("status_label:N", title="状态"), alt.Tooltip("alerts:Q", title="数量")],
        )
        .properties(height=300)
    )


def _render_platform_configuration(settings) -> None:
    config_items = [
        ("运行配置", str(settings.config_path)),
        ("模型路径", str(settings.resolve_path(settings.model.path))),
        ("追踪组件", settings.tracking.provider),
        ("身份提供方", settings.identity.provider),
        ("片段缓冲", f"{settings.clip.pre_seconds}s / {settings.clip.post_seconds}s"),
        ("私有桶策略", "启用" if settings.security.use_private_bucket else "未启用"),
    ]
    blocks = []
    for label, value in config_items:
        blocks.append(
            (
                "<div class='platform-card'>"
                f"<div class='platform-label'>{html.escape(label)}</div>"
                f"<div class='platform-value'>{html.escape(value)}</div>"
                "</div>"
            )
        )
    with st.expander("平台配置与运行参数", expanded=False):
        st.markdown(
            f"<div class='platform-shell'><div class='platform-grid'>{''.join(blocks)}</div></div>",
            unsafe_allow_html=True,
        )


def render_overview(settings, repository, alerts: list[dict], cameras: list[dict]) -> None:
    today = _start_of_day()
    todays_alerts = [item for item in alerts if parse_timestamp(item.get("created_at")) >= today]
    pending_count = sum(1 for item in todays_alerts if item.get("status") == "pending")
    review_count = sum(1 for item in todays_alerts if item.get("identity_status") in {"review_required", "unresolved"})
    remediated_count = sum(1 for item in todays_alerts if item.get("status") == "remediated")
    false_positive_count = sum(1 for item in todays_alerts if item.get("status") == "false_positive")
    resolved_identity = sum(1 for item in todays_alerts if item.get("identity_status") == "resolved")

    _section_header("REAL-TIME OPERATIONS", "运营概览", "围绕今日态势、热点部门、证据图谱和设备健康度进行统一调度。")
    _render_command_strip_panel(settings, todays_alerts, cameras)
    _render_metric_cards(
        [
            {"label": "今日告警", "value": str(len(todays_alerts)), "note": "当前自然日累计告警事件", "foot": "Today / Alerts", "tone": "neutral"},
            {"label": "待处理", "value": str(pending_count), "note": "尚未闭环的现场工单", "foot": "Pending Queue", "tone": "warning"},
            {"label": "待复核", "value": str(review_count), "note": "身份或证据需要人工确认", "foot": "Review Required", "tone": "warning"},
            {"label": "身份已解析", "value": str(resolved_identity), "note": "自动识别或人工确认完成", "foot": "Identity Resolved", "tone": "positive"},
            {"label": "误报", "value": str(false_positive_count), "note": "已判定为误报的事件数量", "foot": "False Positive", "tone": "danger" if false_positive_count else "neutral"},
        ]
    )

    trend_col, dept_col = st.columns((1.7, 1))
    with trend_col:
        _section_header("TREND ANALYTICS", "今日趋势", "按小时观察当前日期告警密度，便于判断班次和时段波动。")
        chart = _build_hourly_chart(todays_alerts)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        else:
            _render_empty_panel("今天还没有告警，系统当前处于相对平稳的生产窗口。")

    with dept_col:
        _section_header("HOTSPOT RANKING", "部门排行", "快速识别高风险部门和当前告警聚集区。")
        if todays_alerts:
            dept_df = pd.DataFrame(todays_alerts)
            dept_chart = _build_department_chart(dept_df, limit=5, height=200)
            if dept_chart is not None:
                st.altair_chart(dept_chart, use_container_width=True)
            ranking = (
                dept_df.assign(department=dept_df["department"].fillna("Unknown"))
                .groupby("department")
                .size()
                .rename("alerts")
                .sort_values(ascending=False)
            )
            rank_items = [(department, "今日告警量", f"{count}") for department, count in ranking.head(6).items()]
            _render_rank_list(rank_items, empty_message="暂无部门排行数据。")
        else:
            _render_empty_panel("暂无部门排行数据。")

    table_col, insight_col = st.columns((1.7, 1))
    with table_col:
        _section_header("TRIAGE QUEUE", "最近告警", "面向运营和管理角色的实时告警视图，支持快速进入后续复核。")
        alert_frame = _alerts_frame(alerts[:16])
        if not alert_frame.empty:
            alert_frame = alert_frame.iloc[:, :8]
        _render_table_surface(
            alert_frame,
            empty_message="当前还没有可展示的告警记录。",
            max_visible_rows=5,
            scroll_label="滚动播报：默认展示 5 行，拖拽右侧滚动条可查看更早告警。",
        )

    with insight_col:
        _section_header("CONTROL SIGNALS", "控制信号", "把关键治理信息压缩成便于管理层快速读取的态势卡片。")
        top_department = "--"
        if todays_alerts:
            department_frame = pd.DataFrame(todays_alerts)
            ranking = department_frame.groupby("department").size().sort_values(ascending=False)
            if not ranking.empty:
                top_department = str(ranking.index[0] or "Unknown")
        latest_event = alerts[0].get("event_no") if alerts else "--"
        _render_detail_cards(
            [
                ("已整改", str(remediated_count), "今日完成闭环的工单数量"),
                ("重点部门", top_department, "当前自然日内告警最集中的部门"),
                ("最新事件", str(latest_event or "--"), "当前时间线中的最近一条告警"),
                ("数据后端", repository.backend_name.upper(), "当前控制台正在读取的数据源"),
            ]
        )

    _render_live_monitor_panel(settings, cameras)

    evidence_col, camera_col = st.columns((1.25, 1))
    with evidence_col:
        _section_header("EVIDENCE MOSAIC", "证据墙", "以视觉化方式回看最近现场截图，方便快速判断真实场景。")
        if alerts:
            columns = st.columns(3)
            rendered = 0
            for alert in alerts[:9]:
                image_path = _display_optional_media(alert, "snapshot_url", "snapshot_path")
                if not image_path:
                    continue
                with columns[rendered % 3]:
                    st.image(image_path, use_container_width=True)
                    st.markdown(
                        f"<div class='evidence-caption'>{_safe_text(alert.get('camera_name'))}<br>{_safe_text(alert.get('event_no') or alert.get('alert_id'))}</div>",
                        unsafe_allow_html=True,
                    )
                rendered += 1
            if rendered == 0:
                _render_empty_panel("最近告警还没有可展示的快照证据。")
        else:
            _render_empty_panel("证据图会在告警生成后出现在这里。")

    with camera_col:
        _section_header("DEVICE HEALTH", "摄像头健康度", "结合心跳、错误与 FPS 观察当前设备接入质量。")
        camera_frame = _camera_frame(cameras)
        if camera_frame.empty:
            _render_empty_panel("当前还没有摄像头心跳数据。")
        else:
            camera_frame = camera_frame.iloc[:, [0, 1, 2, 3, 8, 9, 10, 12]]
            _render_table_surface(camera_frame, empty_message="当前还没有摄像头心跳数据。")


def render_review_desk(settings, repository, directory: PersonDirectory, evidence_store: EvidenceStore, operator: str, role: str, alerts: list[dict]) -> None:
    workflow = AlertWorkflowService(repository)
    _section_header("CASE OPERATIONS", "人工复核台", "围绕证据、身份、通知和处置动作构建统一的案件工作流。")

    if not alerts:
        _render_empty_panel("当前没有符合筛选条件的告警。")
        return

    summary = _alert_summary(alerts)
    _render_metric_cards(
        [
            {"label": "待办工单", "value": str(summary["pending"] + summary["assigned"]), "note": "当前筛选条件下仍需推进的案件数", "foot": "Actionable Cases", "tone": "warning"},
            {"label": "待身份复核", "value": str(summary["review"]), "note": "需要人工确认人员身份或证据链", "foot": "Identity Review", "tone": "warning"},
            {"label": "已识别人员", "value": str(summary["resolved_identity"]), "note": "当前筛选集合中已解析身份的案件", "foot": "Resolved Identity", "tone": "positive"},
            {"label": "已整改", "value": str(summary["remediated"]), "note": "本筛选窗口内已完成整改动作", "foot": "Closed Loop", "tone": "positive"},
        ]
    )

    selection_options = {
        f"{alert.get('event_no') or alert.get('alert_id')} | {_status_label(alert.get('status'))} | {alert.get('camera_name')} | {alert.get('person_name', 'Unknown')}": alert
        for alert in alerts
    }
    selected_label = st.selectbox("选择告警工单", list(selection_options.keys()))
    alert = selection_options[selected_label]

    left, right = st.columns((1.2, 1))
    with left:
        _section_header("EVIDENCE STACK", "现场证据", "优先查看现场截图、视频片段与人脸/工牌裁剪证据。")
        snapshot = _display_optional_media(alert, "snapshot_url", "snapshot_path")
        face_media = _display_optional_media(alert, "face_crop_url", "face_crop_path")
        badge_media = _display_optional_media(alert, "badge_crop_url", "badge_crop_path")
        clip_media = _display_optional_media(alert, "clip_url", "clip_path")
        if snapshot:
            st.image(snapshot, caption="现场截图", use_container_width=True)
        else:
            _render_empty_panel("当前工单还没有现场截图。")
        if clip_media:
            st.video(clip_media)
        media_cols = st.columns(2)
        with media_cols[0]:
            if face_media:
                st.image(face_media, caption="人脸证据", use_container_width=True)
            else:
                _render_empty_panel("暂无人脸裁剪证据。")
        with media_cols[1]:
            if badge_media:
                st.image(badge_media, caption="工牌证据", use_container_width=True)
            else:
                _render_empty_panel("暂无工牌裁剪证据。")

    with right:
        _section_header("CASE DOSSIER", "案件画像", "把工单关键信息压缩为便于值班人员快速决策的字段摘要。")
        st.markdown(
            f"""
            <div class="chip-row">
                {_status_chip(_status_label(alert.get("status")), _status_tone(alert.get("status")))}
                {_status_chip(_identity_label(alert.get("identity_status")), _identity_tone(alert.get("identity_status")))}
                {_status_chip(str(alert.get("camera_name") or alert.get("camera_id") or "--"), "neutral")}
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_detail_cards(
            [
                ("事件编号", str(alert.get("event_no") or alert.get("alert_id") or "--"), "工单或告警唯一编号"),
                ("工单状态", _status_label(alert.get("status")), "当前工单在闭环流程中的状态"),
                ("身份状态", _identity_label(alert.get("identity_status")), "自动识别或人工确认状态"),
                ("识别来源", str(alert.get("identity_source") or "--"), "来自人脸、工牌、人工复核或未识别"),
                ("识别置信度", _format_confidence(alert.get("identity_confidence")), "当前身份结论对应的置信度"),
                ("人员", str(alert.get("person_name", "Unknown")), "关联人员名称"),
                ("工号", str(alert.get("employee_id") or "--"), "若有工号则在这里展示"),
                ("部门", str(alert.get("department") or "--"), "用于责任归属与统计分析"),
                (
                    "位置",
                    f"{alert.get('site_name') or '--'} / {alert.get('building_name') or '--'} / {alert.get('floor_name') or '--'}",
                    "园区、楼栋、楼层的简化定位信息",
                ),
                ("时间", _format_timestamp(alert.get("created_at")), "事件写入系统的时间"),
            ]
        )
        if alert.get("review_note"):
            st.warning(alert["review_note"])
        if alert.get("governance_note"):
            st.info(alert["governance_note"])

    actions = repository.list_alert_actions(alert_id=alert["alert_id"], limit=100)
    notifications = repository.list_notification_logs(alert_id=alert["alert_id"], limit=100)
    history_col, notify_col = st.columns(2)
    with history_col:
        _section_header("WORKFLOW HISTORY", "处理记录", "查看每一步状态流转和人工处置动作。")
        st.dataframe(pd.DataFrame(actions) if actions else pd.DataFrame(), hide_index=True, use_container_width=True)
    with notify_col:
        _section_header("DELIVERY LOG", "通知记录", "查看邮件或其他消息触达情况。")
        st.dataframe(pd.DataFrame(notifications) if notifications else pd.DataFrame(), hide_index=True, use_container_width=True)

    people = directory.get_people()
    person_labels = {"不变更人员信息": None}
    for person in people:
        label = f"{person.get('name')} | {person.get('employee_id')} | {person.get('department')}"
        person_labels[label] = person

    if role == "viewer":
        st.info("当前角色为只读访客，可查看告警详情，但不能处理或转派。")
    else:
        assign_col, status_col = st.columns(2)
        with assign_col:
            _section_header("ASSIGNMENT", "转派", "将当前工单交给明确负责人，并同步记录备注信息。")
            with st.form("assign_form"):
                assignee = st.text_input("处理负责人")
                assignee_email = st.text_input("负责人邮箱")
                assign_note = st.text_area("转派备注")
                assign_submit = st.form_submit_button("提交转派")
            if assign_submit and assignee:
                workflow.assign(
                    alert,
                    actor=operator,
                    actor_role=role,
                    assignee=assignee,
                    assignee_email=assignee_email,
                    note=assign_note,
                )
                st.success("已完成转派。")
                st.rerun()

        with status_col:
            _section_header("CASE RESOLUTION", "状态流转", "完成状态更新、人员修正和整改证据上传。")
            with st.form("status_form"):
                new_status = st.selectbox(
                    "新状态",
                    options=list(STATUS_LABELS.keys()),
                    format_func=_status_label,
                    index=0,
                )
                corrected_person_label = st.selectbox("人工确认人员", list(person_labels.keys()))
                resolution_note = st.text_area("处理备注")
                remediation_file = st.file_uploader("整改截图", type=["png", "jpg", "jpeg"], accept_multiple_files=False)
                status_submit = st.form_submit_button("更新工单")
            if status_submit:
                remediation_path = None
                remediation_url = None
                if remediation_file is not None:
                    extension = Path(remediation_file.name).suffix or ".jpg"
                    remediation_path, remediation_url = evidence_store.save_bytes(
                        alert.get("camera_id") or "manual",
                        remediation_file.getvalue(),
                        f"{alert['alert_id']}_remediation",
                        datetime.now(tz=UTC),
                        category="remediation",
                        extension=extension,
                        content_type=remediation_file.type or "image/jpeg",
                    )
                corrected_identity = None
                selected_person = person_labels.get(corrected_person_label)
                if selected_person:
                    corrected_identity = {
                        "person_id": selected_person.get("person_id"),
                        "person_name": selected_person.get("name"),
                        "employee_id": selected_person.get("employee_id"),
                        "department": selected_person.get("department"),
                        "team": selected_person.get("team"),
                        "role": selected_person.get("role"),
                        "phone": selected_person.get("phone"),
                        "identity_status": "resolved",
                        "identity_source": "manual_review",
                    }
                workflow.update_status(
                    alert,
                    actor=operator,
                    actor_role=role,
                    new_status=new_status,
                    note=resolution_note,
                    corrected_identity=corrected_identity,
                    remediation_snapshot_path=remediation_path,
                    remediation_snapshot_url=remediation_url,
                )
                st.success("工单已更新。")
                st.rerun()


def render_camera_center(settings, repository, cameras: list[dict]) -> None:
    _section_header("DEVICE ORCHESTRATION", "摄像头管理", "统一观察设备在线态势，并维护运行配置。")
    summary = _camera_summary(settings, cameras)
    _render_metric_cards(
        [
            {"label": "已配置设备", "value": str(summary["configured"]), "note": "当前 runtime 中登记的摄像头总量", "foot": "Configured", "tone": "neutral"},
            {"label": "启用设备", "value": str(summary["enabled"]), "note": "实际参与监控任务的摄像头数量", "foot": "Enabled", "tone": "positive"},
            {"label": "活跃上报", "value": str(summary["reporting"]), "note": "最近 10 分钟内持续有心跳的设备", "foot": "Reporting", "tone": "positive" if summary["reporting"] else "warning"},
            {"label": "异常设备", "value": str(summary["abnormal"]), "note": "状态异常或离线的设备数量", "foot": "Abnormal", "tone": "danger" if summary["abnormal"] else "neutral"},
        ]
    )

    table_col, form_col = st.columns((1.3, 1))
    with table_col:
        _section_header("LIVE FABRIC", "设备总览", "从位置、部门、状态、FPS 与错误信息观察接入质量。")
        camera_table = _camera_frame(cameras)
        if not camera_table.empty:
            camera_table = camera_table.iloc[:, [0, 1, 2, 3, 4, 6, 8, 9, 10, 11]]
        _render_table_surface(camera_table, empty_message="当前还没有设备接入数据。")

    with form_col:
        _section_header("CONFIG EDITOR", "运行配置编辑", "针对单个摄像头维护接入源、位置、责任部门和默认人员。")
        existing_options = {"新建摄像头": None}
        for camera in settings.cameras:
            existing_options[f"{camera.camera_id} | {camera.camera_name}"] = camera
        selected = st.selectbox("配置对象", list(existing_options.keys()))
        current = existing_options[selected]

        with st.form("camera_form"):
            raw_source = _runtime_camera_source(settings.config_path, current.camera_id if current else None)
            source_default = raw_source if _is_safe_camera_source_reference(raw_source) else ("0" if current is None else "")
            camera_id = st.text_input("camera_id", value=current.camera_id if current else "")
            camera_name = st.text_input("camera_name", value=current.camera_name if current else "")
            source_ref = st.text_input(
                "source_ref",
                value=source_default,
                help="仅允许本地设备号/本地视频路径，或环境变量引用，如 ${HELMET_MONITOR_STREAM_URL:rtsp://example/live}。",
            )
            if current and raw_source and not _is_safe_camera_source_reference(raw_source):
                st.warning("当前远程源地址已隐藏。请改为环境变量占位符后再保存，避免把明文地址写回 runtime.json。")
            enabled = st.checkbox("enabled", value=current.enabled if current else True)
            location = st.text_input("location", value=current.location if current else "")
            department = st.text_input("department", value=current.department if current else "")
            site_name = st.text_input("site_name", value=current.site_name if current else "Default Site")
            building_name = st.text_input("building_name", value=current.building_name if current else "Main Building")
            floor_name = st.text_input("floor_name", value=current.floor_name if current else "Floor 1")
            workshop_name = st.text_input("workshop_name", value=current.workshop_name if current else "Workshop A")
            zone_name = st.text_input("zone_name", value=current.zone_name if current else "Zone A")
            responsible_department = st.text_input(
                "responsible_department",
                value=current.responsible_department if current else department,
            )
            alert_emails = st.text_input(
                "alert_emails",
                value=",".join(current.alert_emails) if current else "",
                help="多个邮箱用逗号分隔",
            )
            default_person_id = st.text_input("default_person_id", value=current.default_person_id if current else "")
            save_submit = st.form_submit_button("保存到运行配置")
    if save_submit and camera_id:
        source_value = source_ref.strip() or raw_source
        if not _is_safe_camera_source_reference(source_value):
            st.error("source_ref 仅支持本地设备号、本地视频路径，或环境变量引用。")
            return
        payload = {
            "camera_id": camera_id,
            "camera_name": camera_name or camera_id,
            "source": source_value,
            "enabled": enabled,
            "location": location or "Unknown",
            "department": department or "Unknown",
            "site_name": site_name,
            "building_name": building_name,
            "floor_name": floor_name,
            "workshop_name": workshop_name,
            "zone_name": zone_name,
            "responsible_department": responsible_department or department or "Unknown",
            "alert_emails": [item.strip() for item in alert_emails.split(",") if item.strip()],
            "default_person_id": default_person_id.strip(),
        }
        _upsert_runtime_camera(settings.config_path, payload)
        repository.upsert_camera(
            {
                **payload,
                "last_status": "configured",
                "last_seen_at": datetime.now(tz=UTC).isoformat(),
                "retry_count": 0,
                "reconnect_count": 0,
                "last_error": None,
                "last_frame_at": None,
                "last_fps": None,
            }
        )
        st.success("摄像头配置已写入 runtime.json，重启监控 worker 后生效。")
        st.rerun()


def render_reports(alerts: list[dict]) -> None:
    _section_header("DATA PRODUCTS", "统计报表", "从趋势、状态、部门和人员维度形成面向治理的可读报表。")
    if not alerts:
        _render_empty_panel("暂无报表数据。")
        return

    report_df = pd.DataFrame(alerts)
    report_df["created_at_dt"] = report_df["created_at"].apply(parse_timestamp)
    total_alerts = len(report_df)
    unique_people = report_df["employee_id"].fillna("unknown").nunique()
    closure_rate = float((report_df["status"].isin(["remediated", "ignored", "false_positive"])).mean() * 100)
    false_positive_rate = float((report_df["status"] == "false_positive").mean() * 100)
    open_queue = int((report_df["status"].isin(["pending", "assigned"])).sum())

    _render_metric_cards(
        [
            {"label": "告警总数", "value": str(total_alerts), "note": "当前筛选时间窗口内的告警事件总量", "foot": "Alert Volume", "tone": "neutral"},
            {"label": "涉及人数", "value": str(unique_people), "note": "去重后的人员数量，用于观察覆盖范围", "foot": "People Impacted", "tone": "positive"},
            {"label": "闭环率", "value": f"{closure_rate:.1f}%", "note": "已整改、已忽略与误报事件占比", "foot": "Closure Rate", "tone": "positive"},
            {"label": "待办工单", "value": str(open_queue), "note": "仍需推进的工单数量", "foot": "Open Cases", "tone": "warning"},
            {"label": "误报率", "value": f"{false_positive_rate:.1f}%", "note": "当前筛选窗口内误报占比", "foot": "False Positive Rate", "tone": "danger" if false_positive_rate else "neutral"},
        ]
    )

    chart_col, status_col = st.columns(2)
    with chart_col:
        _section_header("TREND CURVE", "每日趋势", "观察时间维度上的累计告警变化。")
        chart = _build_daily_chart(report_df)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        else:
            _render_empty_panel("暂无趋势数据。")
    with status_col:
        _section_header("STATUS MIX", "状态分布", "观察工单处置状态结构，评估治理节奏。")
        chart = _build_status_chart(report_df)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        else:
            _render_empty_panel("暂无状态分布数据。")

    ranking_col, people_col = st.columns(2)
    with ranking_col:
        _section_header("DEPARTMENT HOTSPOTS", "部门排行", "识别最需要治理关注的部门。")
        dept_rank = (
            report_df.assign(department=report_df["department"].fillna("Unknown"))
            .groupby("department")
            .size()
            .rename("alerts")
            .sort_values(ascending=False)
        )
        items = [(name, "累计告警量", str(count)) for name, count in dept_rank.head(8).items()]
        _render_rank_list(items, empty_message="暂无部门排行数据。")
    with people_col:
        _section_header("PEOPLE HOTSPOTS", "人员违规 Top10", "辅助识别高频出现在告警中的重点人员。")
        person_rank = (
            report_df.assign(person_name=report_df["person_name"].fillna("Unknown"), employee_id=report_df["employee_id"].fillna("--"))
            .groupby(["person_name", "employee_id"])
            .size()
            .rename("alerts")
            .sort_values(ascending=False)
            .head(10)
        )
        items = [(f"{name} / {employee_id}", "累计告警量", str(count)) for (name, employee_id), count in person_rank.items()]
        _render_rank_list(items, empty_message="暂无人员排行数据。")

    export_df = report_df[
        [
            "event_no",
            "created_at",
            "camera_name",
            "person_name",
            "employee_id",
            "department",
            "status",
            "identity_status",
            "risk_level",
            "assigned_to",
            "handled_by",
        ]
    ]
    _section_header("EXPORT CENTER", "报表导出", "导出当前筛选结果用于外部汇报、归档或进一步分析。")
    st.download_button(
        "导出 CSV",
        data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="safety_alert_report.csv",
        mime="text/csv",
    )


def render_notification_center(settings, repository, notifier: NotificationService) -> None:
    _section_header("DELIVERY INFRA", "通知中心", "在统一工作台中查看发送记录并验证邮件通知能力。")
    logs = repository.list_notification_logs(limit=200)
    log_col, form_col = st.columns((1.35, 1))
    with log_col:
        _section_header("DELIVERY TIMELINE", "通知记录", "用于核对工单触达、通知状态和失败原因。")
        st.dataframe(pd.DataFrame(logs) if logs else pd.DataFrame(), hide_index=True, use_container_width=True)
    with form_col:
        _section_header("CHANNEL TEST", "测试邮件", "通过测试邮件快速验证 SMTP 与通知链路。")
        with st.form("test_email_form"):
            recipient = st.text_input("测试邮箱")
            subject = st.text_input("主题", value="Safety Helmet System Test")
            body = st.text_area("正文", value="This is a test email from the Safety Helmet Detection System.")
            submit = st.form_submit_button("发送测试邮件")
        if submit and recipient:
            result = notifier.send_test_email(recipient, subject, body)
            if result == "sent":
                st.success("测试邮件发送成功。")
            else:
                st.error(f"测试邮件发送失败：{result}")
        if not settings.notifications.is_email_configured:
            st.warning("当前 SMTP 还没有配置完整，通知记录会以 skipped 的形式落库。")


def render_hard_cases(repository) -> None:
    _section_header("MODEL FEEDBACK", "Hard Cases 回流", "沉淀误报和难例，为后续模型与规则优化提供输入。")
    cases = repository.list_hard_cases(limit=200)
    if not cases:
        _render_empty_panel("还没有 hard cases。把工单标记为误报后会自动进入这里。")
        return
    case_df = pd.DataFrame(cases)
    _render_metric_cards(
        [
            {"label": "回流总量", "value": str(len(case_df)), "note": "当前 hard cases 数据池中的样本总数", "foot": "Cases", "tone": "neutral"},
            {"label": "涉及摄像头", "value": str(case_df['camera_id'].fillna('unknown').nunique()) if "camera_id" in case_df else "0", "note": "难例覆盖的摄像头数量", "foot": "Coverage", "tone": "positive"},
            {"label": "最近 7 天", "value": str(sum(parse_timestamp(item.get('created_at')) >= datetime.now(tz=UTC) - timedelta(days=7) for item in cases)), "note": "近 7 天新增的 hard cases 数量", "foot": "Recent Cases", "tone": "warning"},
        ]
    )
    st.dataframe(case_df, hide_index=True, use_container_width=True)


def main() -> None:
    st.set_page_config(
        page_title="Safety Helmet Command Center",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_theme()

    settings = load_settings()
    repository = build_repository(settings)
    directory = PersonDirectory(settings)
    evidence_store = EvidenceStore(settings)
    notifier = NotificationService(settings, repository)

    _render_sidebar_brand()
    role = st.sidebar.selectbox(
        "当前角色",
        list(ROLE_OPTIONS.keys()),
        format_func=lambda value: f"{ROLE_OPTIONS[value]} / {value}",
    )
    operator = st.sidebar.text_input("当前操作人", value="demo.operator")
    allowed_pages = ROLE_PAGES[role]
    page = st.sidebar.radio("页面", allowed_pages, format_func=lambda value: PAGE_META[value]["nav"])
    auto_refresh = st.sidebar.checkbox("自动刷新", value=page == "总览")
    refresh_seconds = st.sidebar.slider("刷新秒数", min_value=5, max_value=60, value=10, step=5)

    since_days = st.sidebar.slider("筛选最近天数", min_value=1, max_value=30, value=7)
    all_cameras = repository.list_cameras()
    all_alerts = sorted(repository.list_alerts(limit=1000), key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)
    filtered_alerts = _filter_alerts(
        all_alerts,
        date_from=datetime.now(tz=UTC) - timedelta(days=since_days),
    )

    st.sidebar.markdown(
        f"""
        <div class="sidebar-brand" style="padding-top:0.95rem;">
            <div class="sidebar-kicker">SYSTEM STATUS</div>
            <div class="sidebar-copy">
                后端：<strong>{html.escape(repository.backend_name.upper())}</strong><br>
                通知：<strong>{'已配置' if settings.notifications.is_email_configured else '未配置'}</strong><br>
                身份：<strong>{html.escape(settings.identity.provider)}</strong><br>
                时间窗口：<strong>最近 {since_days} 天</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_page_hero(
        page,
        settings=settings,
        repository=repository,
        alerts=filtered_alerts,
        cameras=all_cameras,
        role=role,
        operator=operator,
        auto_refresh=auto_refresh,
        refresh_seconds=refresh_seconds,
    )

    if page == "总览":
        render_overview(settings, repository, filtered_alerts, all_cameras)
    elif page == "人工复核台":
        _section_header("FILTER CONSOLE", "筛选控制台", "按人员、部门、工单状态和摄像头快速筛选待处理案件。")
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            text_query = st.text_input("搜索事件/人员/部门/摄像头")
        with filter_col2:
            status_filter = st.multiselect("状态", list(STATUS_LABELS.keys()), default=list(STATUS_LABELS.keys()), format_func=_status_label)
        with filter_col3:
            department_options = sorted({item.get("department") for item in filtered_alerts if item.get("department")})
            department_filter = st.multiselect("部门", department_options, default=department_options)
        review_alerts = _filter_alerts(
            filtered_alerts,
            text_query=text_query,
            statuses=set(status_filter),
            departments=set(department_filter) if department_filter else None,
        )
        render_review_desk(settings, repository, directory, evidence_store, operator, role, review_alerts)
    elif page == "摄像头管理":
        render_camera_center(settings, repository, all_cameras)
    elif page == "统计报表":
        render_reports(filtered_alerts)
    elif page == "通知中心":
        render_notification_center(settings, repository, notifier)
    elif page == "Hard Cases":
        render_hard_cases(repository)

    _render_platform_configuration(settings)

    if auto_refresh and page == "总览":
        time.sleep(refresh_seconds)
        st.rerun()

def _render_sidebar_brand(language: str) -> None:
    st.sidebar.markdown(
        f"""
        <div class="sidebar-brand">
            <div class="sidebar-kicker">{html.escape(_txt(language, "SAFETY OS / 工业版", "SAFETY OS / INDUSTRIAL EDITION"))}</div>
            <div class="sidebar-title">{html.escape(_txt(language, "工业安全控制台", "Safety Helmet Console"))}</div>
            <div class="sidebar-copy">
                {html.escape(_txt(language, "面向现场管理、复核流转、设备编排与通知触达的一体化安全作业界面。", "A unified console for field operations, review workflow, camera orchestration, and notification delivery."))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_page_hero(
    page: str,
    *,
    settings,
    repository,
    alerts: list[dict],
    cameras: list[dict],
    role: str,
    operator: str,
    auto_refresh: bool,
    refresh_seconds: int,
    language: str,
) -> None:
    meta = _page_meta(page, language)
    alert_summary = _alert_summary(alerts)
    camera_summary = _camera_summary(settings, cameras)
    tags = [
        _pill(f"{_txt(language, '后端', 'Backend')} {repository.backend_name.upper()}", "positive"),
        _pill(f"{_txt(language, '角色', 'Role')} {_role_label(role, language)}", "neutral"),
        _pill(f"{_txt(language, '身份', 'Identity')} {settings.identity.provider}", "warning"),
        _pill(
            _txt(language, "邮件已就绪", "Email Ready")
            if settings.notifications.is_email_configured
            else _txt(language, "邮件待配置", "Email Pending"),
            "positive" if settings.notifications.is_email_configured else "warning",
        ),
        _pill(
            f"{_txt(language, '自动刷新', 'Auto Refresh')} {refresh_seconds}s"
            if auto_refresh
            else _txt(language, "手动刷新", "Manual Refresh"),
            "neutral",
        ),
    ]
    board_items = [
        _signal_item(
            _txt(language, "告警池", "Alert Pool"),
            str(alert_summary["total"]),
            _txt(language, "当前筛选窗口内告警总量", "Total alerts within the current filter window"),
        ),
        _signal_item(
            _txt(language, "待处置", "Pending"),
            str(alert_summary["pending"] + alert_summary["assigned"]),
            _txt(language, "待处理与已转派工单", "Cases waiting for handling or already assigned"),
        ),
        _signal_item(
            _txt(language, "身份已解析", "Resolved Identity"),
            str(alert_summary["resolved_identity"]),
            _txt(language, "已完成人员命中或人工确认", "Matched or manually confirmed people"),
        ),
        _signal_item(
            _txt(language, "上报摄像头", "Reporting Cameras"),
            f"{camera_summary['reporting']} / {camera_summary['enabled']}",
            _txt(language, "最近 10 分钟内有心跳的启用设备", "Enabled devices reporting heartbeats in the last 10 minutes"),
        ),
    ]
    st.markdown(
        f"""
        <section class="hero-shell">
            <div class="hero-grid">
                <div class="hero-main">
                    <div class="hero-kicker">{html.escape(meta['kicker'])}</div>
                    <div class="hero-title">{html.escape(meta['title'])}</div>
                    <div class="hero-copy">{html.escape(meta['description'])}</div>
                    <div class="pill-row">{''.join(tags)}</div>
                </div>
                <div class="hero-board">
                    <div class="board-topline">
                        <div class="live-chip"><span class="live-dot"></span><span>{html.escape(_txt(language, '操作员', 'Operator'))} {html.escape(operator)}</span></div>
                        <div class="pill">{html.escape(datetime.now().strftime('%Y-%m-%d %H:%M'))}</div>
                    </div>
                    {''.join(board_items)}
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_notification_center(settings, repository, notifier: NotificationService, language: str = "zh") -> None:
    _section_header(
        _txt(language, "通知基础设施", "DELIVERY INFRA"),
        _txt(language, "通知中心", "Notification Center"),
        _txt(language, "在统一工作台中查看发送记录并验证邮件通知能力。", "Review delivery logs and verify outbound email capability in one place."),
    )
    logs = repository.list_notification_logs(limit=200)
    log_col, form_col = st.columns((1.5, 0.95))
    with log_col:
        _section_header(
            _txt(language, "通知时间线", "DELIVERY TIMELINE"),
            _txt(language, "通知记录", "Delivery Logs"),
            _txt(language, "把关键字段压缩成可读表，方便核对触达状态与失败原因。", "A condensed log view for delivery state, recipients, and failure reasons."),
        )
        _render_table_surface(
            _notification_frame(logs, language),
            empty_message=_txt(language, "当前还没有通知记录。", "No notification logs available yet."),
        )
    with form_col:
        _section_header(
            _txt(language, "通道验证", "CHANNEL TEST"),
            _txt(language, "测试邮件", "Email Test"),
            _txt(language, "通过测试邮件快速验证 SMTP 与通知链路。", "Send a quick email test to verify the SMTP and delivery path."),
        )
        _render_detail_cards(
            [
                (
                    _txt(language, "SMTP 状态", "SMTP Status"),
                    _txt(language, "已配置", "Configured") if settings.notifications.is_email_configured else _txt(language, "未配置", "Pending"),
                    _txt(language, "当前邮件通道的配置完成情况", "Current readiness of the outbound email channel"),
                ),
                (
                    _txt(language, "通知通道", "Channel"),
                    _txt(language, "邮件", "Email"),
                    _txt(language, "当前测试入口默认使用的发送通道", "The delivery channel used by the current test form"),
                ),
                (
                    _txt(language, "最近事件", "Latest Event"),
                    str(logs[0].get("event_no") or "--") if logs else "--",
                    _txt(language, "最近一条通知记录关联的事件编号", "Event number associated with the latest notification log"),
                ),
            ]
        )
        with st.form("test_email_form"):
            recipient = st.text_input(_txt(language, "测试邮箱", "Recipient Email"))
            subject = st.text_input(_txt(language, "主题", "Subject"), value=_txt(language, "安全帽系统测试邮件", "Safety Helmet System Test"))
            body = st.text_area(
                _txt(language, "正文", "Message"),
                value=_txt(language, "这是一封来自工业安全监控平台的测试邮件。", "This is a test email from the Safety Helmet Detection System."),
            )
            submit = st.form_submit_button(_txt(language, "发送测试邮件", "Send Test Email"))
        if submit and recipient:
            result = notifier.send_test_email(recipient, subject, body)
            if result == "sent":
                st.success(_txt(language, "测试邮件发送成功。", "Test email sent successfully."))
            else:
                st.error(f"{_txt(language, '测试邮件发送失败：', 'Test email failed: ')}{result}")
        if not settings.notifications.is_email_configured:
            st.warning(
                _txt(
                    language,
                    "当前 SMTP 还没有配置完整，通知记录会以 skipped 的形式落库。",
                    "SMTP is not fully configured yet, so notification logs may be recorded as skipped.",
                )
            )


def render_hard_cases(repository, language: str = "zh") -> None:
    _section_header(
        _txt(language, "模型反馈", "MODEL FEEDBACK"),
        _txt(language, "Hard Cases 回流", "Hard Cases"),
        _txt(language, "沉淀误报和难例，为后续模型与规则优化提供输入。", "Capture false positives and edge cases for future model and policy improvements."),
    )
    cases = repository.list_hard_cases(limit=200)
    if not cases:
        _render_empty_panel(_txt(language, "还没有 hard cases。把工单标记为误报后会自动进入这里。", "No hard cases yet. Marking an alert as false positive will send it here automatically."))
        return
    case_df = pd.DataFrame(cases)
    _render_metric_cards(
        [
            {
                "label": _txt(language, "回流总量", "Cases"),
                "value": str(len(case_df)),
                "note": _txt(language, "当前 hard cases 数据池中的样本总数", "Total samples currently stored in the hard-cases pool"),
                "foot": _txt(language, "样本总量", "Cases"),
                "tone": "neutral",
            },
            {
                "label": _txt(language, "涉及摄像头", "Camera Coverage"),
                "value": str(case_df["camera_id"].fillna("unknown").nunique()) if "camera_id" in case_df else "0",
                "note": _txt(language, "难例覆盖的摄像头数量", "Number of cameras represented in the hard-cases pool"),
                "foot": _txt(language, "覆盖范围", "Coverage"),
                "tone": "positive",
            },
            {
                "label": _txt(language, "最近 7 天", "Last 7 Days"),
                "value": str(sum(parse_timestamp(item.get("created_at")) >= datetime.now(tz=UTC) - timedelta(days=7) for item in cases)),
                "note": _txt(language, "近 7 天新增的 hard cases 数量", "New hard cases added during the past seven days"),
                "foot": _txt(language, "近期开样", "Recent Cases"),
                "tone": "warning",
            },
        ]
    )
    _section_header(
        _txt(language, "案例清单", "CASE INVENTORY"),
        _txt(language, "回流样本表", "Case Table"),
        _txt(language, "保留核心字段，避免长路径和原始主键把阅读空间撑满。", "Only the key columns are kept so long paths and raw ids do not dominate the layout."),
    )
    _render_table_surface(
        _hard_cases_frame(cases, language),
        empty_message=_txt(language, "当前没有可展示的回流样本。", "No hard cases available to display."),
    )


def main() -> None:
    st.set_page_config(
        page_title="Safety Helmet Command Center",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_theme()

    settings = load_settings()
    repository = build_repository(settings)
    directory = PersonDirectory(settings)
    evidence_store = EvidenceStore(settings)
    notifier = NotificationService(settings, repository)

    language = st.sidebar.selectbox(
        "语言 / Language",
        list(LANGUAGE_OPTIONS.keys()),
        index=0,
        format_func=lambda value: LANGUAGE_OPTIONS[value],
    )
    _render_sidebar_brand(language)
    role = st.sidebar.selectbox(
        _txt(language, "当前角色", "Role"),
        list(ROLE_OPTIONS.keys()),
        format_func=lambda value: f"{_role_label(value, language)} / {value}",
    )
    operator = st.sidebar.text_input(_txt(language, "当前操作人", "Operator"), value="demo.operator")
    allowed_pages = ROLE_PAGES[role]
    page = st.sidebar.radio(_txt(language, "页面", "Pages"), allowed_pages, format_func=lambda value: _page_meta(value, language)["nav"])
    auto_refresh = st.sidebar.checkbox(_txt(language, "自动刷新", "Auto Refresh"), value=page == "总览")
    refresh_seconds = st.sidebar.slider(_txt(language, "刷新秒数", "Refresh Interval"), min_value=5, max_value=60, value=10, step=5)

    since_days = st.sidebar.slider(_txt(language, "筛选最近天数", "Recent Days"), min_value=1, max_value=30, value=7)
    all_cameras = repository.list_cameras()
    all_alerts = sorted(repository.list_alerts(limit=1000), key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)
    filtered_alerts = _filter_alerts(
        all_alerts,
        date_from=datetime.now(tz=UTC) - timedelta(days=since_days),
    )

    st.sidebar.markdown(
        f"""
        <div class="sidebar-brand" style="padding-top:0.95rem;">
            <div class="sidebar-kicker">{html.escape(_txt(language, "系统状态", "SYSTEM STATUS"))}</div>
            <div class="sidebar-copy">
                {html.escape(_txt(language, "后端", "Backend"))}：<strong>{html.escape(repository.backend_name.upper())}</strong><br>
                {html.escape(_txt(language, "通知", "Notifications"))}：<strong>{html.escape(_txt(language, '已配置', 'Configured') if settings.notifications.is_email_configured else _txt(language, '未配置', 'Pending'))}</strong><br>
                {html.escape(_txt(language, "身份", "Identity"))}：<strong>{html.escape(settings.identity.provider)}</strong><br>
                {html.escape(_txt(language, "时间窗口", "Window"))}：<strong>{html.escape(_txt(language, f'最近 {since_days} 天', f'Last {since_days} Days'))}</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_page_hero(
        page,
        settings=settings,
        repository=repository,
        alerts=filtered_alerts,
        cameras=all_cameras,
        role=role,
        operator=operator,
        auto_refresh=auto_refresh,
        refresh_seconds=refresh_seconds,
        language=language,
    )

    if page == "总览":
        render_overview(settings, repository, filtered_alerts, all_cameras)
    elif page == "人工复核台":
        _section_header("FILTER CONSOLE", "筛选控制台", "按人员、部门、工单状态和摄像头快速筛选待处理案件。")
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            text_query = st.text_input(_txt(language, "搜索事件/人员/部门/摄像头", "Search events / people / departments / cameras"))
        with filter_col2:
            status_filter = st.multiselect(
                _txt(language, "状态", "Status"),
                list(STATUS_LABELS.keys()),
                default=list(STATUS_LABELS.keys()),
                format_func=lambda value: _status_label(value, language),
            )
        with filter_col3:
            department_options = sorted({item.get("department") for item in filtered_alerts if item.get("department")})
            department_filter = st.multiselect(_txt(language, "部门", "Department"), department_options, default=department_options)
        review_alerts = _filter_alerts(
            filtered_alerts,
            text_query=text_query,
            statuses=set(status_filter),
            departments=set(department_filter) if department_filter else None,
        )
        render_review_desk(settings, repository, directory, evidence_store, operator, role, review_alerts)
    elif page == "摄像头管理":
        render_camera_center(settings, repository, all_cameras)
    elif page == "统计报表":
        render_reports(filtered_alerts)
    elif page == "通知中心":
        render_notification_center(settings, repository, notifier, language)
    elif page == "Hard Cases":
        render_hard_cases(repository, language)

    _render_platform_configuration(settings)

    if auto_refresh and page == "总览":
        time.sleep(refresh_seconds)
        st.rerun()


_render_detail_cards_legacy = _render_detail_cards
render_overview_legacy = render_overview
render_review_desk_legacy = render_review_desk
render_camera_center_legacy = render_camera_center
render_reports_legacy = render_reports
_render_live_monitor_panel_legacy = _render_live_monitor_panel
_render_platform_configuration_legacy = _render_platform_configuration


def _inject_theme_runtime_overrides() -> None:
    st.markdown(
        """
        <style>
        .sidebar-kicker,
        .hero-kicker,
        .section-kicker {
            font-size: 0.66rem !important;
            letter-spacing: 0.16em !important;
        }

        .sidebar-title {
            font-size: 1.02rem !important;
            line-height: 1.14 !important;
        }

        .sidebar-copy {
            font-size: 0.8rem !important;
            line-height: 1.48 !important;
        }

        .hero-shell {
            padding: 0.98rem 1.02rem !important;
            border-radius: 24px !important;
        }

        .hero-grid {
            gap: 0.8rem !important;
        }

        .hero-main {
            gap: 0.5rem !important;
        }

        .hero-title {
            font-size: clamp(1.12rem, 1.72vw, 1.56rem) !important;
            line-height: 1.03 !important;
            white-space: nowrap !important;
        }

        .hero-copy {
            font-size: 0.82rem !important;
            line-height: 1.46 !important;
        }

        .pill-row {
            gap: 0.36rem !important;
        }

        .pill {
            padding: 0.34rem 0.58rem !important;
            font-size: 0.7rem !important;
        }

        .hero-board {
            gap: 0.58rem !important;
            padding: 0.72rem !important;
            border-radius: 20px !important;
        }

        .live-chip {
            font-size: 0.72rem !important;
        }

        .signal-item {
            min-height: 92px !important;
            padding: 0.58rem 0.64rem !important;
            border-radius: 16px !important;
        }

        .signal-label {
            font-size: 0.7rem !important;
        }

        .signal-value {
            font-size: 0.96rem !important;
            line-height: 1.08 !important;
        }

        .signal-note {
            font-size: 0.74rem !important;
            line-height: 1.34 !important;
        }

        .section-head {
            margin: 0.28rem 0 0.72rem !important;
        }

        .section-title {
            font-size: 1.04rem !important;
            line-height: 1.14 !important;
            white-space: nowrap !important;
        }

        .section-copy {
            font-size: 0.82rem !important;
            line-height: 1.48 !important;
        }

        .metric-card {
            min-height: 136px !important;
            padding: 0.86rem 0.84rem 0.82rem !important;
            border-radius: 18px !important;
        }

        .metric-label {
            font-size: 0.72rem !important;
        }

        .metric-value {
            margin-top: 0.42rem !important;
            font-size: clamp(1.38rem, 1.92vw, 1.92rem) !important;
            letter-spacing: -0.03em !important;
        }

        .metric-note {
            margin-top: 0.46rem !important;
            font-size: 0.8rem !important;
            line-height: 1.42 !important;
        }

        .metric-foot {
            margin-top: 0.62rem !important;
            font-size: 0.68rem !important;
        }

        .brief-strip {
            gap: 0.64rem !important;
            margin-bottom: 1rem !important;
        }

        .brief-card {
            min-height: 148px !important;
            padding: 0.82rem !important;
            border-radius: 20px !important;
        }

        .brief-label {
            font-size: 0.72rem !important;
        }

        .brief-value {
            margin-top: 0.34rem !important;
            font-size: 1.2rem !important;
            line-height: 1.04 !important;
        }

        .brief-meta {
            font-size: 0.76rem !important;
            line-height: 1.38 !important;
        }

        .brief-bar {
            margin-top: 0.62rem !important;
            height: 6px !important;
        }

        .rank-card,
        .detail-card {
            gap: 0.72rem !important;
        }

        .detail-grid {
            gap: 0.68rem !important;
        }

        .detail-card {
            min-height: 122px !important;
            padding: 0.82rem 0.84rem 0.88rem !important;
            border-radius: 20px !important;
        }

        .detail-index {
            width: 38px !important;
            height: 38px !important;
            font-size: 0.76rem !important;
            border-radius: 13px !important;
        }

        .detail-key {
            margin-top: 0.18rem !important;
            font-size: 0.88rem !important;
            line-height: 1.22 !important;
        }

        .detail-meta {
            font-size: 0.72rem !important;
            line-height: 1.34 !important;
        }

        .detail-value {
            font-size: clamp(1.02rem, 1.42vw, 1.46rem) !important;
            line-height: 1.08 !important;
            letter-spacing: -0.02em !important;
            word-break: break-word !important;
            overflow-wrap: anywhere !important;
        }

        .detail-value--compact {
            font-size: clamp(0.78rem, 1.04vw, 0.96rem) !important;
            line-height: 1.22 !important;
            letter-spacing: 0 !important;
            font-family: "IBM Plex Mono", monospace !important;
        }

        .detail-value--dense {
            font-size: clamp(0.7rem, 0.92vw, 0.84rem) !important;
        }

        .table-shell {
            border-radius: 20px !important;
        }

        .table-shell__meta {
            padding: 0.6rem 0.82rem 0.48rem !important;
            font-size: 0.68rem !important;
        }

        .table-shell--scrollable .table-shell__viewport {
            max-height: calc(2.9rem + (4.7rem * var(--table-visible-rows, 5))) !important;
        }

        .signal-table {
            min-width: 640px !important;
        }

        .signal-table thead th {
            padding: 0.74rem 0.82rem !important;
            font-size: 0.7rem !important;
        }

        .signal-table__cell {
            padding: 0.72rem 0.82rem !important;
            font-size: 0.8rem !important;
            white-space: normal !important;
            word-break: break-word !important;
            overflow-wrap: anywhere !important;
        }

        .signal-table__cell--emphasis {
            font-size: 0.78rem !important;
        }

        .camera-feed-name {
            font-size: 0.98rem !important;
        }

        .camera-feed-location {
            font-size: 0.78rem !important;
        }

        .camera-placeholder {
            min-height: 250px !important;
            border-radius: 20px !important;
        }

        .camera-placeholder__title {
            font-size: 0.92rem !important;
        }

        .camera-placeholder__meta {
            font-size: 0.78rem !important;
            line-height: 1.44 !important;
        }

        .feed-pill {
            padding: 0.36rem 0.58rem !important;
        }

        .feed-pill__label {
            font-size: 0.66rem !important;
        }

        .feed-pill__value {
            font-size: 0.76rem !important;
        }

        .camera-feed-warning {
            padding: 0.72rem 0.8rem !important;
            font-size: 0.78rem !important;
            line-height: 1.45 !important;
        }

        .platform-grid {
            gap: 0.6rem !important;
        }

        .platform-card {
            padding: 0.78rem !important;
            border-radius: 16px !important;
        }

        .platform-label {
            font-size: 0.72rem !important;
        }

        .platform-value {
            margin-top: 0.28rem !important;
            font-size: 0.82rem !important;
            line-height: 1.44 !important;
        }

        .streamlit-expanderHeader {
            font-size: 0.86rem !important;
        }

        [data-baseweb="select"] > div,
        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input,
        .stDateInput input {
            font-size: 0.9rem !important;
        }

        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span {
            font-size: 0.84rem !important;
        }

        @media (max-width: 768px) {
            .hero-title,
            .section-title {
                white-space: normal !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _format_timestamp_compact(value: str | None) -> str:
    parsed = parse_timestamp(value)
    if parsed == datetime.min.replace(tzinfo=UTC):
        return "--"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def _compact_identifier(value: object, *, head: int = 14, tail: int = 8) -> str:
    if value is None or value == "":
        return "--"
    text = str(value)
    if len(text) <= head + tail + 3:
        return text
    return f"{text[:head]}...{text[-tail:]}"


def _identity_source_label(value: str | None, language: str = "zh") -> str:
    mapping = {
        "manual_review": {"zh": "人工复核", "en": "Manual Review"},
        "face_match": {"zh": "人脸匹配", "en": "Face Match"},
        "badge_match": {"zh": "工牌匹配", "en": "Badge Match"},
        "ocr_badge": {"zh": "工牌 OCR", "en": "Badge OCR"},
        "llm": {"zh": "大模型", "en": "LLM"},
        "fallback": {"zh": "回退策略", "en": "Fallback"},
        "test_dataset_override": {"zh": "测试数据覆盖", "en": "Test Dataset Override"},
    }
    if not value:
        return _txt(language, "未知", "Unknown")
    label = mapping.get(str(value).lower())
    if not label:
        return str(value).replace("_", " ").title() if language == "en" else str(value)
    return label[language]


def _camera_frame_i18n(cameras: list[dict], language: str = "zh") -> pd.DataFrame:
    if language == "zh":
        return _camera_frame(cameras)
    if not cameras:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "Camera ID": item.get("camera_id"),
                "Name": item.get("camera_name"),
                "Site": item.get("site_name"),
                "Building": item.get("building_name"),
                "Floor": item.get("floor_name"),
                "Workshop": item.get("workshop_name"),
                "Zone": item.get("zone_name"),
                "Department": item.get("department"),
                "Status": _camera_status_label(item.get("last_status"), language),
                "Heartbeat": _format_timestamp(item.get("last_seen_at")),
                "FPS": item.get("last_fps") or "--",
                "Reconnects": item.get("reconnect_count") or 0,
                "Last Error": item.get("last_error") or "--",
            }
            for item in cameras
        ]
    )


def _alerts_frame_i18n(alerts: list[dict], language: str = "zh") -> pd.DataFrame:
    if language == "zh":
        return _alerts_frame(alerts)
    if not alerts:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "Event No": _compact_identifier(alert.get("event_no")),
                "Created At": _format_timestamp_compact(alert.get("created_at")),
                "Camera": alert.get("camera_name", alert.get("camera_id")),
                "Person": alert.get("person_name", "Unknown"),
                "Employee ID": alert.get("employee_id") or "--",
                "Department": alert.get("department") or "--",
                "Case Status": _status_label(alert.get("status"), language),
                "Identity": _identity_label(alert.get("identity_status"), language),
                "Source": _identity_source_label(alert.get("identity_source"), language),
                "Confidence": _format_confidence(alert.get("identity_confidence")),
                "Risk": alert.get("risk_level") or "--",
                "Assignee": alert.get("assigned_to") or "--",
            }
            for alert in alerts
        ]
    )


def _action_frame(actions: list[dict], language: str = "zh") -> pd.DataFrame:
    if not actions:
        return pd.DataFrame()
    rows = []
    for item in actions:
        raw_status = item.get("to_status") or item.get("new_status") or item.get("status")
        rows.append(
            {
                _txt(language, "时间", "At"): _format_timestamp(item.get("created_at") or item.get("updated_at")),
                _txt(language, "操作人", "Actor"): item.get("actor") or item.get("handled_by") or item.get("performed_by") or "--",
                _txt(language, "角色", "Role"): item.get("actor_role") or "--",
                _txt(language, "动作", "Action"): item.get("action") or item.get("action_type") or item.get("type") or "--",
                _txt(language, "状态", "Status"): _status_label(raw_status, language) if raw_status else "--",
                _txt(language, "备注", "Note"): item.get("note") or item.get("comment") or "--",
            }
        )
    return pd.DataFrame(rows)


def _build_hourly_chart_i18n(alerts: list[dict], language: str = "zh") -> alt.Chart | None:
    if language == "zh":
        return _build_hourly_chart(alerts)
    if not alerts:
        return None
    frame = pd.DataFrame(alerts)
    frame["created_at"] = frame["created_at"].apply(parse_timestamp)
    frame["hour"] = frame["created_at"].dt.strftime("%H:00")
    hourly = frame.groupby("hour").size().rename("alerts").reset_index()
    order = hourly["hour"].tolist()
    base = alt.Chart(hourly).encode(
        x=alt.X("hour:N", sort=order, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("alerts:Q"),
        tooltip=[alt.Tooltip("hour:N", title="Hour"), alt.Tooltip("alerts:Q", title="Alerts")],
    )
    area = base.mark_area(color="#00E4FF", opacity=0.12)
    line = base.mark_line(color="#6CEFFF", strokeWidth=3)
    points = base.mark_point(color="#FFAA3D", size=78, filled=True)
    return (area + line + points).properties(height=320)


def _build_daily_chart_i18n(report_df: pd.DataFrame, language: str = "zh") -> alt.Chart | None:
    if language == "zh":
        return _build_daily_chart(report_df)
    if report_df.empty:
        return None
    daily = report_df.groupby(report_df["created_at_dt"].dt.strftime("%Y-%m-%d")).size().rename("alerts").reset_index()
    base = alt.Chart(daily).encode(
        x=alt.X("created_at_dt:N", title=None),
        y=alt.Y("alerts:Q", title=None),
        tooltip=[alt.Tooltip("created_at_dt:N", title="Date"), alt.Tooltip("alerts:Q", title="Alerts")],
    )
    area = base.mark_area(color="#00E4FF", opacity=0.12)
    line = base.mark_line(color="#6CEFFF", strokeWidth=3)
    return (area + line).properties(height=300)


def _build_department_chart_i18n(
    report_df: pd.DataFrame,
    language: str = "zh",
    *,
    limit: int = 6,
    height: int = 280,
) -> alt.Chart | None:
    if language == "zh":
        return _build_department_chart(report_df, limit=limit, height=height)
    if report_df.empty or "department" not in report_df:
        return None
    ranking = (
        report_df.assign(department=report_df["department"].fillna("Unknown"))
        .groupby("department")
        .size()
        .rename("alerts")
        .reset_index()
        .sort_values("alerts", ascending=False)
        .head(limit)
    )
    return (
        alt.Chart(ranking)
        .mark_bar(cornerRadiusTopRight=8, cornerRadiusBottomRight=8)
        .encode(
            x=alt.X("alerts:Q", title=None),
            y=alt.Y("department:N", sort="-x", title=None),
            color=alt.value("#00E4FF"),
            tooltip=[alt.Tooltip("department:N", title="Department"), alt.Tooltip("alerts:Q", title="Alerts")],
        )
        .properties(height=height)
    )


def _build_status_chart_i18n(report_df: pd.DataFrame, language: str = "zh") -> alt.Chart | None:
    if language == "zh":
        return _build_status_chart(report_df)
    if report_df.empty:
        return None
    status_dist = report_df.groupby("status").size().rename("alerts").reset_index()
    status_dist["status_label"] = status_dist["status"].map(lambda value: _status_label(value, language))
    return (
        alt.Chart(status_dist)
        .mark_bar(cornerRadiusTopRight=8, cornerRadiusBottomRight=8)
        .encode(
            x=alt.X("alerts:Q", title=None),
            y=alt.Y("status_label:N", sort="-x", title=None),
            color=alt.Color("status_label:N", legend=None),
            tooltip=[alt.Tooltip("status_label:N", title="Status"), alt.Tooltip("alerts:Q", title="Alerts")],
        )
        .properties(height=300)
    )


def _render_command_strip_panel_i18n(settings, alerts: list[dict], cameras: list[dict], language: str = "zh") -> None:
    alert_summary = _alert_summary(alerts)
    camera_summary = _camera_summary(settings, cameras)
    total = alert_summary["total"]
    open_cases = alert_summary["pending"] + alert_summary["assigned"]
    resolved_rate = _safe_ratio(alert_summary["resolved_identity"], total)
    closure_rate = _safe_ratio(alert_summary["remediated"] + alert_summary["false_positive"], total)
    online_rate = _safe_ratio(camera_summary["reporting"], camera_summary["enabled"])
    review_pressure = _safe_ratio(alert_summary["review"], total)
    cards = [
        (
            _txt(language, "身份解析率", "Identity Resolved"),
            f"{resolved_rate:.0%}",
            _txt(language, "自动识别或人工确认完成的占比", "Share of alerts resolved by identity matching or manual confirmation"),
            resolved_rate,
        ),
        (
            _txt(language, "闭环进度", "Closure Progress"),
            f"{closure_rate:.0%}",
            _txt(language, "已整改与误报归档的综合进度", "Combined completion of remediation and false-positive closure"),
            closure_rate,
        ),
        (
            _txt(language, "设备在线率", "Device Online"),
            f"{online_rate:.0%}",
            _txt(language, "最近 10 分钟有心跳的启用设备占比", "Share of enabled cameras reporting heartbeats within the last 10 minutes"),
            online_rate,
        ),
        (
            _txt(language, "复核压力", "Review Pressure"),
            str(open_cases if open_cases else alert_summary["review"]),
            _txt(language, "待处理与待复核案件的即时规模", "Immediate volume of open and review-required cases"),
            review_pressure if total else 0.0,
        ),
    ]
    accents = ["cyan", "amber", "green", "red"]
    body: list[str] = []
    for index, (label, value, meta, progress) in enumerate(cards):
        width = max(6, min(100, round(progress * 100))) if progress > 0 else 6
        accent = accents[index % len(accents)]
        body.append(
            (
                f"<article class='brief-card brief-card--{accent}'>"
                "<div class='brief-topline'>"
                f"<div class='brief-label'>{html.escape(label)}</div>"
                f"<div class='brief-dot brief-dot--{accent}'></div>"
                "</div>"
                f"<div class='brief-value'>{html.escape(value)}</div>"
                f"<div class='brief-meta'>{html.escape(meta)}</div>"
                "<div class='brief-bar'>"
                f"<div class='brief-fill brief-fill--{accent}' style='width:{width}%;'></div>"
                "</div>"
                "</article>"
            )
        )
    st.markdown(f"<div class='brief-strip'>{''.join(body)}</div>", unsafe_allow_html=True)


def _render_detail_cards(items: list[tuple[str, str, str]]) -> None:
    body = []
    for index, (key, value, meta) in enumerate(items, start=1):
        value_text = "--" if value is None or value == "" else str(value)
        value_classes = ["detail-value"]
        if len(value_text) > 16:
            value_classes.append("detail-value--compact")
        if len(value_text) > 34:
            value_classes.append("detail-value--dense")
        body.append(
            (
                "<article class='detail-card'>"
                f"<div class='detail-index'>{index:02d}</div>"
                "<div class='detail-body'>"
                f"<div class='detail-meta'>{html.escape(str(meta))}</div>"
                f"<div class='detail-key'>{html.escape(str(key))}</div>"
                "</div>"
                f"<div class='{' '.join(value_classes)}'>{html.escape(value_text)}</div>"
                "</article>"
            )
        )
    st.markdown(f"<div class='detail-grid'>{''.join(body)}</div>", unsafe_allow_html=True)


def _render_live_monitor_panel(settings, cameras: list[dict], language: str = "zh") -> None:
    if language != "en":
        return _render_live_monitor_panel_legacy(settings, cameras)

    monitor_runtime, live_cameras = _merge_live_cameras(settings, cameras)
    enabled_map = {camera.camera_id: camera.enabled for camera in settings.cameras}
    filtered_cameras = [
        camera
        for camera in live_cameras
        if enabled_map.get(str(camera.get("camera_id") or ""), True)
    ]

    def _preview_exists(camera: dict) -> bool:
        preview_path = camera.get("preview_path")
        return bool(preview_path and Path(preview_path).exists())

    filtered_cameras.sort(
        key=lambda camera: (
            0 if _preview_exists(camera) else 1,
            0 if str(camera.get("status") or camera.get("last_status") or "").lower() in {"running", "healthy"} else 1,
            str(camera.get("camera_name") or camera.get("camera_id") or ""),
        )
    )

    _section_header(
        "LIVE MONITOR",
        "Live Monitor",
        "Bring online frames, stream health, and the latest errors into one watch floor instead of checking raw status tables.",
    )
    status_label = _camera_status_label(monitor_runtime.get("status"), language)
    processed_frames = str(monitor_runtime.get("processed_frames") or 0)
    latest_alert = _compact_identifier(monitor_runtime.get("last_alert_event_no"))
    updated_at = _format_timestamp_compact(monitor_runtime.get("updated_at"))
    _render_detail_cards(
        [
            ("Monitor Status", status_label, "Latest runtime state of the monitor worker"),
            ("Processed Frames", processed_frames, "Total frames processed since the current worker boot"),
            ("Latest Alert", latest_alert, "Most recent alert event captured by the monitor"),
            ("Last Update", updated_at, "Latest heartbeat refresh timestamp"),
        ]
    )

    if monitor_runtime.get("status") == "running" and not monitor_runtime.get("last_alert_event_no"):
        st.info("The monitor is online and still reading frames. No no-helmet alert has been triggered yet, and the preview will keep updating while auto refresh is enabled.")
    elif not monitor_runtime:
        st.warning("The monitor heartbeat is not available yet. The monitor service may still be starting.")

    if not filtered_cameras:
        _render_empty_panel("No live camera feeds are available right now.")
        return

    column_count = min(2, max(1, len(filtered_cameras)))
    columns = st.columns(column_count)
    for index, camera in enumerate(filtered_cameras):
        with columns[index % column_count]:
            camera_name = str(camera.get("camera_name") or camera.get("camera_id") or "Camera")
            status_value = camera.get("status") or camera.get("last_status")
            status_label = _camera_status_label(status_value, language)
            status_tone = _camera_tone({"last_status": status_value, "last_seen_at": camera.get("last_seen_at")})
            location_text = " / ".join(
                str(part)
                for part in [
                    camera.get("site_name"),
                    camera.get("building_name"),
                    camera.get("floor_name"),
                    camera.get("zone_name"),
                ]
                if part
            ) or str(camera.get("camera_id") or "--")
            st.markdown(
                (
                    "<div class='camera-feed-head'>"
                    "<div>"
                    f"<div class='camera-feed-name'>{html.escape(camera_name)}</div>"
                    f"<div class='camera-feed-location'>{html.escape(location_text)}</div>"
                    "</div>"
                    f"{_status_chip(status_label, status_tone)}"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

            preview_path = camera.get("preview_path")
            preview_file = Path(preview_path) if preview_path else None
            if preview_file and preview_file.exists():
                st.image(str(preview_file), use_container_width=True)
            else:
                st.markdown(
                    (
                        "<div class='camera-placeholder'>"
                        "<div>"
                        "<div class='camera-placeholder__title'>Awaiting Live Preview</div>"
                        "<div class='camera-placeholder__meta'>The monitor already owns this device. The preview tile will appear automatically after the next frame is written.</div>"
                        "</div>"
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )

            st.markdown(
                (
                    "<div class='camera-feed-meta'>"
                    f"{_feed_pill('Status', status_label)}"
                    f"{_feed_pill('FPS', camera.get('last_fps') or '--')}"
                    f"{_feed_pill('Updated', _format_timestamp_compact(camera.get('preview_updated_at') or monitor_runtime.get('updated_at')))}"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            if camera.get("last_error"):
                st.markdown(
                    f"<div class='camera-feed-warning'>{html.escape(str(camera['last_error']))}</div>",
                    unsafe_allow_html=True,
                )


def _render_platform_configuration(settings, language: str = "zh") -> None:
    if language != "en":
        return _render_platform_configuration_legacy(settings)

    config_items = [
        ("Runtime Config", str(settings.config_path)),
        ("Model Path", str(settings.resolve_path(settings.model.path))),
        ("Tracking Provider", settings.tracking.provider),
        ("Identity Provider", settings.identity.provider),
        ("Clip Buffer", f"{settings.clip.pre_seconds}s / {settings.clip.post_seconds}s"),
        ("Private Bucket", "Enabled" if settings.security.use_private_bucket else "Disabled"),
    ]
    blocks = []
    for label, value in config_items:
        blocks.append(
            (
                "<div class='platform-card'>"
                f"<div class='platform-label'>{html.escape(label)}</div>"
                f"<div class='platform-value'>{html.escape(value)}</div>"
                "</div>"
            )
        )
    with st.expander("Platform Runtime Config", expanded=False):
        st.markdown(
            f"<div class='platform-shell'><div class='platform-grid'>{''.join(blocks)}</div></div>",
            unsafe_allow_html=True,
        )


def render_overview(settings, repository, alerts: list[dict], cameras: list[dict], language: str = "zh") -> None:
    if language != "en":
        return render_overview_legacy(settings, repository, alerts, cameras)

    today = _start_of_day()
    todays_alerts = [item for item in alerts if parse_timestamp(item.get("created_at")) >= today]
    pending_count = sum(1 for item in todays_alerts if item.get("status") == "pending")
    review_count = sum(1 for item in todays_alerts if item.get("identity_status") in {"review_required", "unresolved"})
    remediated_count = sum(1 for item in todays_alerts if item.get("status") == "remediated")
    false_positive_count = sum(1 for item in todays_alerts if item.get("status") == "false_positive")
    resolved_identity = sum(1 for item in todays_alerts if item.get("identity_status") == "resolved")

    _section_header(
        "REAL-TIME OPERATIONS",
        "Operations Overview",
        "Coordinate daily posture, risk hotspots, evidence surfaces, and camera health from one industrial control board.",
    )
    _render_command_strip_panel_i18n(settings, todays_alerts, cameras, language)
    _render_metric_cards(
        [
            {"label": "Today Alerts", "value": str(len(todays_alerts)), "note": "Total alert events accumulated during the current day", "foot": "Today / Alerts", "tone": "neutral"},
            {"label": "Pending Queue", "value": str(pending_count), "note": "Field cases that still require action to close", "foot": "Pending Queue", "tone": "warning"},
            {"label": "Review Required", "value": str(review_count), "note": "Identity or evidence that still requires human confirmation", "foot": "Review Required", "tone": "warning"},
            {"label": "Resolved Identity", "value": str(resolved_identity), "note": "Cases resolved by identity matching or manual confirmation", "foot": "Identity Resolved", "tone": "positive"},
            {"label": "False Positive", "value": str(false_positive_count), "note": "Events already classified as false positives", "foot": "False Positive", "tone": "danger" if false_positive_count else "neutral"},
        ]
    )

    trend_col, dept_col = st.columns((1.7, 1))
    with trend_col:
        _section_header("TREND ANALYTICS", "Daily Trend", "Track the hourly alert rhythm to understand shifts, spikes, and quiet windows.")
        chart = _build_hourly_chart_i18n(todays_alerts, language)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        else:
            _render_empty_panel("No alerts have been recorded yet today, and the current production window looks stable.")

    with dept_col:
        _section_header("HOTSPOT RANKING", "Department Hotspots", "Identify departments that currently absorb the most operational attention.")
        if todays_alerts:
            dept_df = pd.DataFrame(todays_alerts)
            dept_chart = _build_department_chart_i18n(dept_df, language, limit=5, height=200)
            if dept_chart is not None:
                st.altair_chart(dept_chart, use_container_width=True)
            ranking = (
                dept_df.assign(department=dept_df["department"].fillna("Unknown"))
                .groupby("department")
                .size()
                .rename("alerts")
                .sort_values(ascending=False)
            )
            rank_items = [(department, "Alerts today", f"{count}") for department, count in ranking.head(6).items()]
            _render_rank_list(rank_items, empty_message="No department ranking is available yet.")
        else:
            _render_empty_panel("No department ranking is available yet.")

    table_col, insight_col = st.columns((1.7, 1))
    with table_col:
        _section_header("TRIAGE QUEUE", "Recent Alerts", "Review the freshest alerts first and jump into downstream handling faster.")
        alert_frame = _alerts_frame_i18n(alerts[:16], language)
        if not alert_frame.empty:
            alert_frame = alert_frame.iloc[:, :8]
        _render_table_surface(
            alert_frame,
            empty_message="No alert records are available to display.",
            max_visible_rows=5,
            scroll_label="Scrollable feed: five rows stay visible by default. Drag the side scrollbar to browse older alerts.",
        )

    with insight_col:
        _section_header("CONTROL SIGNALS", "Control Signals", "Compress the most important governance indicators into fast-to-read signal cards.")
        top_department = "--"
        if todays_alerts:
            department_frame = pd.DataFrame(todays_alerts)
            ranking = department_frame.assign(department=department_frame["department"].fillna("Unknown")).groupby("department").size().sort_values(ascending=False)
            if not ranking.empty:
                top_department = str(ranking.index[0] or "Unknown")
        latest_event = alerts[0].get("event_no") if alerts else "--"
        _render_detail_cards(
            [
                ("Remediated", str(remediated_count), "Cases completed with a remediation outcome today"),
                ("Focus Department", top_department, "Department currently carrying the highest alert density"),
                ("Latest Event", _compact_identifier(latest_event), "Most recent alert in the active timeline"),
                ("Data Backend", repository.backend_name.upper(), "Data backend currently powering the control board"),
            ]
        )

    _render_live_monitor_panel(settings, cameras, language)

    evidence_col, camera_col = st.columns((1.25, 1))
    with evidence_col:
        _section_header("EVIDENCE MOSAIC", "Evidence Mosaic", "Use a visual wall of recent snapshots to validate what is actually happening in the field.")
        if alerts:
            columns = st.columns(3)
            rendered = 0
            for alert in alerts[:9]:
                image_path = _display_optional_media(alert, "snapshot_url", "snapshot_path")
                if not image_path:
                    continue
                with columns[rendered % 3]:
                    st.image(image_path, use_container_width=True)
                    st.markdown(
                        f"<div class='evidence-caption'>{_safe_text(alert.get('camera_name'))}<br>{_safe_text(alert.get('event_no') or alert.get('alert_id'))}</div>",
                        unsafe_allow_html=True,
                    )
                rendered += 1
            if rendered == 0:
                _render_empty_panel("Recent alerts do not contain snapshot evidence yet.")
        else:
            _render_empty_panel("Snapshots will appear here after alerts are captured.")

    with camera_col:
        _section_header("DEVICE HEALTH", "Camera Health", "Inspect heartbeat freshness, errors, and FPS together to judge stream quality.")
        camera_frame = _camera_frame_i18n(cameras, language)
        if camera_frame.empty:
            _render_empty_panel("No camera heartbeat data is available yet.")
        else:
            camera_frame = camera_frame.iloc[:, [0, 1, 2, 3, 8, 9, 10, 12]]
            _render_table_surface(camera_frame, empty_message="No camera heartbeat data is available yet.")


def render_review_desk(
    settings,
    repository,
    directory: PersonDirectory,
    evidence_store: EvidenceStore,
    operator: str,
    role: str,
    alerts: list[dict],
    language: str = "zh",
) -> None:
    if language != "en":
        return render_review_desk_legacy(settings, repository, directory, evidence_store, operator, role, alerts)

    workflow = AlertWorkflowService(repository)
    _section_header(
        "CASE OPERATIONS",
        "Review Desk",
        "Use one operator surface for evidence review, identity correction, notification checks, and case resolution.",
    )

    if not alerts:
        _render_empty_panel("No alerts match the current filter set.")
        return

    summary = _alert_summary(alerts)
    _render_metric_cards(
        [
            {"label": "Actionable Cases", "value": str(summary["pending"] + summary["assigned"]), "note": "Cases in the current filter set that still require operational action", "foot": "Actionable Cases", "tone": "warning"},
            {"label": "Identity Review", "value": str(summary["review"]), "note": "Cases that still need manual identity or evidence confirmation", "foot": "Identity Review", "tone": "warning"},
            {"label": "Resolved Identity", "value": str(summary["resolved_identity"]), "note": "Cases already matched or manually confirmed to a person", "foot": "Resolved Identity", "tone": "positive"},
            {"label": "Closed Loop", "value": str(summary["remediated"]), "note": "Cases already completed with a remediation outcome inside this filter window", "foot": "Closed Loop", "tone": "positive"},
        ]
    )

    selection_options = {
        f"{alert.get('event_no') or alert.get('alert_id')} | {_status_label(alert.get('status'), language)} | {alert.get('camera_name')} | {alert.get('person_name', 'Unknown')}": alert
        for alert in alerts
    }
    selected_label = st.selectbox("Select Alert Case", list(selection_options.keys()))
    alert = selection_options[selected_label]

    left, right = st.columns((1.2, 1))
    with left:
        _section_header("EVIDENCE STACK", "Evidence Stack", "Prioritize the scene snapshot, clip, and face or badge crops before you decide the next action.")
        snapshot = _display_optional_media(alert, "snapshot_url", "snapshot_path")
        face_media = _display_optional_media(alert, "face_crop_url", "face_crop_path")
        badge_media = _display_optional_media(alert, "badge_crop_url", "badge_crop_path")
        clip_media = _display_optional_media(alert, "clip_url", "clip_path")
        if snapshot:
            st.image(snapshot, caption="Scene Snapshot", use_container_width=True)
        else:
            _render_empty_panel("This case does not have a scene snapshot yet.")
        if clip_media:
            st.video(clip_media)
        media_cols = st.columns(2)
        with media_cols[0]:
            if face_media:
                st.image(face_media, caption="Face Evidence", use_container_width=True)
            else:
                _render_empty_panel("No face crop is available.")
        with media_cols[1]:
            if badge_media:
                st.image(badge_media, caption="Badge Evidence", use_container_width=True)
            else:
                _render_empty_panel("No badge crop is available.")

    with right:
        _section_header("CASE DOSSIER", "Case Dossier", "Compress the case into a concise decision packet for faster operator handling.")
        st.markdown(
            f"""
            <div class="chip-row">
                {_status_chip(_status_label(alert.get("status"), language), _status_tone(alert.get("status")))}
                {_status_chip(_identity_label(alert.get("identity_status"), language), _identity_tone(alert.get("identity_status")))}
                {_status_chip(str(alert.get("camera_name") or alert.get("camera_id") or "--"), "neutral")}
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_detail_cards(
            [
                ("Event No", str(alert.get("event_no") or alert.get("alert_id") or "--"), "Unique case or alert identifier"),
                ("Case Status", _status_label(alert.get("status"), language), "Current workflow state in the case lifecycle"),
                ("Identity Status", _identity_label(alert.get("identity_status"), language), "Current identity resolution state"),
                ("Identity Source", _identity_source_label(alert.get("identity_source"), language), "Origin of the identity result used by the case"),
                ("Confidence", _format_confidence(alert.get("identity_confidence")), "Confidence associated with the current identity conclusion"),
                ("Person", str(alert.get("person_name", "Unknown")), "Person linked to the current case"),
                ("Employee ID", str(alert.get("employee_id") or "--"), "Employee identifier when one is available"),
                ("Department", str(alert.get("department") or "--"), "Department used for ownership and governance analytics"),
                (
                    "Location",
                    " / ".join(
                        str(part)
                        for part in [
                            alert.get("site_name") or "--",
                            alert.get("building_name") or "--",
                            alert.get("floor_name") or "--",
                        ]
                    ),
                    "Simplified site, building, and floor location string",
                ),
                ("Created At", _format_timestamp_compact(alert.get("created_at")), "System write time of the event"),
            ]
        )
        if alert.get("review_note"):
            st.warning(alert["review_note"])
        if alert.get("governance_note"):
            st.info(alert["governance_note"])

    actions = repository.list_alert_actions(alert_id=alert["alert_id"], limit=100)
    notifications = repository.list_notification_logs(alert_id=alert["alert_id"], limit=100)
    history_col, notify_col = st.columns(2)
    with history_col:
        _section_header("WORKFLOW HISTORY", "Action History", "Track status transitions and the exact operator actions already taken on the case.")
        _render_table_surface(_action_frame(actions, language), empty_message="No action history is available for this case yet.")
    with notify_col:
        _section_header("DELIVERY LOG", "Notification Log", "Inspect outbound delivery attempts and the current notification status.")
        _render_table_surface(_notification_frame(notifications, language), empty_message="No notification records are available for this case yet.")

    if role == "viewer":
        st.info("Viewer mode is read-only. Assignment and case resolution actions are hidden.")
        return

    people = directory.get_people()
    person_labels = {"Keep Current Person": None}
    for person in people:
        label = f"{person.get('name')} | {person.get('employee_id')} | {person.get('department')}"
        person_labels[label] = person

    assign_col, status_col = st.columns(2)
    with assign_col:
        _section_header("ASSIGNMENT", "Assignment", "Route the case to a specific owner and capture the transfer context.")
        with st.form("assign_form_en"):
            assignee = st.text_input("Assignee")
            assignee_email = st.text_input("Assignee Email")
            assign_note = st.text_area("Assignment Note")
            assign_submit = st.form_submit_button("Submit Assignment")
        if assign_submit and assignee:
            workflow.assign(
                alert,
                actor=operator,
                actor_role=role,
                assignee=assignee,
                assignee_email=assignee_email,
                note=assign_note,
            )
            st.success("The case has been assigned.")
            st.rerun()

    with status_col:
        _section_header("CASE RESOLUTION", "Case Resolution", "Update the case status, correct the person, and upload remediation evidence.")
        status_values = list(STATUS_LABELS.keys())
        current_status = alert.get("status")
        status_index = status_values.index(current_status) if current_status in status_values else 0
        with st.form("status_form_en"):
            new_status = st.selectbox(
                "New Status",
                options=status_values,
                format_func=lambda value: _status_label(value, language),
                index=status_index,
            )
            corrected_person_label = st.selectbox("Resolved Person", list(person_labels.keys()))
            resolution_note = st.text_area("Resolution Note")
            remediation_file = st.file_uploader("Remediation Snapshot", type=["png", "jpg", "jpeg"], accept_multiple_files=False)
            status_submit = st.form_submit_button("Update Case")
        if status_submit:
            remediation_path = None
            remediation_url = None
            if remediation_file is not None:
                extension = Path(remediation_file.name).suffix or ".jpg"
                remediation_path, remediation_url = evidence_store.save_bytes(
                    alert.get("camera_id") or "manual",
                    remediation_file.getvalue(),
                    f"{alert['alert_id']}_remediation",
                    datetime.now(tz=UTC),
                    category="remediation",
                    extension=extension,
                    content_type=remediation_file.type or "image/jpeg",
                )
            corrected_identity = None
            selected_person = person_labels.get(corrected_person_label)
            if selected_person:
                corrected_identity = {
                    "person_id": selected_person.get("person_id"),
                    "person_name": selected_person.get("name"),
                    "employee_id": selected_person.get("employee_id"),
                    "department": selected_person.get("department"),
                    "team": selected_person.get("team"),
                    "role": selected_person.get("role"),
                    "phone": selected_person.get("phone"),
                    "identity_status": "resolved",
                    "identity_source": "manual_review",
                }
            workflow.update_status(
                alert,
                actor=operator,
                actor_role=role,
                new_status=new_status,
                note=resolution_note,
                corrected_identity=corrected_identity,
                remediation_snapshot_path=remediation_path,
                remediation_snapshot_url=remediation_url,
            )
            st.success("The case has been updated.")
            st.rerun()


def render_camera_center(settings, repository, cameras: list[dict], language: str = "zh") -> None:
    if language != "en":
        return render_camera_center_legacy(settings, repository, cameras)

    _section_header("DEVICE ORCHESTRATION", "Camera Center", "Inspect online posture, update stream metadata, and keep runtime camera configuration clean.")
    summary = _camera_summary(settings, cameras)
    _render_metric_cards(
        [
            {"label": "Configured Cameras", "value": str(summary["configured"]), "note": "Total cameras registered in the runtime configuration", "foot": "Configured", "tone": "neutral"},
            {"label": "Enabled Cameras", "value": str(summary["enabled"]), "note": "Cameras actively participating in the monitoring workload", "foot": "Enabled", "tone": "positive"},
            {"label": "Reporting Cameras", "value": str(summary["reporting"]), "note": "Devices with fresh heartbeats during the last 10 minutes", "foot": "Reporting", "tone": "positive" if summary["reporting"] else "warning"},
            {"label": "Abnormal Cameras", "value": str(summary["abnormal"]), "note": "Devices currently flagged as offline, degraded, or error state", "foot": "Abnormal", "tone": "danger" if summary["abnormal"] else "neutral"},
        ]
    )

    table_col, form_col = st.columns((1.3, 1))
    with table_col:
        _section_header("LIVE FABRIC", "Device Inventory", "Review location, status, FPS, and recent errors to judge stream quality.")
        camera_table = _camera_frame_i18n(cameras, language)
        if not camera_table.empty:
            camera_table = camera_table.iloc[:, [0, 1, 2, 3, 4, 7, 8, 9, 10, 12]]
        _render_table_surface(camera_table, empty_message="No device records are available yet.")

    with form_col:
        _section_header("CONFIG EDITOR", "Runtime Config Editor", "Maintain source, location, ownership, and default routing for a single camera entry.")
        existing_options = {"New Camera": None}
        for camera in settings.cameras:
            existing_options[f"{camera.camera_id} | {camera.camera_name}"] = camera
        selected = st.selectbox("Target", list(existing_options.keys()))
        current = existing_options[selected]

        with st.form("camera_form_en"):
            raw_source = _runtime_camera_source(settings.config_path, current.camera_id if current else None)
            source_default = raw_source if _is_safe_camera_source_reference(raw_source) else ("0" if current is None else "")
            camera_id = st.text_input("camera_id", value=current.camera_id if current else "")
            camera_name = st.text_input("camera_name", value=current.camera_name if current else "")
            source_ref = st.text_input(
                "source_ref",
                value=source_default,
                help="Allow local device indexes / local video paths, or env placeholders such as ${HELMET_MONITOR_STREAM_URL:rtsp://example/live}.",
            )
            if current and raw_source and not _is_safe_camera_source_reference(raw_source):
                st.warning("The current remote source is hidden. Replace it with an env placeholder before saving so secrets are not written back to runtime.json.")
            enabled = st.checkbox("enabled", value=current.enabled if current else True)
            location = st.text_input("location", value=current.location if current else "")
            department = st.text_input("department", value=current.department if current else "")
            site_name = st.text_input("site_name", value=current.site_name if current else "Default Site")
            building_name = st.text_input("building_name", value=current.building_name if current else "Main Building")
            floor_name = st.text_input("floor_name", value=current.floor_name if current else "Floor 1")
            workshop_name = st.text_input("workshop_name", value=current.workshop_name if current else "Workshop A")
            zone_name = st.text_input("zone_name", value=current.zone_name if current else "Zone A")
            responsible_department = st.text_input(
                "responsible_department",
                value=current.responsible_department if current else department,
            )
            alert_emails = st.text_input(
                "alert_emails",
                value=",".join(current.alert_emails) if current else "",
                help="Separate multiple recipients with commas.",
            )
            default_person_id = st.text_input("default_person_id", value=current.default_person_id if current else "")
            save_submit = st.form_submit_button("Save to Runtime Config")
    if save_submit and camera_id:
        source_value = source_ref.strip() or raw_source
        if not _is_safe_camera_source_reference(source_value):
            st.error("source_ref only accepts local device indexes, local video paths, or env placeholders.")
            return
        payload = {
            "camera_id": camera_id,
            "camera_name": camera_name or camera_id,
            "source": source_value,
            "enabled": enabled,
            "location": location or "Unknown",
            "department": department or "Unknown",
            "site_name": site_name,
            "building_name": building_name,
            "floor_name": floor_name,
            "workshop_name": workshop_name,
            "zone_name": zone_name,
            "responsible_department": responsible_department or department or "Unknown",
            "alert_emails": [item.strip() for item in alert_emails.split(",") if item.strip()],
            "default_person_id": default_person_id.strip(),
        }
        _upsert_runtime_camera(settings.config_path, payload)
        repository.upsert_camera(
            {
                **payload,
                "last_status": "configured",
                "last_seen_at": datetime.now(tz=UTC).isoformat(),
                "retry_count": 0,
                "reconnect_count": 0,
                "last_error": None,
                "last_frame_at": None,
                "last_fps": None,
            }
        )
        st.success("The camera entry has been written to the runtime config. Restart the monitor worker to activate the change.")
        st.rerun()


def render_reports(alerts: list[dict], language: str = "zh") -> None:
    if language != "en":
        return render_reports_legacy(alerts)

    _section_header(
        "DATA PRODUCTS",
        "Governance Reports",
        "Turn trends, status mix, departments, and people into readable governance outputs.",
    )
    if not alerts:
        _render_empty_panel("No reporting data is available yet.")
        return

    report_df = pd.DataFrame(alerts)
    report_df["created_at_dt"] = report_df["created_at"].apply(parse_timestamp)
    total_alerts = len(report_df)
    unique_people = report_df["employee_id"].fillna("unknown").nunique()
    closure_rate = float((report_df["status"].isin(["remediated", "ignored", "false_positive"])).mean() * 100)
    false_positive_rate = float((report_df["status"] == "false_positive").mean() * 100)
    open_queue = int((report_df["status"].isin(["pending", "assigned"])).sum())

    _render_metric_cards(
        [
            {"label": "Alert Volume", "value": str(total_alerts), "note": "Total alert volume inside the current filter window", "foot": "Alert Volume", "tone": "neutral"},
            {"label": "People Impacted", "value": str(unique_people), "note": "Distinct people represented in the filtered alert set", "foot": "People Impacted", "tone": "positive"},
            {"label": "Closure Rate", "value": f"{closure_rate:.1f}%", "note": "Share of alerts already remediated, ignored, or closed as false positive", "foot": "Closure Rate", "tone": "positive"},
            {"label": "Open Cases", "value": str(open_queue), "note": "Cases that still require operational follow-through", "foot": "Open Cases", "tone": "warning"},
            {"label": "False Positive Rate", "value": f"{false_positive_rate:.1f}%", "note": "False-positive share within the current filtered dataset", "foot": "False Positive Rate", "tone": "danger" if false_positive_rate else "neutral"},
        ]
    )

    chart_col, status_col = st.columns(2)
    with chart_col:
        _section_header("TREND CURVE", "Daily Trend", "Observe the accumulation of alerts over time and detect operational swings.")
        chart = _build_daily_chart_i18n(report_df, language)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        else:
            _render_empty_panel("No trend data is available yet.")
    with status_col:
        _section_header("STATUS MIX", "Status Mix", "Use a horizontal comparison of workflow states to read the current governance balance.")
        chart = _build_status_chart_i18n(report_df, language)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        else:
            _render_empty_panel("No status distribution is available yet.")

    ranking_col, people_col = st.columns(2)
    with ranking_col:
        _section_header("DEPARTMENT HOTSPOTS", "Department Ranking", "Identify departments that currently need the most governance attention.")
        dept_rank = (
            report_df.assign(department=report_df["department"].fillna("Unknown"))
            .groupby("department")
            .size()
            .rename("alerts")
            .sort_values(ascending=False)
        )
        items = [(name, "Alert volume", str(count)) for name, count in dept_rank.head(8).items()]
        _render_rank_list(items, empty_message="No department ranking is available yet.")
    with people_col:
        _section_header("PEOPLE HOTSPOTS", "People Hotspots", "Spot the people who appear most frequently across alerts and need extra attention.")
        person_rank = (
            report_df.assign(person_name=report_df["person_name"].fillna("Unknown"), employee_id=report_df["employee_id"].fillna("--"))
            .groupby(["person_name", "employee_id"])
            .size()
            .rename("alerts")
            .sort_values(ascending=False)
            .head(10)
        )
        items = [(f"{name} / {employee_id}", "Alert volume", str(count)) for (name, employee_id), count in person_rank.items()]
        _render_rank_list(items, empty_message="No people ranking is available yet.")

    export_df = report_df[
        [
            "event_no",
            "created_at",
            "camera_name",
            "person_name",
            "employee_id",
            "department",
            "status",
            "identity_status",
            "risk_level",
            "assigned_to",
            "handled_by",
        ]
    ]
    _section_header("EXPORT CENTER", "Export Center", "Export the filtered reporting slice for downstream briefing, archival, or external analytics.")
    st.download_button(
        "Export CSV",
        data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="safety_alert_report.csv",
        mime="text/csv",
    )


def main() -> None:
    st.set_page_config(
        page_title="Safety Helmet Command Center",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_theme()
    _inject_theme_runtime_overrides()

    settings = load_settings()
    repository = build_repository(settings)
    directory = PersonDirectory(settings)
    evidence_store = EvidenceStore(settings)
    notifier = NotificationService(settings, repository)

    language = st.sidebar.selectbox(
        "语言 / Language",
        list(LANGUAGE_OPTIONS.keys()),
        index=0,
        format_func=lambda value: LANGUAGE_OPTIONS[value],
    )
    _render_sidebar_brand(language)
    role = st.sidebar.selectbox(
        _txt(language, "当前角色", "Role"),
        list(ROLE_OPTIONS.keys()),
        format_func=lambda value: f"{_role_label(value, language)} / {value}",
    )
    operator = st.sidebar.text_input(_txt(language, "当前操作人", "Operator"), value="demo.operator")
    allowed_pages = ROLE_PAGES[role]
    page = st.sidebar.radio(_txt(language, "页面", "Pages"), allowed_pages, format_func=lambda value: _page_meta(value, language)["nav"])
    auto_refresh = st.sidebar.checkbox(_txt(language, "自动刷新", "Auto Refresh"), value=page == "总览")
    refresh_seconds = st.sidebar.slider(_txt(language, "刷新秒数", "Refresh Interval"), min_value=5, max_value=60, value=10, step=5)

    since_days = st.sidebar.slider(_txt(language, "筛选最近天数", "Recent Days"), min_value=1, max_value=30, value=7)
    all_cameras = repository.list_cameras()
    all_alerts = sorted(repository.list_alerts(limit=1000), key=lambda item: parse_timestamp(item.get("created_at")), reverse=True)
    filtered_alerts = _filter_alerts(
        all_alerts,
        date_from=datetime.now(tz=UTC) - timedelta(days=since_days),
    )

    st.sidebar.markdown(
        f"""
        <div class="sidebar-brand" style="padding-top:0.82rem;">
            <div class="sidebar-kicker">{html.escape(_txt(language, "系统状态", "SYSTEM STATUS"))}</div>
            <div class="sidebar-copy">
                {html.escape(_txt(language, "后端", "Backend"))}: <strong>{html.escape(repository.backend_name.upper())}</strong><br>
                {html.escape(_txt(language, "通知", "Notifications"))}: <strong>{html.escape(_txt(language, '已配置', 'Configured') if settings.notifications.is_email_configured else _txt(language, '未配置', 'Pending'))}</strong><br>
                {html.escape(_txt(language, "身份", "Identity"))}: <strong>{html.escape(settings.identity.provider)}</strong><br>
                {html.escape(_txt(language, "时间窗口", "Window"))}: <strong>{html.escape(_txt(language, f'最近 {since_days} 天', f'Last {since_days} Days'))}</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_page_hero(
        page,
        settings=settings,
        repository=repository,
        alerts=filtered_alerts,
        cameras=all_cameras,
        role=role,
        operator=operator,
        auto_refresh=auto_refresh,
        refresh_seconds=refresh_seconds,
        language=language,
    )

    if page == "总览":
        render_overview(settings, repository, filtered_alerts, all_cameras, language)
    elif page == "人工复核台":
        _section_header(
            "FILTER CONSOLE",
            _txt(language, "筛选控制台", "Filter Console"),
            _txt(language, "按人员、部门、工单状态和摄像头快速筛选待处理案件。", "Filter cases by people, department, status, and cameras to focus operator attention quickly."),
        )
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            text_query = st.text_input(_txt(language, "搜索事件/人员/部门/摄像头", "Search events / people / departments / cameras"))
        with filter_col2:
            status_filter = st.multiselect(
                _txt(language, "状态", "Status"),
                list(STATUS_LABELS.keys()),
                default=list(STATUS_LABELS.keys()),
                format_func=lambda value: _status_label(value, language),
            )
        with filter_col3:
            department_options = sorted({item.get("department") for item in filtered_alerts if item.get("department")})
            department_filter = st.multiselect(_txt(language, "部门", "Department"), department_options, default=department_options)
        review_alerts = _filter_alerts(
            filtered_alerts,
            text_query=text_query,
            statuses=set(status_filter),
            departments=set(department_filter) if department_filter else None,
        )
        render_review_desk(settings, repository, directory, evidence_store, operator, role, review_alerts, language)
    elif page == "摄像头管理":
        render_camera_center(settings, repository, all_cameras, language)
    elif page == "统计报表":
        render_reports(filtered_alerts, language)
    elif page == "通知中心":
        render_notification_center(settings, repository, notifier, language)
    elif page == "Hard Cases":
        render_hard_cases(repository, language)

    _render_platform_configuration(settings, language)

    if auto_refresh and page == "总览":
        time.sleep(refresh_seconds)
        st.rerun()


if __name__ == "__main__":
    main()
