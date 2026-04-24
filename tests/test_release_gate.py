from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.api.app import app
from helmet_monitoring.services.auth import hash_password


def _write_config(root: Path) -> Path:
    config = {
        "repository_backend": "local",
        "persistence": {
            "snapshot_dir": str(root / "captures"),
            "runtime_dir": str(root / "runtime"),
            "upload_to_supabase_storage": False,
        },
        "notifications": {"enabled": False, "email_enabled": False},
        "cameras": [],
    }
    path = root / "runtime.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return path


def _auth_env(root: Path) -> dict[str, str]:
    return {
        "HELMET_AUTH_USERS_FILE": str(root / "auth_users.json"),
        "HELMET_AUTH_ATTEMPTS_FILE": str(root / "auth_attempts.json"),
        "HELMET_AUTH_TOKEN_SECRET": "release-gate-test-secret",
        "HELMET_AUTH_USERS_JSON": json.dumps(
            [
                {
                    "username": "admin_gate",
                    "role": "admin",
                    "display_name": "Admin Gate",
                    "password_hash": hash_password("GatePass!2026"),
                }
            ]
        ),
    }


def _login(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/login", json={"username": "admin_gate", "password": "GatePass!2026"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_release_activation_is_blocked_when_quality_gate_is_not_ready(tmp_path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("HELMET_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("HELMET_STORAGE_BACKEND", "local")
    for key, value in _auth_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        "helmet_monitoring.api.app._release_gate_status",
        lambda *_args, **_kwargs: {
            "quality_ready": False,
            "readiness_ready": True,
            "quality_payload": {"promotion_gate": {"status": "review_required", "reason": "pilot replay not ready"}},
            "readiness_blockers": [],
        },
    )
    monkeypatch.setattr(
        "helmet_monitoring.api.app.activate_release",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("activate_release should not be called")),
    )

    client = TestClient(app)
    headers = _login(client)
    response = client.post(
        "/api/v1/helmet/ops/releases/activate",
        headers=headers,
        json={"release_name": "candidate-001", "confirm_text": "HELMET OPS"},
    )
    assert response.status_code == 409
    payload = response.json()
    assert payload["detail"]["quality_status"] == "review_required"
