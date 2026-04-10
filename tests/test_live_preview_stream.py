from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import app
from helmet_monitoring.core.config import (
    AppSettings,
    CameraSettings,
    ClipSettings,
    EventRuleSettings,
    FaceRecognitionSettings,
    GovernanceSettings,
    IdentitySettings,
    LlmFallbackSettings,
    ModelSettings,
    MonitoringSettings,
    NotificationSettings,
    OcrSettings,
    PersistenceSettings,
    SecuritySettings,
    SupabaseSettings,
    TrackingSettings,
)
from helmet_monitoring.core.schemas import DetectionRecord
from helmet_monitoring.ui.live_preview_stream import start_live_preview_server


def build_settings() -> AppSettings:
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="artifacts/training_runs/helmet_project/cpu_test3/weights/best.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(
            snapshot_dir="artifacts/captures",
            runtime_dir="artifacts/runtime",
            upload_to_supabase_storage=False,
        ),
        monitoring=MonitoringSettings(camera_retry_seconds=0.0),
        identity=IdentitySettings(),
        face_recognition=FaceRecognitionSettings(enabled=False),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(),
        notifications=NotificationSettings(enabled=False, email_enabled=False),
        security=SecuritySettings(),
        supabase=SupabaseSettings(),
        cameras=(
            CameraSettings(
                camera_id="cam-local-001",
                camera_name="Laptop Camera",
                source="0",
                location="Test",
                department="QA",
                enabled=True,
            ),
        ),
    )


class LivePreviewStreamTest(unittest.TestCase):
    def test_app_cached_preview_server_supports_legacy_signature(self) -> None:
        cached_impl = getattr(app._cached_live_preview_server, "__wrapped__", app._cached_live_preview_server)

        class LegacyModule:
            @staticmethod
            def start_live_preview_server(*, live_frames_dir, port):
                return {"live_frames_dir": live_frames_dir, "port": port, "mode": "legacy"}

        with patch.object(app.importlib, "reload", return_value=LegacyModule):
            result = cached_impl("tmp/live", 9988, object())

        self.assertEqual(result["port"], 9988)
        self.assertEqual(result["mode"], "legacy")

    def test_app_cached_preview_server_starts_current_server(self) -> None:
        cached_impl = getattr(app._cached_live_preview_server, "__wrapped__", app._cached_live_preview_server)
        settings = build_settings()

        with tempfile.TemporaryDirectory() as temp_dir:
            handle = cached_impl(temp_dir, 0, settings)
            port = handle.server.server_address[1]
            try:
                time.sleep(0.1)
                with urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
                    health_payload = response.read().decode("utf-8")
            finally:
                handle.server.shutdown()
                handle.server.server_close()

        self.assertEqual(health_payload, "ok")

    def test_live_preview_server_exposes_browser_and_infer_endpoints(self) -> None:
        settings = build_settings()
        sample_frame = np.zeros((120, 160, 3), dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", sample_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        self.assertTrue(ok)
        payload = encoded.tobytes()

        class FakeDetector:
            def detect(self, _frame):
                return [
                    DetectionRecord(
                        class_id=0,
                        label="helmet",
                        confidence=0.93,
                        x1=10,
                        y1=12,
                        x2=90,
                        y2=104,
                        is_violation=False,
                    ),
                    DetectionRecord(
                        class_id=1,
                        label="no_helmet",
                        confidence=0.88,
                        x1=94,
                        y1=20,
                        x2=150,
                        y2=110,
                        is_violation=True,
                    ),
                ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("helmet_monitoring.ui.live_preview_stream.BrowserInferenceEngine._get_detector", return_value=FakeDetector()):
                handle = start_live_preview_server(
                    live_frames_dir=temp_dir,
                    port=0,
                    settings=settings,
                )
                port = handle.server.server_address[1]
                try:
                    time.sleep(0.1)
                    with urlopen(f"http://127.0.0.1:{port}/browser/cam-local-001", timeout=5) as response:
                        browser_html = response.read().decode("utf-8")
                    self.assertIn("getUserMedia", browser_html)
                    self.assertIn("/infer/${encodeURIComponent(cameraId)}", browser_html)

                    request = Request(
                        f"http://127.0.0.1:{port}/infer/cam-local-001",
                        data=payload,
                        headers={"Content-Type": "image/jpeg"},
                        method="POST",
                    )
                    with urlopen(request, timeout=5) as response:
                        infer_payload = json.loads(response.read().decode("utf-8"))
                finally:
                    handle.server.shutdown()
                    handle.server.server_close()

        self.assertEqual(infer_payload["camera_id"], "cam-local-001")
        self.assertEqual(infer_payload["frame_width"], 160)
        self.assertEqual(infer_payload["frame_height"], 120)
        self.assertEqual(len(infer_payload["detections"]), 2)
        self.assertTrue(any(item["is_violation"] for item in infer_payload["detections"]))
        self.assertTrue(any(not item["is_violation"] for item in infer_payload["detections"]))


if __name__ == "__main__":
    unittest.main()
