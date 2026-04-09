from __future__ import annotations

import argparse
import os
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import AppSettings, load_settings
from helmet_monitoring.services.video_sources import is_local_device_source
from helmet_monitoring.ui.live_preview_stream import start_live_preview_server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch a lightweight browser camera preview with helmet boxes.")
    parser.add_argument("--config", default=None, help="Optional runtime config path.")
    parser.add_argument("--camera-id", default=None, help="Specific local camera_id to open.")
    parser.add_argument("--port", type=int, default=int(os.getenv("HELMET_LIVE_PREVIEW_PORT", "8765")), help="Preview server port.")
    parser.add_argument("--host", default="127.0.0.1", help="Host for the preview URL shown in the browser.")
    parser.add_argument("--bind-host", default="0.0.0.0", help="Host address to bind the preview server to.")
    parser.add_argument("--no-browser", action="store_true", help="Start the preview server without opening the browser.")
    parser.add_argument("--startup-wait", type=float, default=0.4, help="Seconds to wait before opening the browser.")
    return parser.parse_args()


def _enabled_local_cameras(settings: AppSettings):
    return [
        camera
        for camera in settings.cameras
        if camera.enabled and is_local_device_source(camera.source)
    ]


def _pick_camera_id(settings: AppSettings, requested_camera_id: str | None) -> str:
    local_cameras = _enabled_local_cameras(settings)
    if requested_camera_id:
        for camera in local_cameras:
            if camera.camera_id == requested_camera_id:
                return camera.camera_id
        raise SystemExit(f"Local camera '{requested_camera_id}' is not enabled in the current settings.")
    if not local_cameras:
        raise SystemExit("No enabled local camera found. Check camera_use_laptop_camera or configs/runtime.json.")
    return local_cameras[0].camera_id


def _preview_url(host: str, port: int, camera_id: str) -> str:
    return f"http://{host}:{port}/browser/{quote(camera_id)}"


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    camera_id = _pick_camera_id(settings, args.camera_id)

    live_frames_dir = Path(settings.persistence.runtime_dir) / "live_frames"
    live_frames_dir.mkdir(parents=True, exist_ok=True)

    handle = start_live_preview_server(
        live_frames_dir=live_frames_dir,
        host=args.bind_host,
        port=args.port,
        settings=settings,
    )
    preview_url = _preview_url(args.host, args.port, camera_id)
    print(f"Preview URL: {preview_url}")
    print("This mode uses the browser camera directly for smoother live video.")
    print("Green boxes mean helmet detected. Red boxes mean helmet missing.")
    print("Press Ctrl+C to stop the preview server.")

    try:
        if not args.no_browser:
            time.sleep(max(args.startup_wait, 0.0))
            webbrowser.open(preview_url, new=1)
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping browser camera preview...")
    finally:
        handle.server.shutdown()
        handle.server.server_close()


if __name__ == "__main__":
    main()
