from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.api.app import app
from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.auth import hash_password
from helmet_monitoring.storage.repository import build_repository


def _write_config(root: Path) -> Path:
    registry_path = root / "persons.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "person_id": "person-001",
                    "name": "Demo Worker",
                    "employee_id": "E001",
                    "department": "Safety",
                    "status": "active",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = {
        "repository_backend": "local",
        "persistence": {
            "snapshot_dir": str(root / "captures"),
            "runtime_dir": str(root / "runtime"),
            "upload_to_supabase_storage": False,
            "keep_local_copy": True,
        },
        "identity": {"registry_path": str(registry_path)},
        "notifications": {"enabled": False, "email_enabled": False},
        "cameras": [
            {
                "camera_id": "cam-001",
                "camera_name": "Gate Camera",
                "source": "0",
                "location": "Gate",
                "department": "Safety",
                "enabled": True,
                "site_name": "Plant A",
                "building_name": "Main",
                "floor_name": "F1",
                "workshop_name": "Gate",
                "zone_name": "Entrance",
            },
            {
                "camera_id": "cam-002",
                "camera_name": "Disabled Yard Camera",
                "source": "1",
                "location": "Yard",
                "department": "Safety",
                "enabled": False,
                "site_name": "Plant A",
                "building_name": "Yard",
                "floor_name": "F0",
                "workshop_name": "Yard",
                "zone_name": "Outer Gate",
            }
        ],
    }
    config_path = root / "runtime.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return config_path


def _auth_env(root: Path) -> dict[str, str]:
    return {
        "HELMET_AUTH_USERS_FILE": str(root / "auth_users.json"),
        "HELMET_AUTH_ATTEMPTS_FILE": str(root / "auth_attempts.json"),
        "HELMET_AUTH_ADMIN_USERNAME": "",
        "HELMET_AUTH_ADMIN_PASSWORD_HASH": "",
        "HELMET_AUTH_USERS_JSON": json.dumps(
            [
                {
                    "username": "admin_ops",
                    "role": "admin",
                    "display_name": "Operations Admin",
                    "password_hash": hash_password("AdminPass!2026"),
                },
                {
                    "username": "viewer_readonly",
                    "role": "viewer",
                    "display_name": "Viewer",
                    "password_hash": hash_password("ViewerPass!2026"),
                },
            ]
        ),
    }


