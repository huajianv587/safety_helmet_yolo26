from __future__ import annotations

import time
import uuid
from pathlib import Path

import cv2

from helmet_monitoring.core.config import AppSettings
from helmet_monitoring.core.schemas import AlertRecord, CameraHeartbeat, utc_now
from helmet_monitoring.services.clip_recorder import ClipRecorder
from helmet_monitoring.services.detector import HelmetDetector
from helmet_monitoring.services.event_engine import ViolationEventEngine
from helmet_monitoring.services.governance import FalsePositiveGovernance
from helmet_monitoring.services.identity_resolver import build_identity_resolver
from helmet_monitoring.services.notifier import NotificationService
from helmet_monitoring.services.video_sources import CameraStream
from helmet_monitoring.storage.evidence_store import EvidenceStore
from helmet_monitoring.storage.repository import AlertRepository, build_repository


class SafetyHelmetMonitor:
    def __init__(self, settings: AppSettings, repository: AlertRepository | None = None) -> None:
        if not settings.cameras:
            raise ValueError("At least one camera source is required in configs/runtime.json")
        self.settings = settings
        self.repository = repository or build_repository(settings)
        self.evidence_store = EvidenceStore(settings)
        self.detector = HelmetDetector(settings.model, settings.tracking)
        self.event_engine = ViolationEventEngine(settings.event_rules)
        self.identity_resolver = build_identity_resolver(settings)
        self.governance = FalsePositiveGovernance(settings)
        self.clip_recorder = ClipRecorder(settings, self.evidence_store)
        self.notifier = NotificationService(settings, self.repository)
        self.streams = [
            CameraStream(camera, retry_seconds=settings.monitoring.camera_retry_seconds)
            for camera in settings.cameras
            if camera.enabled
        ]
        self._last_heartbeat: dict[str, float] = {}
        self._last_status: dict[str, str] = {}

    def _persist_crop(self, camera_id: str, crop, alert_id: str, observed_at, category: str, suffix: str) -> tuple[str | None, str | None]:
        if crop is None:
            return None, None
        return self.evidence_store.save(
            camera_id,
            crop,
            f"{alert_id}_{suffix}",
            observed_at,
            category=category,
        )

    def _heartbeat_due(self, camera_id: str, now: float) -> bool:
        last = self._last_heartbeat.get(camera_id, 0.0)
        if now - last >= self.settings.monitoring.heartbeat_interval_seconds:
            self._last_heartbeat[camera_id] = now
            return True
        return False

    def _event_no(self, camera_id: str, observed_at, alert_id: str) -> str:
        short_camera = camera_id.replace("_", "-").upper()[:12]
        return f"AL-{observed_at.strftime('%Y%m%d-%H%M%S')}-{short_camera}-{alert_id[:6].upper()}"

    def _overlay_snapshot(self, camera: CameraStream, frame, event_no: str, observed_at):
        annotated = frame.copy()
        lines = [
            f"Event: {event_no}",
            f"Time: {observed_at.isoformat()}",
            f"Camera: {camera.camera.camera_name}",
            f"Location: {camera.camera.site_name}/{camera.camera.building_name}/{camera.camera.floor_name}/{camera.camera.workshop_name}/{camera.camera.zone_name}",
        ]
        for index, line in enumerate(lines):
            cv2.putText(
                annotated,
                line,
                (16, 28 + index * 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                (0, 215, 255),
                2,
            )
        return annotated

    def _upsert_camera(self, stream: CameraStream, status: str) -> None:
        now = utc_now()
        status_changed = self._last_status.get(stream.camera.camera_id) != status
        if not status_changed and not self._heartbeat_due(stream.camera.camera_id, now.timestamp()):
            return
        self._last_status[stream.camera.camera_id] = status
        self._last_heartbeat[stream.camera.camera_id] = now.timestamp()
        heartbeat = CameraHeartbeat(
            camera_id=stream.camera.camera_id,
            camera_name=stream.camera.camera_name,
            source=stream.camera.source,
            location=stream.camera.location,
            department=stream.camera.department,
            last_status=status,
            last_seen_at=now,
            site_name=stream.camera.site_name,
            building_name=stream.camera.building_name,
            floor_name=stream.camera.floor_name,
            workshop_name=stream.camera.workshop_name,
            zone_name=stream.camera.zone_name,
            responsible_department=stream.camera.responsible_department or stream.camera.department,
            retry_count=stream.retry_count,
            reconnect_count=stream.reconnect_count,
            last_error=stream.last_error,
            last_frame_at=utc_now() if stream.last_frame_ts else None,
            last_fps=stream.last_fps,
        )
        self.repository.upsert_camera(heartbeat.to_record())

    def _finalize_pending_clips(self, camera: CameraStream, frame, observed_at) -> None:
        completed = self.clip_recorder.capture(camera.camera, frame, observed_at)
        for item in completed:
            self.repository.update_alert(
                item["alert_id"],
                {
                    "clip_path": item["clip_path"],
                    "clip_url": item["clip_url"],
                },
            )

    def run(self, max_frames: int | None = None) -> None:
        hard_limit = max_frames if max_frames is not None else self.settings.monitoring.max_frames
        processed_frames = 0
        print(f"[monitor] Starting with repository={self.repository.backend_name} cameras={len(self.streams)}")
        try:
            while True:
                for stream in self.streams:
                    success, frame = stream.read()
                    if not success:
                        self._upsert_camera(stream, "offline")
                        continue

                    observed_at = utc_now()
                    self._finalize_pending_clips(stream, frame, observed_at)
                    self._upsert_camera(stream, "online")

                    if stream.frames_seen % self.settings.monitoring.frame_stride != 0:
                        processed_frames += 1
                        if hard_limit and processed_frames >= hard_limit:
                            print(f"[monitor] Reached frame limit: {hard_limit}")
                            return
                        continue

                    detections = self.detector.detect(frame)
                    alert_candidates = self.event_engine.evaluate(
                        stream.camera.camera_id,
                        detections,
                        observed_at,
                    )
                    if alert_candidates:
                        annotated = self.detector.annotate(frame, detections)
                        for candidate in alert_candidates:
                            governance = self.governance.evaluate(stream.camera, candidate, observed_at)
                            if not governance.allow:
                                continue

                            resolved_person = self.identity_resolver.resolve(stream.camera, candidate, frame)
                            alert_id = uuid.uuid4().hex
                            event_no = self._event_no(stream.camera.camera_id, observed_at, alert_id)
                            snapshot_path, snapshot_url = self.evidence_store.save(
                                stream.camera.camera_id,
                                self._overlay_snapshot(stream, annotated, event_no, observed_at),
                                alert_id,
                                observed_at,
                            )
                            face_crop_path, face_crop_url = self._persist_crop(
                                stream.camera.camera_id,
                                resolved_person.face_crop,
                                alert_id,
                                observed_at,
                                "faces",
                                "face",
                            )
                            badge_crop_path, badge_crop_url = self._persist_crop(
                                stream.camera.camera_id,
                                resolved_person.badge_crop,
                                alert_id,
                                observed_at,
                                "badges",
                                "badge",
                            )
                            identity_status = resolved_person.identity_status
                            review_notes = [item for item in [resolved_person.review_note, governance.note] if item]
                            if governance.review_required and identity_status == "resolved":
                                identity_status = "review_required"

                            alert = AlertRecord(
                                alert_id=alert_id,
                                event_key=candidate.event_key,
                                event_no=event_no,
                                camera_id=stream.camera.camera_id,
                                camera_name=stream.camera.camera_name,
                                location=stream.camera.location,
                                department=stream.camera.department,
                                violation_type="no_helmet",
                                risk_level=governance.risk_level,
                                confidence=round(candidate.confidence, 4),
                                snapshot_path=snapshot_path,
                                snapshot_url=snapshot_url,
                                status="pending",
                                bbox=candidate.bbox,
                                model_name=Path(self.settings.model.path).name,
                                person_id=resolved_person.person_id,
                                person_name=resolved_person.person_name,
                                employee_id=resolved_person.employee_id,
                                team=resolved_person.team,
                                role=resolved_person.role,
                                phone=resolved_person.phone,
                                identity_status=identity_status,
                                identity_source=resolved_person.identity_source,
                                identity_confidence=resolved_person.identity_confidence,
                                badge_text=resolved_person.badge_text,
                                badge_confidence=resolved_person.badge_confidence,
                                face_match_score=resolved_person.face_match_score,
                                face_crop_path=face_crop_path,
                                face_crop_url=face_crop_url,
                                badge_crop_path=badge_crop_path,
                                badge_crop_url=badge_crop_url,
                                review_note=" ".join(review_notes) or None,
                                llm_provider=resolved_person.llm_provider,
                                llm_summary=resolved_person.llm_summary,
                                clip_path=None,
                                clip_url=None,
                                alert_source="cascade_pipeline",
                                governance_note=governance.note,
                                track_id=candidate.track_id,
                                site_name=stream.camera.site_name,
                                building_name=stream.camera.building_name,
                                floor_name=stream.camera.floor_name,
                                workshop_name=stream.camera.workshop_name,
                                zone_name=stream.camera.zone_name,
                                responsible_department=stream.camera.responsible_department or stream.camera.department,
                                created_at=observed_at,
                            )
                            self.repository.insert_alert(alert.to_record())
                            self.repository.insert_audit_log(
                                {
                                    "audit_id": uuid.uuid4().hex,
                                    "entity_type": "alert",
                                    "entity_id": alert.alert_id,
                                    "action_type": "created",
                                    "actor": "system",
                                    "actor_role": "worker",
                                    "payload": {
                                        "event_no": alert.event_no,
                                        "risk_level": alert.risk_level,
                                        "identity_status": alert.identity_status,
                                    },
                                    "created_at": observed_at.isoformat(),
                                }
                            )
                            self.clip_recorder.start(stream.camera, alert.alert_id, alert.event_no or alert.alert_id, observed_at)
                            recipients = stream.camera.alert_emails or self.settings.notifications.default_recipients
                            self.notifier.send_alert_email(alert, recipients)
                            print(
                                "[alert]",
                                alert.event_no,
                                alert.camera_name,
                                alert.snapshot_path,
                                f"confidence={alert.confidence:.2f}",
                            )

                    processed_frames += 1
                    if hard_limit and processed_frames >= hard_limit:
                        print(f"[monitor] Reached frame limit: {hard_limit}")
                        return
                time.sleep(0.01)
        finally:
            for stream in self.streams:
                stream.release()
