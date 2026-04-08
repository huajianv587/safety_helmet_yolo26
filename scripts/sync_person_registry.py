from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import json

from supabase import create_client

from helmet_monitoring.core.config import load_settings


def main() -> None:
    settings = load_settings("configs/runtime.json")
    registry_path = settings.resolve_path(settings.identity.registry_path)
    if not registry_path.exists():
        raise FileNotFoundError(f"Person registry not found: {registry_path}")
    if not settings.supabase.is_configured:
        raise RuntimeError("Supabase credentials are not configured in .env")

    with registry_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    client = create_client(settings.supabase.url, settings.supabase.service_role_key)
    client.table("persons").upsert(payload, on_conflict="person_id").execute()
    print(f"synced_people={len(payload)}")


if __name__ == "__main__":
    main()
