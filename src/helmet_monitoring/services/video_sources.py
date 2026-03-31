from __future__ import annotations

import time

import cv2

from helmet_monitoring.core.config import CameraSettings


def _parse_source(value: str):
    stripped = value.strip()
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    return stripped


class CameraStream:
    def __init__(self, camera: CameraSettings, retry_seconds: float) -> None:
        self.camera = camera
        self.retry_seconds = retry_seconds
        self.capture = None
        self.frames_seen = 0
        self._last_open_attempt = 0.0
        self.retry_count = 0
        self.reconnect_count = 0
        self.last_error: str | None = None
        self.last_frame_ts = 0.0
        self.last_fps: float | None = None

    def open(self) -> bool:
        now = time.time()
        if now - self._last_open_attempt < self.retry_seconds:
            return False
        self._last_open_attempt = now
        self.release()
        self.capture = cv2.VideoCapture(_parse_source(self.camera.source))
        opened = bool(self.capture and self.capture.isOpened())
        if opened:
            self.reconnect_count += 1
            self.last_error = None
        else:
            self.retry_count += 1
            self.last_error = "Unable to open camera stream."
        return opened

    def read(self):
        if self.capture is None or not self.capture.isOpened():
            if not self.open():
                return False, None
        success, frame = self.capture.read()
        if not success:
            self.retry_count += 1
            self.last_error = "Frame read failed."
            self.release()
            return False, None
        self.frames_seen += 1
        now = time.time()
        if self.last_frame_ts:
            delta = now - self.last_frame_ts
            if delta > 0:
                self.last_fps = round(1.0 / delta, 2)
        self.last_frame_ts = now
        self.last_error = None
        return True, frame

    def release(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
