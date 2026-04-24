from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

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
from helmet_monitoring.services.clip_recorder import ClipRecorder


def _build_settings(root: Path) -> AppSettings:
    registry_path = root / "persons.json"
    registry_path.write_text("[]", encoding="utf-8")
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="models/best.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(
            snapshot_dir=str(root / "captures"),
            runtime_dir=str(root / "runtime"),
            upload_to_supabase_storage=False,
        ),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(registry_path=str(registry_path)),
        face_recognition=FaceRecognitionSettings(enabled=False),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(enabled=True, pre_seconds=1, post_seconds=1, fps=1.0, codec="mp4v"),
        notifications=NotificationSettings(enabled=False, email_enabled=False),
        security=SecuritySettings(),
        supabase=SupabaseSettings(),
        cameras=(),
        config_path=root / "runtime.json",
    )


class _FakeEvidenceStore:
    def __init__(self) -> None:
        self.saved_existing: list[tuple] = []
        self.saved_frames: list[tuple] = []

    def save_existing_file(self, *args, **kwargs):
        self.saved_existing.append((args, kwargs))
        return ("existing.mp4", "https://example.test/existing.mp4")

    def save_video_frames(self, *args, **kwargs):
        self.saved_frames.append((args, kwargs))
        return ("fallback.mp4", None)


class _FakeVideoWriter:
    def __init__(self, path, *_args, **_kwargs) -> None:
        self.frames_written = 0
        self._opened = True
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"staged-video")

    def isOpened(self) -> bool:
        return self._opened

    def write(self, _frame) -> None:
        self.frames_written += 1

    def release(self) -> None:
        self._opened = False


class ClipRecorderTest(unittest.TestCase):
    def test_clip_recorder_streams_to_staging_file_before_final_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = _build_settings(root)
            evidence_store = _FakeEvidenceStore()
            recorder = ClipRecorder(settings, evidence_store)
            camera = CameraSettings(
                camera_id="cam-001",
                camera_name="Gate Camera",
                source="0",
                location="Gate",
                department="Safety",
            )
            frame = np.zeros((48, 64, 3), dtype=np.uint8)
            started_at = datetime.now(timezone.utc)

            with patch("helmet_monitoring.services.clip_recorder.cv2.VideoWriter", _FakeVideoWriter), patch(
                "helmet_monitoring.services.clip_recorder.cv2.VideoWriter_fourcc",
                return_value=0,
            ):
                recorder.capture(camera, frame, started_at)
                recorder.start(camera, "alert-001", "EVT-001", started_at)
                completed = recorder.capture(camera, frame, started_at + timedelta(seconds=1))

        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["clip_path"], "existing.mp4")
        self.assertEqual(len(evidence_store.saved_existing), 1)
        self.assertEqual(len(evidence_store.saved_frames), 0)


if __name__ == "__main__":
    unittest.main()
