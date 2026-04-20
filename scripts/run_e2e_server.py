from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import uvicorn


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.services.auth import hash_password
from helmet_monitoring.core.config import load_settings
from helmet_monitoring.storage.repository import build_repository


def _prepare_e2e_config() -> Path:
    source = REPO_ROOT / "configs" / "runtime.quicktest.json"
    target = REPO_ROOT / "artifacts" / "runtime" / "e2e" / "runtime.quicktest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def _set_default_env() -> None:
    if not os.getenv("HELMET_CONFIG_PATH"):
        os.environ["HELMET_CONFIG_PATH"] = str(_prepare_e2e_config())
    os.environ.setdefault("HELMET_STORAGE_BACKEND", "local")
    os.environ.setdefault("HELMET_CORS_ORIGINS", "*")
    os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))
    os.environ.setdefault("HELMET_AUTH_USERS_FILE", str(REPO_ROOT / "artifacts" / "runtime" / "e2e" / "auth_users.json"))
    os.environ.setdefault("HELMET_AUTH_ATTEMPTS_FILE", str(REPO_ROOT / "artifacts" / "runtime" / "e2e" / "auth_attempts.json"))
    admin_username = os.getenv("HELMET_E2E_ADMIN_USERNAME", "jianghuajian99@gmail.com")
    admin_password = os.getenv("HELMET_E2E_ADMIN_PASSWORD", "AdminPass!2026")
    if not os.getenv("HELMET_AUTH_USERS_JSON") and not os.getenv("HELMET_AUTH_ADMIN_PASSWORD_HASH"):
        os.environ["HELMET_AUTH_USERS_JSON"] = json.dumps(
            [
                {
                    "username": admin_username,
                    "role": "admin",
                    "display_name": "Operations Admin",
                    "email": admin_username,
                    "password_hash": hash_password(admin_password),
                },
                {
                    "username": "viewer_readonly",
                    "role": "viewer",
                    "display_name": "Viewer Readonly",
                    "email": "viewer@example.com",
                    "password_hash": hash_password("ViewerPass!2026"),
                },
            ],
            ensure_ascii=False,
        )


def _seed_e2e_data() -> None:
    settings = load_settings()
    repository = build_repository(settings)
    repository.upsert_camera(
        {
            "camera_id": "cam-local-001",
            "camera_name": "Laptop Camera",
            "location": "Local Workstation",
            "department": "Safety",
            "site_name": "Demo Site",
            "building_name": "HQ",
            "floor_name": "Floor 1",
            "workshop_name": "Safety Lab",
            "zone_name": "Desktop",
            "last_status": "running",
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "last_fps": 20.0,
        }
    )
    if repository.get_alert("alert-e2e-001") is not None:
        return
    snapshot = settings.resolve_path(settings.persistence.snapshot_dir) / "alerts" / "e2e-demo.jpg"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if not snapshot.exists():
        snapshot.write_bytes(b"e2e-demo-image")
    repository.insert_alert(
        {
            "alert_id": "alert-e2e-001",
            "event_no": "E2E-001",
            "camera_id": "cam-local-001",
            "camera_name": "Laptop Camera",
            "location": "Local Workstation",
            "department": "Safety",
            "site_name": "Demo Site",
            "building_name": "HQ",
            "floor_name": "Floor 1",
            "workshop_name": "Safety Lab",
            "zone_name": "Desktop",
            "status": "pending",
            "identity_status": "review_required",
            "identity_source": "face",
            "person_id": None,
            "person_name": "Unknown Worker",
            "employee_id": None,
            "risk_level": "high",
            "snapshot_path": str(snapshot),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def main() -> None:
    _set_default_env()
    _seed_e2e_data()
    port = int(os.getenv("E2E_PORT", "39123"))
    uvicorn.run("helmet_monitoring.api.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
