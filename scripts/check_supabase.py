from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.storage.evidence_store import EvidenceStore
from helmet_monitoring.storage.repository import build_repository


def main() -> None:
    settings = load_settings("configs/runtime.json")
    repository = build_repository(settings)
    cameras = repository.list_cameras()
    print(f"backend={repository.backend_name}")
    print(f"camera_count={len(cameras)}")
    if repository.backend_name == "supabase":
        people_count = 0
        profile_count = 0
        try:
            people_response = repository.client.table("persons").select("person_id", count="exact").limit(1).execute()
            people_count = people_response.count or 0
            repository.client.table("alerts").select("person_name").limit(1).execute()
            print("identity_extension=ready")
        except Exception:
            print("identity_extension=missing")
        try:
            profile_response = (
                repository.client.table("person_face_profiles").select("profile_id", count="exact").limit(1).execute()
            )
            profile_count = profile_response.count or 0
            repository.client.table("alerts").select("identity_confidence").limit(1).execute()
            print("identity_ai_extension=ready")
        except Exception:
            print("identity_ai_extension=missing")
        try:
            repository.client.table("alert_actions").select("action_id").limit(1).execute()
            repository.client.table("notification_logs").select("notification_id").limit(1).execute()
            repository.client.table("hard_cases").select("case_id").limit(1).execute()
            repository.client.table("audit_logs").select("audit_id").limit(1).execute()
            repository.client.table("alerts").select("event_no").limit(1).execute()
            print("product_extension=ready")
        except Exception:
            print("product_extension=missing")
        print(f"person_count={people_count}")
        print(f"face_profile_count={profile_count}")
        try:
            store = EvidenceStore(settings)
            print(f"storage_bucket_ready={str(store._ensure_bucket()).lower()}")
        except Exception:
            print("storage_bucket_ready=false")


if __name__ == "__main__":
    main()
