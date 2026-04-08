from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.operations import activate_release, create_release_snapshot, ensure_operations_state, rollback_release
from helmet_monitoring.storage.repository import build_repository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create, activate, inspect, and rollback release snapshots.")
    parser.add_argument("--config", default=None, help="Runtime config path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot", help="Create a release snapshot.")
    snapshot.add_argument("--name", default=None, help="Release name.")
    snapshot.add_argument("--activate", action="store_true", help="Activate immediately after snapshot.")
    snapshot.add_argument("--actor", default="system", help="Audit actor.")
    snapshot.add_argument("--note", default=None, help="Release note.")

    activate = subparsers.add_parser("activate", help="Activate an existing release.")
    activate.add_argument("name", help="Release name.")
    activate.add_argument("--actor", default="system", help="Audit actor.")
    activate.add_argument("--note", default=None, help="Activation note.")

    rollback = subparsers.add_parser("rollback", help="Rollback to a previous release.")
    rollback.add_argument("--steps", type=int, default=1, help="How many distinct activations to roll back.")
    rollback.add_argument("--actor", default="system", help="Audit actor.")
    rollback.add_argument("--note", default=None, help="Rollback note.")

    status = subparsers.add_parser("status", help="Show release registry JSON.")
    status.add_argument("--json", action="store_true", help="Print JSON only.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    repository = build_repository(settings)
    if args.command == "snapshot":
        record = create_release_snapshot(
            settings,
            release_name=args.name,
            activate=args.activate,
            actor=args.actor,
            note=args.note,
            repository=repository,
        )
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return
    if args.command == "activate":
        record = activate_release(settings, release_name=args.name, actor=args.actor, note=args.note, repository=repository)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return
    if args.command == "rollback":
        record = rollback_release(settings, steps=args.steps, actor=args.actor, note=args.note, repository=repository)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return

    registry = json.loads(ensure_operations_state(settings)["release_registry"].read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps(registry, ensure_ascii=False, indent=2))
    else:
        print(f"active_release={registry.get('active_release')}")
        print(f"release_count={len(registry.get('releases', []))}")
        print(json.dumps(registry, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
