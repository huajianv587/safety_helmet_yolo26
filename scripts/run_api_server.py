from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))


def main() -> None:
    host = os.getenv("HELMET_API_HOST", "127.0.0.1")
    port = int(os.getenv("HELMET_API_PORT", "8000"))
    reload = os.getenv("HELMET_API_RELOAD", "0").lower() in {"1", "true", "yes", "on"}
    uvicorn.run("helmet_monitoring.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()

