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
from helmet_monitoring.services.video_sources import local_device_access_issue


INVALID_REMOTE_SOURCE_MARKERS = (
    "",
    "rtsp://replace-with-your-camera-url",
    "rtsp://replace-with-your-iphone-stream-url",
    "http://replace-with-your-camera-url",
    "rtmp://replace-with-your-camera-url",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Safety Helmet Phase 1 monitoring worker.")
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to the runtime JSON config. Defaults to HELMET_CONFIG_PATH or configs/runtime.json.",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="Optional frame cap for smoke tests. Use 0 to run continuously.",
    )
    return parser.parse_args()


def validate_runtime_sources(settings) -> None:
    source_issues: list[str] = []
    for camera in settings.cameras:
        if not camera.enabled:
            continue
        source_value = camera.source.strip()
        if source_value in INVALID_REMOTE_SOURCE_MARKERS:
            source_issues.append(
                f"{camera.camera_name} ({camera.camera_id}): missing live stream address. "
                "Fill HELMET_MONITOR_STREAM_URL in .env or update the camera source in the runtime config."
            )
            continue
        access_issue = local_device_access_issue(camera.source)
        if access_issue:
            source_issues.append(f"{camera.camera_name} ({camera.camera_id}): {access_issue}")
    if source_issues:
        joined = "\n".join(f"- {item}" for item in source_issues)
        raise RuntimeError(
            "The configured live camera sources are not available to this monitor process.\n"
            f"{joined}\n"
            "Tip: keep the dashboard in Docker, but run the monitor on the Windows host for laptop webcam mode."
        )


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    validate_runtime_sources(settings)
    monitor = SafetyHelmetMonitor(settings)
    frame_limit = args.max_frames if args.max_frames > 0 else None
    monitor.run(max_frames=frame_limit)


if __name__ == "__main__":
    main()
