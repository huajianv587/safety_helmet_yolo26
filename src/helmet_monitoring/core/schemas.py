from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(slots=True)
class DetectionRecord:
    class_id: int
    label: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int
    is_violation: bool
    track_id: str | None = None

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def bbox(self) -> dict[str, int]:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}

    @property
    def area(self) -> int:
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)


@dataclass(slots=True)
class AlertCandidate:
    event_key: str
    camera_id: str
    confidence: float
    label: str
    bbox: dict[str, int]
    first_seen_at: datetime
    triggered_at: datetime
    consecutive_hits: int
    track_id: str | None = None


@dataclass(slots=True)
class ResolvedPerson:
    person_id: str | None
    person_name: str
    employee_id: str | None
    department: str | None
    team: str | None
    role: str | None
    phone: str | None
    identity_status: str
    identity_source: str
    identity_confidence: float | None = None
    badge_text: str | None = None
    badge_confidence: float | None = None
    face_match_score: float | None = None
    review_note: str | None = None
    llm_provider: str | None = None
    llm_summary: str | None = None
    face_crop: Any | None = None
    badge_crop: Any | None = None


@dataclass(slots=True)
class CameraHeartbeat:
    camera_id: str
    camera_name: str
    source: str
    location: str
    department: str
    last_status: str
    last_seen_at: datetime
    site_name: str | None = None
    building_name: str | None = None
    floor_name: str | None = None
    workshop_name: str | None = None
    zone_name: str | None = None
    responsible_department: str | None = None
    retry_count: int = 0
    reconnect_count: int = 0
    last_error: str | None = None
    last_frame_at: datetime | None = None
    last_fps: float | None = None

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["last_seen_at"] = self.last_seen_at.isoformat()
        payload["last_frame_at"] = self.last_frame_at.isoformat() if self.last_frame_at else None
        return payload


@dataclass(slots=True)
class AlertRecord:
    alert_id: str
    event_key: str
    camera_id: str
    camera_name: str
    location: str
    department: str
    violation_type: str
    risk_level: str
    confidence: float
    snapshot_path: str
    snapshot_url: str | None
    status: str
    bbox: dict[str, int]
    model_name: str
    person_id: str | None
    person_name: str
    employee_id: str | None
    team: str | None
    role: str | None
    phone: str | None
    identity_status: str
    identity_source: str
    created_at: datetime
    event_no: str | None = None
    identity_confidence: float | None = None
    badge_text: str | None = None
    badge_confidence: float | None = None
    face_match_score: float | None = None
    face_crop_path: str | None = None
    face_crop_url: str | None = None
    badge_crop_path: str | None = None
    badge_crop_url: str | None = None
    review_note: str | None = None
    llm_provider: str | None = None
    llm_summary: str | None = None
    clip_path: str | None = None
    clip_url: str | None = None
    assigned_to: str | None = None
    assigned_email: str | None = None
    handled_by: str | None = None
    handled_at: datetime | None = None
    resolution_note: str | None = None
    remediation_snapshot_path: str | None = None
    remediation_snapshot_url: str | None = None
    false_positive: bool = False
    closed_at: datetime | None = None
    alert_source: str = "model"
    governance_note: str | None = None
    track_id: str | None = None
    site_name: str | None = None
    building_name: str | None = None
    floor_name: str | None = None
    workshop_name: str | None = None
    zone_name: str | None = None
    responsible_department: str | None = None

    def to_record(self) -> dict[str, object]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["handled_at"] = self.handled_at.isoformat() if self.handled_at else None
        payload["closed_at"] = self.closed_at.isoformat() if self.closed_at else None
        return payload


@dataclass(slots=True)
class AlertActionRecord:
    action_id: str
    alert_id: str
    event_no: str | None
    action_type: str
    actor: str
    actor_role: str
    note: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


@dataclass(slots=True)
class NotificationLogRecord:
    notification_id: str
    alert_id: str
    event_no: str | None
    channel: str
    recipient: str
    subject: str
    status: str
    error_message: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


@dataclass(slots=True)
class HardCaseRecord:
    case_id: str
    alert_id: str
    event_no: str | None
    case_type: str
    snapshot_path: str | None
    snapshot_url: str | None
    clip_path: str | None
    clip_url: str | None
    note: str | None
    created_at: datetime = field(default_factory=utc_now)

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload
