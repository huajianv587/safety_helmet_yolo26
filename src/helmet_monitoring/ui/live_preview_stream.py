from __future__ import annotations

import html
import json
import os
import threading
import time
from dataclasses import dataclass, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import cv2
import numpy as np

from helmet_monitoring.core.config import AppSettings
from helmet_monitoring.services.detector import HelmetDetector
from helmet_monitoring.services.video_sources import is_local_device_source


BOUNDARY = "frame"


@dataclass(slots=True)
class LivePreviewServerHandle:
    host: str
    port: int
    thread: threading.Thread
    server: ThreadingHTTPServer


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


class BrowserInferenceEngine:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.local_camera_ids = {
            camera.camera_id
            for camera in settings.cameras
            if camera.enabled and is_local_device_source(camera.source)
        }
        self._detector: HelmetDetector | None = None
        self._detector_lock = threading.Lock()

    def supports_camera(self, camera_id: str) -> bool:
        return camera_id in self.local_camera_ids

    def _get_detector(self) -> HelmetDetector:
        if self._detector is not None:
            return self._detector
        with self._detector_lock:
            if self._detector is None:
                preview_tracking = replace(self.settings.tracking, enabled=False)
                self._detector = HelmetDetector(self.settings.model, preview_tracking)
        return self._detector

    def detect(self, camera_id: str, payload: bytes) -> dict[str, object]:
        if not self.supports_camera(camera_id):
            raise KeyError(camera_id)

        frame_buffer = np.frombuffer(payload, dtype=np.uint8)
        frame = cv2.imdecode(frame_buffer, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Unable to decode the browser frame.")

        detector = self._get_detector()
        started_at = time.perf_counter()
        with self._detector_lock:
            detections = detector.detect(frame)
        infer_ms = (time.perf_counter() - started_at) * 1000.0

        return {
            "camera_id": camera_id,
            "infer_ms": round(infer_ms, 2),
            "frame_width": int(frame.shape[1]),
            "frame_height": int(frame.shape[0]),
            "detections": [
                {
                    "label": detection.label,
                    "confidence": round(float(detection.confidence), 4),
                    "x1": int(detection.x1),
                    "y1": int(detection.y1),
                    "x2": int(detection.x2),
                    "y2": int(detection.y2),
                    "is_violation": bool(detection.is_violation),
                }
                for detection in detections
            ],
        }


def _camera_frame_path(live_frames_dir: Path, camera_id: str) -> Path:
    return live_frames_dir / f"{camera_id}.jpg"


def _browser_camera_page(camera_id: str) -> str:
    safe_camera_id = json.dumps(camera_id)
    detect_interval_ms = _env_int("HELMET_BROWSER_PREVIEW_INTERVAL_MS", 180, minimum=80, maximum=1000)
    overlay_hold_ms = _env_int("HELMET_BROWSER_PREVIEW_OVERLAY_HOLD_MS", 900, minimum=250, maximum=5000)
    max_infer_width = _env_int("HELMET_BROWSER_PREVIEW_INFER_WIDTH", 512, minimum=256, maximum=960)
    camera_width = _env_int("HELMET_BROWSER_PREVIEW_CAMERA_WIDTH", 960, minimum=320, maximum=1920)
    camera_height = _env_int("HELMET_BROWSER_PREVIEW_CAMERA_HEIGHT", 540, minimum=240, maximum=1080)
    camera_fps = _env_int("HELMET_BROWSER_PREVIEW_CAMERA_FPS", 24, minimum=8, maximum=60)
    jpeg_quality = _env_float("HELMET_BROWSER_PREVIEW_JPEG_QUALITY", 0.68, minimum=0.3, maximum=0.92)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Helmet Live Preview</title>
  <style>
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #091220;
      font-family: Arial, sans-serif;
    }}
    .shell {{
      position: relative;
      width: 100%;
      height: 100%;
      background: #091220;
      overflow: hidden;
    }}
    video {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      background: #091220;
    }}
    canvas {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
    }}
    .status {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 18px;
      text-align: center;
      color: #d7e6ff;
      font-size: 14px;
      line-height: 1.5;
      background: rgba(9, 18, 32, 0.72);
    }}
  </style>
