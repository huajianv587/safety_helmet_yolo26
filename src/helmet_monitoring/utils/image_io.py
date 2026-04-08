from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def read_image(path: str | Path, flags: int = cv2.IMREAD_COLOR):
    target = Path(path)
    try:
        payload = np.fromfile(target, dtype=np.uint8)
    except OSError:
        return None
    if payload.size == 0:
        return None
    return cv2.imdecode(payload, flags)


def write_image(path: str | Path, image, params: list[int] | None = None) -> bool:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    extension = target.suffix or ".jpg"
    success, encoded = cv2.imencode(extension, image, params or [])
    if not success:
        return False
    try:
        target.write_bytes(encoded.tobytes())
    except OSError:
        return False
    return True

