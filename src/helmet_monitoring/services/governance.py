from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from helmet_monitoring.core.config import AppSettings, CameraSettings
from helmet_monitoring.core.schemas import AlertCandidate


@dataclass(slots=True)
class GovernanceDecision:
    allow: bool
    risk_level: str
    review_required: bool
    note: str | None = None


class FalsePositiveGovernance:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def _override_value(self, camera: CameraSettings, field_name: str, default):
        camera_override = self.settings.governance.camera_overrides.get(camera.camera_id, {})
        if field_name in camera_override:
            return camera_override[field_name]
        site_key = str(camera.site_name or "").strip()
        if site_key:
            site_override = self.settings.governance.site_overrides.get(site_key, {})
            if field_name in site_override:
                return site_override[field_name]
        return default

    def _is_night(self, observed_at: datetime) -> bool:
        hour = observed_at.hour
        start = self.settings.governance.night_start_hour
        end = self.settings.governance.night_end_hour
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    def _inside_ignore_zone(self, camera_id: str, bbox: dict[str, int]) -> bool:
        for zone in self.settings.governance.ignore_zones.get(camera_id, ()):
            if (
                bbox["x1"] >= zone["x1"]
                and bbox["y1"] >= zone["y1"]
                and bbox["x2"] <= zone["x2"]
                and bbox["y2"] <= zone["y2"]
            ):
                return True
        return False

    def evaluate(self, camera: CameraSettings, candidate: AlertCandidate, observed_at: datetime) -> GovernanceDecision:
        if not bool(self._override_value(camera, "enabled", self.settings.governance.enabled)):
            return GovernanceDecision(allow=True, risk_level="high", review_required=False)
        if camera.camera_id in self.settings.governance.whitelist_camera_ids:
            return GovernanceDecision(
                allow=False,
                risk_level="low",
                review_required=False,
                note="Camera is currently in the governance whitelist and will not trigger alerts.",
            )
        bbox = candidate.bbox
        area = max(0, bbox["x2"] - bbox["x1"]) * max(0, bbox["y2"] - bbox["y1"])
        min_bbox_area = int(self._override_value(camera, "min_bbox_area", self.settings.governance.min_bbox_area))
        if area < min_bbox_area:
            return GovernanceDecision(
                allow=False,
                risk_level="low",
                review_required=False,
                note="Target is too small and is filtered as a likely false positive.",
            )
        if self._inside_ignore_zone(camera.camera_id, bbox):
            return GovernanceDecision(
                allow=False,
                risk_level="low",
                review_required=False,
                note="Target falls inside an ignore zone and will not be alerted.",
            )

        review_required = False
        risk_level = "high"
        notes: list[str] = []
        night_confidence_boost = float(
            self._override_value(camera, "night_confidence_boost", self.settings.governance.night_confidence_boost)
        )
        review_confidence_margin = float(
            self._override_value(camera, "review_confidence_margin", self.settings.governance.review_confidence_margin)
        )
        if self._is_night(observed_at) and candidate.confidence < (
            self.settings.event_rules.min_confidence_for_alert + night_confidence_boost
        ):
            review_required = True
            risk_level = "medium"
            notes.append("Night-time detection requires manual review.")
        if candidate.confidence < (
            self.settings.event_rules.min_confidence_for_alert + review_confidence_margin
        ):
            review_required = True
            risk_level = "medium"
            notes.append("Confidence is near the lower bound and should be reviewed.")
        return GovernanceDecision(
            allow=True,
            risk_level=risk_level,
            review_required=review_required,
            note=" ".join(notes) or None,
        )
