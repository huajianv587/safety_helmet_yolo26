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
from helmet_monitoring.services.monitor import SafetyHelmetMonitor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Safety Helmet Phase 1 monitoring worker.")
    parser.add_argument("--config", default="configs/runtime.json", help="Path to the runtime JSON config.")
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="Optional frame cap for smoke tests. Use 0 to run continuously.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    monitor = SafetyHelmetMonitor(settings)
    frame_limit = args.max_frames if args.max_frames > 0 else None
    monitor.run(max_frames=frame_limit)


if __name__ == "__main__":
    main()
