from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any


UTC = timezone.utc


@dataclass(slots=True)
class LiveFrameEntry:
    camera_id: str
    payload: bytes
    updated_at: datetime
    content_type: str = "image/jpeg"
    metadata: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0


class LiveFrameHub:
    def __init__(self) -> None:
        self._lock = Lock()
        self._frames: dict[str, LiveFrameEntry] = {}
        self._sequence = 0

    def publish(
        self,
        camera_id: str,
        payload: bytes,
        *,
        updated_at: datetime | None = None,
        content_type: str = "image/jpeg",
        metadata: dict[str, Any] | None = None,
    ) -> LiveFrameEntry:
        observed_at = updated_at or datetime.now(tz=UTC)
        with self._lock:
            self._sequence += 1
            entry = LiveFrameEntry(
                camera_id=str(camera_id),
                payload=bytes(payload),
                updated_at=observed_at,
                content_type=content_type,
                metadata=dict(metadata or {}),
                sequence=self._sequence,
            )
            self._frames[str(camera_id)] = entry
            return entry

    def get(self, camera_id: str) -> LiveFrameEntry | None:
        with self._lock:
            return self._frames.get(str(camera_id))

    def clear(self, camera_id: str | None = None) -> None:
        with self._lock:
            if camera_id is None:
                self._frames.clear()
                return
            self._frames.pop(str(camera_id), None)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                camera_id: {
                    "updated_at": entry.updated_at.isoformat(),
                    "sequence": entry.sequence,
                    "content_type": entry.content_type,
                    **dict(entry.metadata),
                }
                for camera_id, entry in self._frames.items()
            }


_hub: LiveFrameHub | None = None


def get_live_frame_hub() -> LiveFrameHub:
    global _hub
    if _hub is None:
        _hub = LiveFrameHub()
    return _hub
