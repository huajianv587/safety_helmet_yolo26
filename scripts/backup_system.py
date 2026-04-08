from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.operations import create_backup
from helmet_monitoring.storage.repository import build_repository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a runtime backup for configs, registries, releases, and feedback assets.")
    parser.add_argument("--config", default=None, help="Runtime config path.")
    parser.add_argument("--name", default=None, help="Backup archive name without extension.")
    parser.add_argument("--include-captures", action="store_true", help="Include artifacts/captures in the backup.")
    parser.add_argument("--actor", default="system", help="Audit actor.")
    parser.add_argument("--note", default=None, help="Optional backup note.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    repository = build_repository(settings)
    record = create_backup(
        settings,
        include_captures=args.include_captures,
        backup_name=args.name,
        actor=args.actor,
        note=args.note,
        repository=repository,
    )
    print(f"backup_name={record['backup_name']}")
    print(f"backup_path={record['backup_path']}")
    print(f"backup_files={record['file_count']}")


if __name__ == "__main__":
    main()
