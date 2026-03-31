from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings


UTC = timezone.utc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dry-run or apply local evidence retention cleanup.")
    parser.add_argument("--apply", action="store_true", help="Actually delete expired local evidence files.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings("configs/runtime.json")
    root = settings.resolve_path(settings.persistence.snapshot_dir)
    cutoff = datetime.now(tz=UTC) - timedelta(days=settings.security.evidence_retention_days)
    expired_paths: list[Path] = []

    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if modified < cutoff:
                expired_paths.append(path)

    print(f"snapshot_root={root}")
    print(f"retention_days={settings.security.evidence_retention_days}")
    print(f"expired_files={len(expired_paths)}")

    if not args.apply:
        print("mode=dry-run")
        return

    removed = 0
    for path in expired_paths:
        try:
            path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    print(f"mode=apply removed_files={removed}")


if __name__ == "__main__":
    main()
