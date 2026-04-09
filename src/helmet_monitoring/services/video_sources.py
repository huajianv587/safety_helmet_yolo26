from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import cv2

from helmet_monitoring.core.config import CameraSettings


def _parse_source(value: str):
    stripped = value.strip()
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    return stripped


def is_remote_stream_source(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("rtsp://", "rtsps://", "rtmp://", "rtmps://", "http://", "https://"))


def is_rtsp_source(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("rtsp://", "rtsps://"))


def is_local_device_source(value: str) -> bool:
    return value.strip().lstrip("-").isdigit()


def local_device_path(value: str) -> Path | None:
    if not is_local_device_source(value):
        return None
    source_index = int(value.strip())
    if source_index < 0:
        return None
    return Path(f"/dev/video{source_index}")


def local_device_access_issue(value: str) -> str | None:
    device_path = local_device_path(value)
    if device_path is None:
        return None
    if Path("/.dockerenv").exists() and not device_path.exists():
        return (
            f"Local camera source {value.strip()} expects {device_path.as_posix()}, but this device is not available inside "
            "the container. For Docker, switch the camera source to RTSP/HTTP. For a laptop webcam on Windows, "
            "run the monitor on the host instead of inside Docker."
        )
    return None


def local_device_open_failure(value: str) -> str:
    device_path = local_device_path(value)
    device_label = device_path.as_posix() if device_path is not None else value.strip()
    return (
        f"Unable to open {device_label}. If this monitor is running inside Docker Desktop on Windows or macOS, "
        "switch the source to RTSP/HTTP/RTMP or run the monitor on the host for laptop webcam mode."
    )


def remote_stream_open_failure(value: str) -> str:
    return (
        f"Unable to open remote stream {value.strip()}. Keep the phone stream app in the foreground, "
        "disable auto-lock, ensure the phone and computer stay on the same Wi-Fi, and prefer a stable local network."
    )


def remote_stream_read_failure(value: str) -> str:
    return (
        f"Remote stream {value.strip()} timed out or disconnected. The monitor will reconnect automatically."
    )


def _ensure_ffmpeg_capture_options(source: str) -> None:
    if not is_rtsp_source(source):
        return
    env_name = "OPENCV_FFMPEG_CAPTURE_OPTIONS"
    if os.environ.get(env_name):
        return
    os.environ[env_name] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;500000|stimeout;5000000"


def _apply_capture_tuning(capture, source: str) -> None:
    if capture is None:
        return
    tuning: list[tuple[int | None, float]] = []
    tuning.append((getattr(cv2, "CAP_PROP_BUFFERSIZE", None), 1))
    if is_remote_stream_source(source):
        tuning.append((getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), 5000))
        tuning.append((getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), 8000))
    for prop_id, value in tuning:
        if prop_id is None:
            continue
        try:
            capture.set(prop_id, value)
        except Exception:
            continue


def _open_capture(source: str):
    parsed = _parse_source(source)
    if not is_remote_stream_source(source):
        capture = cv2.VideoCapture(parsed)
        _apply_capture_tuning(capture, source)
        return capture

    _ensure_ffmpeg_capture_options(source)
    capture = cv2.VideoCapture(parsed)
    _apply_capture_tuning(capture, source)
    return capture


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
        self._reader_thread: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._latest_seq = 0
        self._last_delivered_seq = 0
        self._reader_failed = False

    def _start_reader(self) -> None:
        if self.capture is None:
            return
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._reader_stop = threading.Event()
        self._reader_failed = False
        self._latest_frame = None
        self._latest_seq = 0
        self._last_delivered_seq = 0
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"camera-stream-{getattr(self.camera, 'camera_id', 'unknown')}",
            daemon=True,
        )
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        capture = self.capture
        while capture is not None and not self._reader_stop.is_set():
            try:
                success, frame = capture.read()
            except Exception:
                success, frame = False, None
            if not success:
                self._reader_failed = True
                break

            now = time.time()
            if self.last_frame_ts:
                delta = now - self.last_frame_ts
                if delta > 0:
                    self.last_fps = round(1.0 / delta, 2)
            self.last_frame_ts = now
            self.last_error = None
            with self._frame_lock:
                self._latest_frame = frame
                self._latest_seq += 1

    def open(self) -> bool:
        now = time.time()
        if now - self._last_open_attempt < self.retry_seconds:
            return False
        self._last_open_attempt = now
        self.release()
        access_issue = local_device_access_issue(self.camera.source)
        if access_issue:
            self.retry_count += 1
            self.last_error = access_issue
            return False
        self.capture = _open_capture(self.camera.source)
        opened = bool(self.capture and self.capture.isOpened())
        if opened:
            self.reconnect_count += 1
            self.last_error = None
            self._start_reader()
        else:
            self.retry_count += 1
            if Path("/.dockerenv").exists() and is_local_device_source(self.camera.source):
                self.last_error = local_device_open_failure(self.camera.source)
            elif is_remote_stream_source(self.camera.source):
                self.last_error = remote_stream_open_failure(self.camera.source)
            else:
                self.last_error = "Unable to open camera stream."
        return opened

    def read(self):
        if self.capture is None or not self.capture.isOpened():
            if not self.open():
                return False, None

        deadline = time.time() + 0.15
        while time.time() < deadline:
            if self._reader_failed:
                break
            with self._frame_lock:
                latest_frame = self._latest_frame
                latest_seq = self._latest_seq
            if latest_frame is not None and latest_seq != self._last_delivered_seq:
                self._last_delivered_seq = latest_seq
                self.frames_seen += 1
                self.last_error = None
                return True, latest_frame
            time.sleep(0.003)

        with self._frame_lock:
            latest_frame = self._latest_frame
            latest_seq = self._latest_seq
        if latest_frame is not None and latest_seq > 0:
            self._last_delivered_seq = latest_seq
            self.frames_seen += 1
            self.last_error = None
            return True, latest_frame

        if self._reader_failed:
            self.retry_count += 1
            if is_remote_stream_source(self.camera.source):
                self.last_error = remote_stream_read_failure(self.camera.source)
            else:
                self.last_error = "Frame read failed."
            self.release()
            return False, None
        self.last_error = "Waiting for the next camera frame."
        return False, None

    def release(self) -> None:
        self._reader_stop.set()
        capture = self.capture
        self.capture = None
        if capture is not None:
            capture.release()
        if self._reader_thread is not None and self._reader_thread.is_alive():
            if self._reader_thread is not threading.current_thread():
                self._reader_thread.join(timeout=0.2)
        self._reader_thread = None
        with self._frame_lock:
            self._latest_frame = None
            self._latest_seq = 0
            self._last_delivered_seq = 0
        self._reader_failed = False
