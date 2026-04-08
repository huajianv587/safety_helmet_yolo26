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
from helmet_monitoring.services.operations import restore_backup
from helmet_monitoring.storage.repository import build_repository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore a backup archive into the current repo workspace.")
    parser.add_argument("backup_path", help="Backup archive path.")
    parser.add_argument("--config", default=None, help="Runtime config path.")
    parser.add_argument("--actor", default="system", help="Audit actor.")
    parser.add_argument("--note", default=None, help="Optional restore note.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    repository = build_repository(settings)
    record = restore_backup(
        settings,
        args.backup_path,
        actor=args.actor,
        note=args.note,
        repository=repository,
    )
    print(f"restored_files={record['restored_files']}")
    print(f"restored_from={record['backup_path']}")


if __name__ == "__main__":
    main()
