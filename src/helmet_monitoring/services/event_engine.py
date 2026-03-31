from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime

from helmet_monitoring.core.config import EventRuleSettings
from helmet_monitoring.core.schemas import AlertCandidate, DetectionRecord


@dataclass(slots=True)
class TrackState:
    track_id: str
    center: tuple[float, float]
    bbox: dict[str, int]
    first_seen_at: datetime
    last_seen_at: datetime
    label: str
    confidence: float
    consecutive_hits: int = 1
    last_alert_at: datetime | None = None


class ViolationEventEngine:
    def __init__(self, settings: EventRuleSettings) -> None:
        self.settings = settings
        self._tracks: dict[str, list[TrackState]] = {}

    def evaluate(
        self,
        camera_id: str,
        detections: list[DetectionRecord],
        observed_at: datetime,
    ) -> list[AlertCandidate]:
        tracks = self._tracks.setdefault(camera_id, [])
        stale_after = self.settings.max_track_age_seconds
        tracks[:] = [track for track in tracks if (observed_at - track.last_seen_at).total_seconds() <= stale_after]

        violation_detections = [
            item
            for item in detections
            if item.is_violation and item.confidence >= self.settings.min_confidence_for_alert
        ]
        matched_track_ids: set[str] = set()
        updated_tracks: list[TrackState] = []

        for detection in violation_detections:
            best_track: TrackState | None = None
            best_distance: float | None = None
            if detection.track_id:
                for track in tracks:
                    if track.track_id == detection.track_id:
                        best_track = track
                        break
            for track in tracks:
                if best_track is not None:
                    break
                if track.track_id in matched_track_ids:
                    continue
                distance = math.dist(track.center, detection.center)
                if distance > self.settings.match_distance_pixels:
                    continue
                if best_distance is None or distance < best_distance:
                    best_track = track
                    best_distance = distance

            if best_track is None:
                best_track = TrackState(
                    track_id=detection.track_id or uuid.uuid4().hex[:8],
                    center=detection.center,
                    bbox=detection.bbox,
                    first_seen_at=observed_at,
                    last_seen_at=observed_at,
                    label=detection.label,
                    confidence=detection.confidence,
                    consecutive_hits=1,
                )
                tracks.append(best_track)
            else:
                best_track.center = detection.center
                best_track.bbox = detection.bbox
                best_track.last_seen_at = observed_at
                best_track.label = detection.label
                best_track.confidence = detection.confidence
                best_track.consecutive_hits += 1
            matched_track_ids.add(best_track.track_id)
            updated_tracks.append(best_track)

        alerts: list[AlertCandidate] = []
        for track in updated_tracks:
            if track.consecutive_hits < self.settings.alert_frames:
                continue
            if track.last_alert_at and (observed_at - track.last_alert_at).total_seconds() < self.settings.dedupe_seconds:
                continue
            track.last_alert_at = observed_at
            alerts.append(
                AlertCandidate(
                    event_key=f"{camera_id}:{track.track_id}",
                    camera_id=camera_id,
                    confidence=track.confidence,
                    label=track.label,
                    bbox=track.bbox,
                    first_seen_at=track.first_seen_at,
                    triggered_at=observed_at,
                    consecutive_hits=track.consecutive_hits,
                    track_id=track.track_id,
                )
            )
        return alerts