</head>
<body>
  <div class="shell">
    <video id="camera-video" autoplay playsinline muted></video>
    <canvas id="camera-overlay"></canvas>
    <div id="camera-status" class="status">Waiting for camera permission...</div>
  </div>
  <script>
    (() => {{
      const cameraId = {safe_camera_id};
      const detectPath = `/infer/${{encodeURIComponent(cameraId)}}`;
      const detectIntervalMs = {detect_interval_ms};
      const overlayHoldMs = {overlay_hold_ms};
      const maxInferWidth = {max_infer_width};
      const cameraWidth = {camera_width};
      const cameraHeight = {camera_height};
      const cameraFps = {camera_fps};
      const jpegQuality = {jpeg_quality};
      const maxAdaptiveDelayMs = Math.max(360, detectIntervalMs * 3);
      const statusEl = document.getElementById("camera-status");
      const videoEl = document.getElementById("camera-video");
      const overlayEl = document.getElementById("camera-overlay");
      const overlayCtx = overlayEl.getContext("2d", {{ alpha: true, desynchronized: true }});
      const captureCanvas = document.createElement("canvas");
      const captureCtx = captureCanvas.getContext("2d", {{ alpha: false, desynchronized: true }});
      let latestDetections = [];
      let latestFrameWidth = 0;
      let latestFrameHeight = 0;
      let latestInferMs = 0;
      let latestDetectionAt = 0;
      let inflight = false;
      let inferTimer = 0;

      const showStatus = (message) => {{
        statusEl.textContent = message;
        statusEl.style.display = "flex";
      }};

      const hideStatus = () => {{
        statusEl.style.display = "none";
      }};

      const resizeOverlay = () => {{
        const width = overlayEl.clientWidth || videoEl.clientWidth || 1;
        const height = overlayEl.clientHeight || videoEl.clientHeight || 1;
        if (overlayEl.width !== width || overlayEl.height !== height) {{
          overlayEl.width = width;
          overlayEl.height = height;
        }}
      }};

      const drawOverlay = () => {{
        resizeOverlay();
        overlayCtx.clearRect(0, 0, overlayEl.width, overlayEl.height);

        if (latestFrameWidth > 0 && latestFrameHeight > 0 && Date.now() - latestDetectionAt <= overlayHoldMs) {{
          const scaleX = overlayEl.width / latestFrameWidth;
          const scaleY = overlayEl.height / latestFrameHeight;
          for (const item of latestDetections) {{
            const color = item.is_violation ? "#ff4d5b" : "#2ed36f";
            const x = item.x1 * scaleX;
            const y = item.y1 * scaleY;
            const width = Math.max(1, (item.x2 - item.x1) * scaleX);
            const height = Math.max(1, (item.y2 - item.y1) * scaleY);
            overlayCtx.strokeStyle = color;
            overlayCtx.lineWidth = 3;
            overlayCtx.strokeRect(x, y, width, height);
            overlayCtx.font = "bold 16px Arial";
            overlayCtx.fillStyle = color;
            overlayCtx.fillText(item.is_violation ? "No Helmet" : "Helmet", x, Math.max(18, y - 8));
          }}
        }}

        overlayCtx.font = "14px Arial";
        overlayCtx.fillStyle = "#e8f2ff";
        overlayCtx.fillText(`Infer: ${{latestInferMs.toFixed(0)}} ms`, 16, 26);
        requestAnimationFrame(drawOverlay);
      }};

      const scheduleInference = (delayMs) => {{
        if (inferTimer) {{
          window.clearTimeout(inferTimer);
        }}
        inferTimer = window.setTimeout(runInference, Math.max(0, Math.round(delayMs)));
      }};

      const runInference = () => {{
        if (
          inflight ||
          document.hidden ||
          videoEl.readyState < 2 ||
          !videoEl.videoWidth ||
          !videoEl.videoHeight
        ) {{
          scheduleInference(detectIntervalMs);
          return;
        }}
        inflight = true;
        const roundtripStartedAt = performance.now();

        let inferWidth = videoEl.videoWidth;
        let inferHeight = videoEl.videoHeight;
        if (inferWidth > maxInferWidth) {{
          inferHeight = Math.max(1, Math.round(inferHeight * (maxInferWidth / inferWidth)));
          inferWidth = maxInferWidth;
        }}

        captureCanvas.width = inferWidth;
        captureCanvas.height = inferHeight;
        captureCtx.drawImage(videoEl, 0, 0, inferWidth, inferHeight);
        captureCanvas.toBlob(async (blob) => {{
          if (!blob) {{
            inflight = false;
            scheduleInference(detectIntervalMs);
            return;
          }}
          try {{
            const response = await fetch(detectPath, {{
              method: "POST",
              headers: {{ "Content-Type": "image/jpeg" }},
              body: blob,
            }});
            if (!response.ok) {{
              throw new Error("Detection endpoint is not ready.");
            }}
            const payload = await response.json();
            latestDetections = Array.isArray(payload.detections) ? payload.detections : [];
            latestInferMs = Number(payload.infer_ms || 0);
            latestFrameWidth = Number(payload.frame_width || inferWidth);
            latestFrameHeight = Number(payload.frame_height || inferHeight);
            latestDetectionAt = Date.now();
            hideStatus();
          }} catch (_error) {{
            showStatus("Detection is warming up or temporarily unavailable.");
          }} finally {{
            inflight = false;
            const roundtripMs = performance.now() - roundtripStartedAt;
            const nextDelay = Math.max(
              detectIntervalMs,
              Math.min(maxAdaptiveDelayMs, Math.round(roundtripMs * 1.12))
            );
            scheduleInference(nextDelay);
          }}
        }}, "image/jpeg", jpegQuality);
      }};

      const start = async () => {{
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{
          showStatus("This browser does not support direct camera access.");
          return;
        }}
        try {{
          let stream;
          try {{
            stream = await navigator.mediaDevices.getUserMedia({{
              video: {{
                facingMode: {{ ideal: "environment" }},
                width: {{ ideal: cameraWidth }},
                height: {{ ideal: cameraHeight }},
                frameRate: {{ ideal: cameraFps, max: cameraFps }},
              }},
              audio: false,
            }});
          }} catch (_error) {{
            stream = await navigator.mediaDevices.getUserMedia({{ video: true, audio: false }});
          }}
          videoEl.srcObject = stream;
          await videoEl.play();
          hideStatus();
          scheduleInference(detectIntervalMs);
          requestAnimationFrame(drawOverlay);
        }} catch (_error) {{
          showStatus("Camera permission was denied or the browser could not open the camera.");
        }}
      }};

      window.addEventListener("resize", resizeOverlay);
      start();
    }})();
  </script>
