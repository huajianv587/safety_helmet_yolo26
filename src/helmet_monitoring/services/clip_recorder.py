from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

import cv2

from helmet_monitoring.core.config import AppSettings, CameraSettings
from helmet_monitoring.storage.evidence_store import EvidenceStore


@dataclass(slots=True)
class PendingClip:
    alert_id: str
    event_no: str
    created_at: datetime
    remaining_post_frames: int
    frames: list = field(default_factory=list)


class ClipRecorder:
    def __init__(self, settings: AppSettings, evidence_store: EvidenceStore) -> None:
        self.settings = settings
        self.evidence_store = evidence_store
        self.buffer_size = max(1, int(settings.clip.pre_seconds * settings.clip.fps))
        self.post_frames = max(1, int(settings.clip.post_seconds * settings.clip.fps))
        self._buffers: dict[str, deque] = {}
        self._pending: dict[str, list[PendingClip]] = {}

    def _overlay(self, frame, camera: CameraSettings, event_no: str, observed_at: datetime):
        stamped = frame.copy()
        lines = [
            f"Event: {event_no}",
            f"Time: {observed_at.isoformat()}",
            f"Camera: {camera.camera_name}",
            f"Location: {camera.site_name}/{camera.building_name}/{camera.floor_name}/{camera.workshop_name}/{camera.zone_name}",
        ]
        for index, line in enumerate(lines):
            y = 28 + index * 24
            cv2.putText(
                stamped,
                line,
                (16, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                (0, 215, 255),
                2,
            )
        return stamped

    def capture(self, camera: CameraSettings, frame, observed_at: datetime) -> list[dict[str, str | None]]:
        if not self.settings.clip.enabled:
            return []
        buffer = self._buffers.setdefault(camera.camera_id, deque(maxlen=self.buffer_size))
        buffer.append((frame.copy(), observed_at))

        completed: list[dict[str, str | None]] = []
        pendings = self._pending.get(camera.camera_id, [])
        for pending in list(pendings):
            pending.frames.append(self._overlay(frame, camera, pending.event_no, observed_at))
            pending.remaining_post_frames -= 1
            if pending.remaining_post_frames <= 0:
                clip_path, clip_url = self.evidence_store.save_video_frames(
                    camera.camera_id,
                    pending.frames,
                    pending.alert_id,
                    pending.created_at,
                    category="clips",
                    fps=self.settings.clip.fps,
                    codec=self.settings.clip.codec,
                )
                completed.append(
                    {
                        "alert_id": pending.alert_id,
                        "clip_path": clip_path,
                        "clip_url": clip_url,
                    }
                )
                pendings.remove(pending)
        return completed

    def start(self, camera: CameraSettings, alert_id: str, event_no: str, observed_at: datetime) -> None:
        if not self.settings.clip.enabled:
            return
        buffer = self._buffers.setdefault(camera.camera_id, deque(maxlen=self.buffer_size))
        initial_frames = [self._overlay(item_frame, camera, event_no, item_time) for item_frame, item_time in list(buffer)]
        pending = PendingClip(
            alert_id=alert_id,
            event_no=event_no,
            created_at=observed_at,
            remaining_post_frames=self.post_frames,
            frames=initial_frames,
        )
        self._pending.setdefault(camera.camera_id, []).append(pending)
