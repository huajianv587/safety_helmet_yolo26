from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st


REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.notifier import NotificationService
from helmet_monitoring.services.person_directory import PersonDirectory
from helmet_monitoring.services.workflow import AlertWorkflowService
from helmet_monitoring.storage.evidence_store import EvidenceStore
from helmet_monitoring.storage.repository import build_repository, parse_timestamp


UTC = timezone.utc
STATUS_LABELS = {
    "pending": "待处理",
    "confirmed": "已确认",
    "remediated": "已整改",
    "false_positive": "误报",
    "ignored": "已忽略",
    "assigned": "已转派",
}
ROLE_OPTIONS = {
    "admin": "管理员",
    "team_lead": "班组长",
    "safety_manager": "安监负责人",
    "viewer": "只读访客",
}
ROLE_PAGES = {
    "admin": ["总览", "人工复核台", "摄像头管理", "统计报表", "通知中心", "Hard Cases"],
    "safety_manager": ["总览", "人工复核台", "统计报表", "通知中心", "Hard Cases"],
    "team_lead": ["总览", "人工复核台", "统计报表"],
    "viewer": ["总览", "统计报表"],
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


def _status_label(value: str | None) -> str:
    if not value:
        return "未知"
    return STATUS_LABELS.get(value, value)


def _camera_frame(cameras: list[dict]) -> pd.DataFrame:
    if not cameras:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "camera_id": item.get("camera_id"),
                "camera_name": item.get("camera_name"),
                "site": item.get("site_name"),
                "building": item.get("building_name"),
                "floor": item.get("floor_name"),
                "workshop": item.get("workshop_name"),
                "zone": item.get("zone_name"),
                "department": item.get("department"),
                "status": item.get("last_status"),
                "last_seen_at": item.get("last_seen_at"),
                "retry_count": item.get("retry_count"),
                "reconnect_count": item.get("reconnect_count"),
                "last_fps": item.get("last_fps"),
                "last_error": item.get("last_error"),
            }
            for item in cameras
        ]
    )


def _alerts_frame(alerts: list[dict]) -> pd.DataFrame:
    if not alerts:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "event_no": alert.get("event_no"),
                "created_at": alert.get("created_at"),
                "camera_name": alert.get("camera_name", alert.get("camera_id")),
                "person_name": alert.get("person_name", "Unknown"),
                "employee_id": alert.get("employee_id"),
                "department": alert.get("department"),
                "status": _status_label(alert.get("status")),
                "identity_status": alert.get("identity_status"),
                "identity_source": alert.get("identity_source"),
                "identity_confidence": alert.get("identity_confidence"),
                "risk_level": alert.get("risk_level"),
                "assigned_to": alert.get("assigned_to"),
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


def render_overview(repository, alerts: list[dict], cameras: list[dict]) -> None:
    today = _start_of_day()
    todays_alerts = [item for item in alerts if parse_timestamp(item.get("created_at")) >= today]
    pending_count = sum(1 for item in todays_alerts if item.get("status") == "pending")
    review_count = sum(1 for item in todays_alerts if item.get("identity_status") in {"review_required", "unresolved"})
    remediated_count = sum(1 for item in todays_alerts if item.get("status") == "remediated")
    false_positive_count = sum(1 for item in todays_alerts if item.get("status") == "false_positive")

    st.subheader("运营概览")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("今日告警", len(todays_alerts))
    col2.metric("待处理", pending_count)
    col3.metric("待复核", review_count)
    col4.metric("已整改", remediated_count)
    col5.metric("误报", false_positive_count)

    trend_col, dept_col = st.columns((2, 1))
    with trend_col:
        st.subheader("今日趋势")
        if todays_alerts:
            trend_df = pd.DataFrame(todays_alerts)
            trend_df["created_at"] = trend_df["created_at"].apply(parse_timestamp)
            trend_df["hour"] = trend_df["created_at"].dt.strftime("%H:00")
            chart_df = trend_df.groupby("hour").size().rename("alerts").reset_index()
            st.bar_chart(chart_df.set_index("hour"))
        else:
            st.info("今天还没有告警。")

    with dept_col:
        st.subheader("部门排行")
        if todays_alerts:
            dept_df = pd.DataFrame(todays_alerts)
            ranking = dept_df.groupby("department").size().rename("alerts").sort_values(ascending=False)
            st.dataframe(ranking.reset_index(), hide_index=True, use_container_width=True)
        else:
            st.info("暂无数据。")

    st.subheader("最近告警")
    st.dataframe(_alerts_frame(alerts[:20]), hide_index=True, use_container_width=True)

    st.subheader("证据墙")
    if alerts:
        columns = st.columns(3)
        for index, alert in enumerate(alerts[:9]):
            image_path = _display_optional_media(alert, "snapshot_url", "snapshot_path")
            with columns[index % 3]:
                if image_path:
                    st.image(
                        image_path,
                        caption=f"{alert.get('event_no') or alert.get('alert_id')} | {alert.get('camera_name')}",
                        use_container_width=True,
                    )
    else:
        st.info("证据图会在告警生成后出现在这里。")

    st.subheader("摄像头健康度")
    st.dataframe(_camera_frame(cameras), hide_index=True, use_container_width=True)


