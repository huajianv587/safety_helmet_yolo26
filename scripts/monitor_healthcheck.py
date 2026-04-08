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
from helmet_monitoring.services.operations import operations_paths, service_health_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor heartbeat healthcheck for Docker and ops scripts.")
    parser.add_argument("--config", default=None, help="Runtime config path.")
    parser.add_argument("--stale-after", type=int, default=90, help="Stale threshold in seconds.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    report = service_health_report(
        operations_paths(settings)["monitor_health"],
        service_name="monitor",
        stale_after_seconds=args.stale_after,
    )
    print(f"monitor_status={report['status']}")
    print(f"monitor_detail={report['detail']}")
    if report["status"] != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
