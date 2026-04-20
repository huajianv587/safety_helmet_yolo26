from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.api.app import app
from helmet_monitoring.services.auth import hash_password
from helmet_monitoring.services.operations_studio import validate_capability_matrix


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
                    "aliases": ["worker"],
                    "badge_keywords": ["E001"],
                    "default_camera_ids": ["cam-001"],
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
        "HELMET_AUTH_TOKEN_SECRET": "ops-test-token-secret",
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
                    "username": "manager_ops",
                    "role": "safety_manager",
                    "display_name": "Safety Manager",
                    "password_hash": hash_password("ManagerPass!2026"),
                },
                {
                    "username": "viewer_ops",
                    "role": "viewer",
                    "display_name": "Viewer",
                    "password_hash": hash_password("ViewerPass!2026"),
                },
            ]
        ),
    }


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    token = client.post("/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_capability_matrix_has_no_gaps() -> None:
    assert validate_capability_matrix() == []


def test_ops_routes_require_elevated_roles_and_keep_outputs_sanitized(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    monkeypatch.setenv("SMTP_PASSWORD", "secret-smtp")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret-supabase")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        "helmet_monitoring.services.operations_studio._load_latest_compare_report",
        lambda: {
            "baseline_model": "artifacts/models/baseline.pt",
            "candidate_model": "artifacts/models/candidate.pt",
            "conclusion": "review_required",
            "block_reasons": ["site benchmark still lacks labeled site_holdout samples"],
        },
    )

    client = TestClient(app)
    guest = client.get("/api/v1/helmet/ops/capabilities")
    assert guest.status_code == 401

    admin_headers = _login(client, "admin_ops", "AdminPass!2026")
    manager_headers = _login(client, "manager_ops", "ManagerPass!2026")
    viewer_headers = _login(client, "viewer_ops", "ViewerPass!2026")

    admin_me = client.get("/auth/me", headers=admin_headers).json()
    manager_me = client.get("/auth/me", headers=manager_headers).json()
    viewer_me = client.get("/auth/me", headers=viewer_headers).json()
    assert "/operations" in admin_me["user"]["routes"]
    assert "/operations" in manager_me["user"]["routes"]
    assert "/operations" not in viewer_me["user"]["routes"]

    capabilities = client.get("/api/v1/helmet/ops/capabilities", headers=manager_headers)
    assert capabilities.status_code == 200
    payload = capabilities.json()
    assert payload["summary"]["total"] > 0
    assert payload["coverage_errors"] == []

    for path in (
        "/api/v1/helmet/ops/readiness",
        "/api/v1/helmet/ops/services",
        "/api/v1/helmet/ops/identity/summary",
        "/api/v1/helmet/ops/model-feedback",
        "/api/v1/helmet/ops/quality-summary",
        "/api/v1/helmet/ops/evidence-delivery",
        "/api/v1/helmet/ops/backups",
        "/api/v1/helmet/ops/releases",
    ):
        response = client.get(path, headers=manager_headers)
        assert response.status_code == 200, path
        text = response.text.lower()
        assert str(tmp_path).lower() not in text
        assert "secret-smtp" not in text
        assert "secret-supabase" not in text
        assert "password_hash" not in text
        assert "rtsp://" not in text

    assert client.post("/api/v1/helmet/ops/backups", headers=manager_headers, json={}).status_code == 403

    quality = client.get("/api/v1/helmet/ops/quality-summary", headers=manager_headers)
    assert quality.status_code == 200
    quality_payload = quality.json()
    assert quality_payload["detector"]["state"] in {"ready", "review_required", "invalid"}
    assert quality_payload["badge_ocr"]["state"] in {"ready", "review_required", "invalid"}
    assert quality_payload["face_identity"]["state"] in {"ready", "review_required", "invalid"}
    assert quality_payload["active_thresholds"]["detector_confidence"] >= 0.52
    assert quality_payload["active_thresholds"]["alert_confidence"] >= 0.58
    assert quality_payload["recommended_thresholds"]["ocr_min_confidence"] >= 0.55
    assert quality_payload["site_benchmark"]["rules"]["allowed_labels"] == ["helmet", "no_helmet"]
    assert quality_payload["site_benchmark"]["rules"]["split_unit"] == "camera_id + date"
    assert quality_payload["pilot_video_eval"]["evaluation_mode"] in {
        "inventory_replay_proxy",
        "hard_case_replay",
        "compare_candidate_replay",
    }
    assert quality_payload["promotion_gate"]["status"] in {"ready", "review_required", "invalid"}
    assert "requirements" in quality_payload["promotion_gate"]
    assert quality_payload["latest_compare_report"]["conclusion"] == "review_required"
    assert quality_payload["artifacts"]["summary_json"].endswith(".json")
    assert quality_payload["artifacts"]["summary_markdown"].endswith(".md")
    assert quality_payload["artifacts"]["summary_text"].endswith(".txt")


def test_ops_write_endpoints_sanitize_path_like_fields(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    now = datetime.now(timezone.utc).isoformat()
    fake_backup_path = tmp_path / "artifacts" / "backups" / "demo-backup.zip"
    fake_release_path = tmp_path / "artifacts" / "releases" / "snapshots" / "demo-release.json"
    fake_export_dir = tmp_path / "artifacts" / "exports" / "model_feedback" / "export-001"
    fake_dataset_yaml = tmp_path / "artifacts" / "exports" / "model_feedback" / "dataset-001" / "feedback.yaml"

    fake_create_backup = lambda *args, **kwargs: {
        "backup_id": "backup-001",
        "backup_name": "demo-backup",
        "backup_path": str(fake_backup_path),
        "file_count": 3,
        "created_at": now,
    }
    fake_restore_backup = lambda *args, **kwargs: {
        "backup_path": str(fake_backup_path),
        "restored_files": 3,
        "restored_at": now,
    }
    fake_create_release = lambda *args, **kwargs: {
        "release_name": "demo-release",
        "config_snapshot": str(fake_release_path),
        "config_path": str(tmp_path / "runtime.json"),
        "model_path": str(tmp_path / "models" / "helmet.pt"),
        "created_at": now,
    }
    fake_activate_release = lambda *args, **kwargs: {
        "release_name": "demo-release",
        "config_snapshot": str(fake_release_path),
        "activated_at": now,
    }
    fake_rollback_release = lambda *args, **kwargs: {
        "release_name": "demo-release",
        "config_snapshot": str(fake_release_path),
        "activated_at": now,
    }
    monkeypatch.setattr("helmet_monitoring.api.app.create_backup", fake_create_backup)
    monkeypatch.setattr("helmet_monitoring.services.operations.create_backup", fake_create_backup)
    monkeypatch.setattr("helmet_monitoring.api.app.restore_backup", fake_restore_backup)
    monkeypatch.setattr("helmet_monitoring.services.operations.restore_backup", fake_restore_backup)
    monkeypatch.setattr("helmet_monitoring.api.app.create_release_snapshot", fake_create_release)
    monkeypatch.setattr("helmet_monitoring.services.operations.create_release_snapshot", fake_create_release)
    monkeypatch.setattr("helmet_monitoring.api.app.activate_release", fake_activate_release)
    monkeypatch.setattr("helmet_monitoring.services.operations.activate_release", fake_activate_release)
    monkeypatch.setattr("helmet_monitoring.api.app.rollback_release", fake_rollback_release)
    monkeypatch.setattr("helmet_monitoring.services.operations.rollback_release", fake_rollback_release)
    monkeypatch.setattr(
        "helmet_monitoring.api.app.export_feedback_cases",
        lambda *args, **kwargs: {
            "export_id": "export-001",
            "export_dir": str(fake_export_dir),
            "created_at": now,
            "cases": [{"alert_id": "alert-001", "snapshot_path": str(fake_export_dir / "snapshot.jpg"), "clip_path": str(fake_export_dir / "clip.mp4")}],
        },
    )
    monkeypatch.setattr(
        "helmet_monitoring.api.app.build_feedback_dataset",
        lambda *args, **kwargs: {
            "dataset_id": "dataset-001",
            "dataset_yaml": str(fake_dataset_yaml),
            "manifest_path": str(fake_dataset_yaml.with_suffix(".json")),
            "base_dataset_yaml": str(tmp_path / "configs" / "base.yaml"),
            "created_at": now,
        },
    )

    client = TestClient(app)
    admin_headers = _login(client, "admin_ops", "AdminPass!2026")

    backup = client.post("/api/v1/helmet/ops/backups", headers=admin_headers, json={})
    assert backup.status_code == 200
    assert str(tmp_path) not in backup.text
    assert "demo-backup.zip" in backup.text

    restore_requires_confirm = client.post(
        "/api/v1/helmet/ops/backups/restore",
        headers=admin_headers,
        json={"backup_path": str(fake_backup_path), "confirm_text": ""},
    )
    assert restore_requires_confirm.status_code == 400

    restore = client.post(
        "/api/v1/helmet/ops/backups/restore",
        headers=admin_headers,
        json={"backup_path": str(fake_backup_path), "confirm_text": "HELMET OPS"},
    )
    assert restore.status_code == 200
    assert str(tmp_path) not in restore.text

    snapshot = client.post("/api/v1/helmet/ops/releases/snapshot", headers=admin_headers, json={})
    assert snapshot.status_code == 200
    assert str(tmp_path) not in snapshot.text

    activate = client.post(
        "/api/v1/helmet/ops/releases/activate",
        headers=admin_headers,
        json={"release_name": "demo-release", "confirm_text": "HELMET OPS"},
    )
    assert activate.status_code == 200
    assert str(tmp_path) not in activate.text

    rollback = client.post(
        "/api/v1/helmet/ops/releases/rollback",
        headers=admin_headers,
        json={"steps": 1, "confirm_text": "HELMET OPS"},
    )
    assert rollback.status_code == 200
    assert str(tmp_path) not in rollback.text

    export = client.post("/api/v1/helmet/ops/model-feedback/export", headers=admin_headers, json={})
    assert export.status_code == 200
    assert str(tmp_path) not in export.text

    dataset = client.post("/api/v1/helmet/ops/model-feedback/dataset", headers=admin_headers, json={})
    assert dataset.status_code == 200
    assert str(tmp_path) not in dataset.text