def render_review_desk(settings, repository, directory: PersonDirectory, evidence_store: EvidenceStore, operator: str, role: str, alerts: list[dict]) -> None:
    workflow = AlertWorkflowService(repository)
    st.subheader("人工复核台")

    if not alerts:
        st.info("当前没有符合筛选条件的告警。")
        return

    selection_options = {
        f"{alert.get('event_no') or alert.get('alert_id')} | {_status_label(alert.get('status'))} | {alert.get('camera_name')} | {alert.get('person_name', 'Unknown')}": alert
        for alert in alerts
    }
    selected_label = st.selectbox("选择告警工单", list(selection_options.keys()))
    alert = selection_options[selected_label]

    left, right = st.columns((1.2, 1))
    with left:
        snapshot = _display_optional_media(alert, "snapshot_url", "snapshot_path")
        face_media = _display_optional_media(alert, "face_crop_url", "face_crop_path")
        badge_media = _display_optional_media(alert, "badge_crop_url", "badge_crop_path")
        clip_media = _display_optional_media(alert, "clip_url", "clip_path")
        if snapshot:
            st.image(snapshot, caption="现场截图", use_container_width=True)
        if clip_media:
            st.video(clip_media)
        media_cols = st.columns(2)
        if face_media:
            media_cols[0].image(face_media, caption="人脸证据", use_container_width=True)
        if badge_media:
            media_cols[1].image(badge_media, caption="工牌证据", use_container_width=True)

    with right:
        st.write(f"事件编号：`{alert.get('event_no') or alert.get('alert_id')}`")
        st.write(f"状态：`{_status_label(alert.get('status'))}`")
        st.write(f"时间：`{alert.get('created_at')}`")
        st.write(f"地点：`{alert.get('site_name')}/{alert.get('building_name')}/{alert.get('floor_name')}/{alert.get('workshop_name')}/{alert.get('zone_name')}`")
        st.write(f"识别来源：`{alert.get('identity_source')}`")
        st.write(f"识别状态：`{alert.get('identity_status')}`")
        st.write(f"识别置信度：`{alert.get('identity_confidence')}`")
        st.write(f"人员：`{alert.get('person_name', 'Unknown')}` / `{alert.get('employee_id') or 'N/A'}`")
        st.write(f"部门：`{alert.get('department')}`")
        if alert.get("review_note"):
            st.warning(alert["review_note"])
        if alert.get("governance_note"):
            st.info(alert["governance_note"])

    actions = repository.list_alert_actions(alert_id=alert["alert_id"], limit=100)
    notifications = repository.list_notification_logs(alert_id=alert["alert_id"], limit=100)
    history_col, notify_col = st.columns(2)
    with history_col:
        st.subheader("处理记录")
        st.dataframe(pd.DataFrame(actions) if actions else pd.DataFrame(), hide_index=True, use_container_width=True)
    with notify_col:
        st.subheader("通知记录")
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
            st.subheader("转派")
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
            st.subheader("状态流转")
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
    st.subheader("摄像头管理")
    st.dataframe(_camera_frame(cameras), hide_index=True, use_container_width=True)

    existing_options = {"新建摄像头": None}
    for camera in settings.cameras:
        existing_options[f"{camera.camera_id} | {camera.camera_name}"] = camera
    selected = st.selectbox("配置对象", list(existing_options.keys()))
    current = existing_options[selected]

    with st.form("camera_form"):
        camera_id = st.text_input("camera_id", value=current.camera_id if current else "")
        camera_name = st.text_input("camera_name", value=current.camera_name if current else "")
        source = st.text_input("source", value=current.source if current else "0")
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
        payload = {
            "camera_id": camera_id,
            "camera_name": camera_name or camera_id,
            "source": source,
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
    st.subheader("统计报表")
    if not alerts:
        st.info("暂无报表数据。")
        return

    report_df = pd.DataFrame(alerts)
    report_df["created_at_dt"] = report_df["created_at"].apply(parse_timestamp)
    total_alerts = len(report_df)
    unique_people = report_df["employee_id"].fillna("unknown").nunique()
    closure_rate = float((report_df["status"].isin(["remediated", "ignored", "false_positive"])).mean() * 100)
    false_positive_rate = float((report_df["status"] == "false_positive").mean() * 100)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("告警总数", total_alerts)
    col2.metric("涉及人数", unique_people)
    col3.metric("闭环率", f"{closure_rate:.1f}%")
    col4.metric("误报率", f"{false_positive_rate:.1f}%")

    dept_rank = report_df.groupby("department").size().rename("alerts").sort_values(ascending=False)
    person_rank = (
        report_df.groupby(["person_name", "employee_id"]).size().rename("alerts").sort_values(ascending=False).head(10)
    )
    status_dist = report_df.groupby("status").size().rename("alerts")
    daily_trend = report_df.groupby(report_df["created_at_dt"].dt.strftime("%Y-%m-%d")).size().rename("alerts")

    chart_col, table_col = st.columns(2)
    with chart_col:
        st.subheader("每日趋势")
        st.line_chart(daily_trend)
        st.subheader("状态分布")
        st.bar_chart(status_dist)
    with table_col:
        st.subheader("部门排行")
        st.dataframe(dept_rank.reset_index(), hide_index=True, use_container_width=True)
        st.subheader("人员违规 Top10")
        st.dataframe(person_rank.reset_index(), hide_index=True, use_container_width=True)

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
    st.download_button(
        "导出 CSV",
        data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="safety_alert_report.csv",
        mime="text/csv",
    )


def render_notification_center(settings, repository, notifier: NotificationService) -> None:
    st.subheader("通知中心")
    logs = repository.list_notification_logs(limit=200)
    st.dataframe(pd.DataFrame(logs) if logs else pd.DataFrame(), hide_index=True, use_container_width=True)

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
    st.subheader("Hard Cases 回流")
    cases = repository.list_hard_cases(limit=200)
    if not cases:
        st.info("还没有 hard cases。把工单标记为误报后会自动进入这里。")
        return
    st.dataframe(pd.DataFrame(cases), hide_index=True, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="Safety Helmet Product Console", layout="wide")
    st.title("Safety Helmet Detection System")
    st.caption("产品化控制台：大屏、复核、工单、通知、摄像头、报表、硬例回流")

    settings = load_settings()
    repository = build_repository(settings)
    directory = PersonDirectory(settings)
    evidence_store = EvidenceStore(settings)
    notifier = NotificationService(settings, repository)

    st.sidebar.header("控制台")
    role = st.sidebar.selectbox("当前角色", list(ROLE_OPTIONS.keys()), format_func=lambda value: ROLE_OPTIONS[value])
    operator = st.sidebar.text_input("当前操作人", value="demo.operator")
    allowed_pages = ROLE_PAGES[role]
    page = st.sidebar.radio(
        "页面",
        allowed_pages,
    )
    auto_refresh = st.sidebar.checkbox("自动刷新", value=page == "总览")
    refresh_seconds = st.sidebar.slider("刷新秒数", min_value=5, max_value=60, value=10, step=5)

    since_days = st.sidebar.slider("筛选最近天数", min_value=1, max_value=30, value=7)
    all_cameras = repository.list_cameras()
    camera_ids = [camera.get("camera_id") for camera in all_cameras if camera.get("camera_id")]
    all_alerts = repository.list_alerts(limit=1000)
    filtered_alerts = _filter_alerts(
        all_alerts,
        date_from=datetime.now(tz=UTC) - timedelta(days=since_days),
    )

    st.sidebar.caption(
        f"后端：{repository.backend_name} | 邮件通知：{'已配置' if settings.notifications.is_email_configured else '未配置'}"
    )

    if page == "总览":
        render_overview(repository, filtered_alerts, all_cameras)
    elif page == "人工复核台":
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

    st.subheader("运行配置")
    st.code(
        "\n".join(
            [
                f"Config path: {settings.config_path}",
                f"Model path: {settings.resolve_path(settings.model.path)}",
                f"Tracking provider: {settings.tracking.provider}",
                f"Clip pre/post seconds: {settings.clip.pre_seconds}/{settings.clip.post_seconds}",
                f"Identity provider: {settings.identity.provider}",
                f"Storage private bucket: {settings.security.use_private_bucket}",
            ]
        )
    )

    if auto_refresh and page == "总览":
        time.sleep(refresh_seconds)
        st.rerun()


if __name__ == "__main__":
    main()
