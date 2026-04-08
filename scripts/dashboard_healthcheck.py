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
from helmet_monitoring.services.operations import ping_dashboard, write_dashboard_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dashboard healthcheck for Docker and ops scripts.")
    parser.add_argument("--config", default=None, help="Runtime config path.")
    parser.add_argument("--url", default="http://127.0.0.1:8501/_stcore/health", help="Dashboard health URL.")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    detail, latency_ms = ping_dashboard(args.url, timeout_seconds=args.timeout)
    status = "ready" if detail == "ok" else "error"
    write_dashboard_status(settings, status=status, detail=detail, url=args.url, latency_ms=latency_ms)
    print(f"dashboard_status={status}")
    print(f"dashboard_detail={detail}")
    if latency_ms is not None:
        print(f"dashboard_latency_ms={latency_ms:.2f}")
    if status != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
