from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import cv2

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.core.schemas import utc_now
from helmet_monitoring.storage.evidence_store import EvidenceStore


def main() -> None:
    settings = load_settings("configs/runtime.json")
    image_dir = settings.resolve_path("data/helmet_detection_dataset/images/val")
    image_path = next(image_dir.glob("*.jpg"))
    frame = cv2.imread(str(image_path))
    store = EvidenceStore(settings)
    local_path, public_url = store.save("smoke-cam", frame, uuid.uuid4().hex, utc_now())
    print(f"local_path={local_path}")
    print(f"public_url={public_url}")


if __name__ == "__main__":
    main()
