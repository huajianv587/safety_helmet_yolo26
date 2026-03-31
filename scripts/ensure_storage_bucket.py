from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.storage.evidence_store import EvidenceStore


def main() -> None:
    settings = load_settings("configs/runtime.json")
    store = EvidenceStore(settings)
    ready = store._ensure_bucket()
    print(f"bucket={settings.supabase.storage_bucket}")
    print(f"ready={str(ready).lower()}")


if __name__ == "__main__":
    main()

