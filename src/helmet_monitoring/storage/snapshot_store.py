from __future__ import annotations

from datetime import datetime
from pathlib import Path

import cv2


class SnapshotStore:
    def __init__(self, snapshot_root: Path) -> None:
        self.snapshot_root = snapshot_root
        self.snapshot_root.mkdir(parents=True, exist_ok=True)

    def save(self, camera_id: str, frame, alert_id: str, created_at: datetime) -> str:
        day_dir = self.snapshot_root / created_at.strftime("%Y%m%d") / camera_id
        day_dir.mkdir(parents=True, exist_ok=True)
        target = day_dir / f"{created_at.strftime('%H%M%S')}_{alert_id}.jpg"
        cv2.imwrite(str(target), frame)
        return str(target)