def _seed_alert(root: Path) -> None:
    settings = load_settings(str(root / "runtime.json"))
    repository = build_repository(settings)
    snapshot = root / "captures" / "alerts" / "demo.jpg"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(b"demo-image")
    repository.upsert_camera(
        {
            "camera_id": "cam-001",
            "camera_name": "Gate Camera",
            "location": "Gate",
            "department": "Safety",
            "last_status": "running",
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    repository.insert_alert(
        {
            "alert_id": "alert-001",
            "event_no": "EVT-001",
            "camera_id": "cam-001",
            "camera_name": "Gate Camera",
            "location": "Gate",
            "department": "Safety",
            "status": "pending",
            "identity_status": "review_required",
            "identity_source": "face",
            "person_id": None,
            "person_name": "Unknown",
            "employee_id": None,
            "risk_level": "high",
            "snapshot_path": str(snapshot),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _seed_alert_at(root: Path, *, alert_id: str, event_no: str, camera_id: str, camera_name: str, status: str, created_at: datetime) -> None:
    settings = load_settings(str(root / "runtime.json"))
    repository = build_repository(settings)
    snapshot = root / "captures" / "alerts" / f"{alert_id}.jpg"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(b"demo-image")
    repository.insert_alert(
        {
            "alert_id": alert_id,
            "event_no": event_no,
            "camera_id": camera_id,
            "camera_name": camera_name,
            "location": "Gate",
            "department": "Safety",
            "status": status,
            "identity_status": "review_required",
            "identity_source": "face",
            "person_id": None,
            "person_name": "Unknown",
            "employee_id": None,
            "risk_level": "high",
            "snapshot_path": str(snapshot),
            "created_at": created_at.isoformat(),
        }
    )


def test_root_and_app_static_are_served(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    client = TestClient(app)
    root = client.get("/")
    assert root.status_code == 200
    assert "Safety Helmet Command Center" in root.text
    assert "/app/#/dashboard" in root.text

    app_response = client.get("/app")
    assert app_response.status_code in {200, 307}
    assert client.get("/health").json()["status"] == "ok"


def test_auth_overview_and_media_token(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    _seed_alert(tmp_path)

    client = TestClient(app)
    login = client.post("/auth/login", json={"username": "admin_ops", "password": "AdminPass!2026"})
    assert login.status_code == 200
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    overview = client.get("/api/v1/helmet/platform/overview?days=7", headers=headers)
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["metrics"]["today_alerts"] == 1
    assert payload["metrics"]["review_required"] == 1
    assert "snapshot_path" not in payload["evidence_alerts"][0]
    media_url = payload["evidence_alerts"][0]["snapshot_display_url"]
    assert media_url.startswith("/api/v1/helmet/media/")
    assert client.get(media_url).status_code == 200


def test_guest_can_read_core_console_apis_without_token(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    _seed_alert(tmp_path)

    client = TestClient(app)
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "guest"
    assert "/config" in me.json()["user"]["routes"]

    for path in (
        "/api/v1/helmet/platform/overview?days=7",
        "/api/v1/helmet/alerts?days=30",
        "/api/v1/helmet/alerts/alert-001",
        "/api/v1/helmet/cameras",
        "/api/v1/helmet/cameras/live",
        "/api/v1/helmet/reports/summary?days=30",
        "/api/v1/helmet/notifications",
        "/api/v1/helmet/hard-cases",
        "/api/v1/helmet/config/summary",
        "/api/v1/helmet/visitor-evidence",
    ):
        response = client.get(path)
        assert response.status_code == 200, path

    alert_payload = client.get("/api/v1/helmet/alerts/alert-001").json()["alert"]
    assert "snapshot_path" not in alert_payload
    assert alert_payload["snapshot_display_url"].startswith("/api/v1/helmet/media/")
    assert alert_payload["snapshot_media_state"] == "available"

    compact = client.get("/api/v1/helmet/alerts?days=30&mode=compact&include_media=false").json()
    assert compact["items"][0]["snapshot_display_url"] is None
    assert compact["items"][0]["snapshot_media_state"] == "available"
    identity_filtered = client.get("/api/v1/helmet/alerts?days=30&identity_status=review_required").json()
    assert identity_filtered["total"] == 1

    reports = client.get("/api/v1/helmet/reports/summary?days=30").json()
    assert reports["rows_total"] >= 1
    assert len(reports["rows"]) <= 20
    assert reports["rows_truncated"] in {True, False}
    rows = client.get("/api/v1/helmet/reports/rows?days=30&limit=10&offset=0").json()
    assert rows["total"] >= 1
    assert len(rows["items"]) == 1


def test_guest_can_create_visitor_evidence_and_overview_exposes_it(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    client = TestClient(app)
    created = client.post(
        "/api/v1/helmet/visitor-evidence",
        data={
            "visitor_name": "Alice Visitor",
            "visitor_company": "Demo Contractor",
            "visit_reason": "Site walkthrough",
            "note": "Helmet briefing completed.",
            "camera_id": "cam-001",
        },
        files={"snapshot": ("visitor.jpg", b"\xff\xd8visitor\xff\xd9", "image/jpeg")},
    )
    assert created.status_code == 200
    record = created.json()["record"]
    assert record["visitor_name"] == "Alice Visitor"
    assert record["created_by"] == "guest"
    assert record["snapshot_display_url"].startswith("/api/v1/helmet/media/")
    assert "snapshot_path" not in record

    listed = client.get("/api/v1/helmet/visitor-evidence?limit=10")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["record_id"] == record["record_id"]

    overview = client.get("/api/v1/helmet/platform/overview?days=7")
    assert overview.status_code == 200
    summary = overview.json()["visitor_evidence_summary"]
    assert summary["total"] == 1
    assert summary["items"][0]["record_id"] == record["record_id"]


def test_overview_hotspots_fallback_and_reports_filters_are_consistent(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    _seed_alert_at(
        tmp_path,
        alert_id="alert-yesterday",
        event_no="EVT-YDAY",
        camera_id="cam-001",
        camera_name="Gate Camera",
        status="pending",
        created_at=yesterday,
    )
    _seed_alert_at(
        tmp_path,
        alert_id="alert-assigned",
        event_no="EVT-ASSIGNED",
        camera_id="cam-002",
        camera_name="Disabled Yard Camera",
        status="assigned",
        created_at=yesterday,
    )

    client = TestClient(app)
    overview = client.get("/api/v1/helmet/platform/overview?days=7")
    assert overview.status_code == 200
    hotspots = overview.json()["hotspots"]
    assert hotspots["mode"] == "fallback_7d"
    assert hotspots["departments"][0]["department"] == "Safety"
    assert hotspots["cameras"]

    summary = client.get("/api/v1/helmet/reports/summary?days=30&status=assigned&camera_id=cam-002")
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["metrics"]["alert_volume"] == 1
    assert summary_payload["rows_total"] == 1
    assert summary_payload["applied_filters"]["statuses"] == ["assigned"]
    assert summary_payload["applied_filters"]["camera_ids"] == ["cam-002"]

    rows = client.get("/api/v1/helmet/reports/rows?days=30&status=assigned&camera_id=cam-002&limit=20&offset=0")
    assert rows.status_code == 200
    rows_payload = rows.json()
    assert rows_payload["total"] == 1
    assert rows_payload["items"][0]["camera_id"] == "cam-002"
    assert rows_payload["items"][0]["status"] == "assigned"


def test_public_register_defaults_to_admin_and_change_password(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    client = TestClient(app)
    weak = client.post("/auth/register", json={"username": "weak@example.test", "password": "short"})
    assert weak.status_code == 400

    payload = {
        "username": "New_User@Example.Test",
        "email": "New_User@Example.Test",
        "display_name": "New User",
        "password": "StartPass!2026",
        "remember": True,
    }
    registered = client.post("/auth/register", json=payload)
    assert registered.status_code == 200
    body = registered.json()
    assert body["user"]["username"] == "new_user@example.test"
    assert body["user"]["role"] == "admin"
    assert "account.manage" in body["user"]["permissions"]
    assert "password_hash" not in registered.text

    duplicate = client.post("/auth/register", json=payload)
    assert duplicate.status_code == 409

    headers = {"Authorization": f"Bearer {body['token']}"}
    accounts = client.get("/api/v1/helmet/accounts", headers=headers)
    assert accounts.status_code == 200
    assert "new_user@example.test" in accounts.text
    assert "password_hash" not in accounts.text

    changed = client.post("/auth/change-password", headers=headers, json={"new_password": "ChangedPass!2026"})
    assert changed.status_code == 200
    assert changed.json()["changed"] == "new_user@example.test"

    old_login = client.post("/auth/login", json={"username": "new_user@example.test", "password": "StartPass!2026"})
    assert old_login.status_code == 401
    new_login = client.post("/auth/login", json={"username": "new_user@example.test", "password": "ChangedPass!2026"})
    assert new_login.status_code == 200


def test_guest_writes_are_rejected_and_admin_writes_work(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    _seed_alert(tmp_path)

    client = TestClient(app)
    assert client.post("/api/v1/helmet/cameras", json={"camera_id": "guest-cam", "source": "0"}).status_code == 401
    assert client.post("/api/v1/helmet/alerts/alert-001/assign", json={"assignee": "ops"}).status_code == 401
    assert client.get("/api/v1/helmet/accounts").status_code == 401

    token = client.post("/auth/login", json={"username": "admin_ops", "password": "AdminPass!2026"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    camera = client.post(
        "/api/v1/helmet/cameras",
        headers=headers,
        json={"camera_id": "cam-local-2", "camera_name": "Local 2", "source": "1", "department": "Safety"},
    )
    assert camera.status_code == 200
    assigned = client.post(
        "/api/v1/helmet/alerts/alert-001/assign",
        headers=headers,
        json={"assignee": "ops-lead", "assignee_email": "ops@example.com", "note": "check"},
    )
    assert assigned.status_code == 200
    accounts = client.get("/api/v1/helmet/accounts", headers=headers)
    assert accounts.status_code == 200
    assert "password_hash" not in accounts.text


def test_config_summary_does_not_expose_secrets(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    monkeypatch.setenv("SMTP_PASSWORD", "super-secret-smtp")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "super-secret-service-role")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    client = TestClient(app)
    response = client.get("/api/v1/helmet/config/summary")
    assert response.status_code == 200
    text = response.text
    assert "super-secret-smtp" not in text
    assert "super-secret-service-role" not in text
    lowered = text.lower()
    assert "password_hash" not in lowered
    assert "smtp_password" not in lowered


def test_camera_upsert_rejects_plain_remote_sources(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    client = TestClient(app)
    token = client.post("/auth/login", json={"username": "admin_ops", "password": "AdminPass!2026"}).json()["token"]
    response = client.post(
        "/api/v1/helmet/cameras",
        headers={"Authorization": f"Bearer {token}"},
        json={"camera_id": "cam-remote", "source": "rtsp://camera.example/live"},
    )
    assert response.status_code == 400


def test_live_camera_frame_api_is_readonly_and_safe(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    live_dir = tmp_path / "runtime" / "ops" / "live_frames"
    live_dir.mkdir(parents=True)
    frame_path = live_dir / "cam-001.jpg"
    frame_path.write_bytes(b"\xff\xd8helmet-live-frame\xff\xd9")

    client = TestClient(app)
    live = client.get("/api/v1/helmet/cameras/live")
    assert live.status_code == 200
    body = live.json()
    lookup = {item["camera_id"]: item for item in body["items"]}
    assert set(lookup) >= {"cam-001", "cam-002"}
    assert lookup["cam-001"]["has_live_frame"] is True
    assert lookup["cam-001"]["frame_url"] == "/api/v1/helmet/cameras/cam-001/frame.jpg"
    assert lookup["cam-001"]["display_group"] == "local"
    assert lookup["cam-002"]["display_group"] == "disabled"
    assert lookup["cam-002"]["selectable"] is True
    text = live.text.lower()
    assert "rtsp://" not in text
    assert "password" not in text
    assert str(tmp_path).lower() not in text.lower()

    frame = client.get("/api/v1/helmet/cameras/cam-001/frame.jpg")
    assert frame.status_code == 200
    assert frame.headers["content-type"].startswith("image/jpeg")
    assert frame.headers["cache-control"].startswith("no-store")
    assert frame.content.startswith(b"\xff\xd8")

    assert client.get("/api/v1/helmet/cameras/unknown/frame.jpg").status_code == 404
    assert client.get("/api/v1/helmet/cameras/..%2Fsecret/frame.jpg").status_code in {400, 404}
    frame_path.unlink()
    assert client.get("/api/v1/helmet/cameras/cam-001/stream.mjpeg").status_code == 404