</body>
</html>"""


def _make_handler(
    live_frames_dir: Path,
    frame_interval_seconds: float,
    inference_engine: BrowserInferenceEngine | None,
):
    class LivePreviewHandler(BaseHTTPRequestHandler):
        server_version = "HelmetLivePreview/2.0"

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")

        def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler interface
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler interface
            if self.path == "/health":
                self.send_response(HTTPStatus.OK)
                self._send_cors_headers()
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b"ok")
                return

            browser_prefix = "/browser/"
            if self.path.startswith(browser_prefix):
                camera_id = unquote(self.path[len(browser_prefix) :].split("?", 1)[0]).strip()
                if not camera_id:
                    self.send_error(HTTPStatus.BAD_REQUEST, "camera_id is required.")
                    return
                if inference_engine is None or not inference_engine.supports_camera(camera_id):
                    self.send_error(HTTPStatus.NOT_FOUND, "Local browser preview is not available for this camera.")
                    return
                payload = _browser_camera_page(camera_id).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self._send_cors_headers()
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            mjpeg_prefix = "/mjpeg/"
            if not self.path.startswith(mjpeg_prefix):
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint.")
                return

            camera_id = unquote(self.path[len(mjpeg_prefix) :].split("?", 1)[0]).strip()
            if not camera_id:
                self.send_error(HTTPStatus.BAD_REQUEST, "camera_id is required.")
                return

            frame_path = _camera_frame_path(live_frames_dir, camera_id)
            self.send_response(HTTPStatus.OK)
            self._send_cors_headers()
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Connection", "close")
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
            self.end_headers()

            last_mtime_ns = -1
            try:
                while True:
                    if not frame_path.exists():
                        time.sleep(frame_interval_seconds)
                        continue

                    try:
                        stat = frame_path.stat()
                    except OSError:
                        time.sleep(frame_interval_seconds)
                        continue

                    if stat.st_mtime_ns == last_mtime_ns:
                        time.sleep(frame_interval_seconds)
                        continue

                    try:
                        payload = frame_path.read_bytes()
                    except OSError:
                        time.sleep(frame_interval_seconds)
                        continue

                    last_mtime_ns = stat.st_mtime_ns
                    self.wfile.write(f"--{BOUNDARY}\r\n".encode("ascii"))
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(payload)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                    time.sleep(frame_interval_seconds)
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler interface
            infer_prefix = "/infer/"
            if not self.path.startswith(infer_prefix):
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint.")
                return

            if inference_engine is None:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Inference engine is not available.")
                return

            camera_id = unquote(self.path[len(infer_prefix) :].split("?", 1)[0]).strip()
            if not camera_id:
                self.send_error(HTTPStatus.BAD_REQUEST, "camera_id is required.")
                return

            content_length = int(self.headers.get("Content-Length", "0") or "0")
            if content_length <= 0 or content_length > 5_000_000:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid frame payload.")
                return

            payload = self.rfile.read(content_length)
            try:
                result = inference_engine.detect(camera_id, payload)
            except KeyError:
                self.send_error(HTTPStatus.NOT_FOUND, "The camera is not configured for browser preview.")
                return
            except ValueError as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except Exception:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Detection failed.")
                return

            body = json.dumps(result).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self._send_cors_headers()
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003 - matches stdlib signature
            return

    return LivePreviewHandler


def start_live_preview_server(
    *,
    live_frames_dir: str | Path,
    host: str = "0.0.0.0",
    port: int = 8765,
    frame_interval_seconds: float = 0.03,
    settings: AppSettings | None = None,
) -> LivePreviewServerHandle:
    target_dir = Path(live_frames_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    inference_engine = BrowserInferenceEngine(settings) if settings is not None else None
    handler = _make_handler(target_dir, frame_interval_seconds, inference_engine)
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, name="live-preview-server", daemon=True)
    thread.start()
    return LivePreviewServerHandle(host=host, port=port, thread=thread, server=server)
