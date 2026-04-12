from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import json

from supabase import create_client

from helmet_monitoring.core.config import load_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync person_registry.json into the Supabase persons table.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    return parser.parse_args()


def _sync_people(client, payload: list[dict]) -> set[str]:
    ignored_columns: set[str] = set()
    while True:
        filtered_payload = [{key: value for key, value in item.items() if key not in ignored_columns} for item in payload]
        try:
            client.table("persons").upsert(filtered_payload, on_conflict="person_id").execute()
            return ignored_columns
        except Exception as exc:
            match = re.search(r"Could not find the '([^']+)' column", str(exc))
            if not match:
                raise
            missing_column = match.group(1)
            if missing_column in ignored_columns:
                raise
            ignored_columns.add(missing_column)


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    registry_path = settings.resolve_path(settings.identity.registry_path)
    if not registry_path.exists():
        raise FileNotFoundError(f"Person registry not found: {registry_path}")
    if not settings.supabase.is_configured:
        raise RuntimeError("Supabase credentials are not configured in .env")

    with registry_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    client = create_client(settings.supabase.url, settings.supabase.service_role_key)
    ignored_columns = _sync_people(client, payload)
    print(f"synced_people={len(payload)}")
    if ignored_columns:
        print(f"ignored_columns={','.join(sorted(ignored_columns))}")


if __name__ == "__main__":
    main()
