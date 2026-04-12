from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from helmet_monitoring.core.config import AppSettings
from helmet_monitoring.core.schemas import AlertRecord, CameraHeartbeat, utc_now
from helmet_monitoring.services.clip_recorder import ClipRecorder
from helmet_monitoring.services.detector import HelmetDetector
from helmet_monitoring.services.event_engine import ViolationEventEngine
from helmet_monitoring.services.governance import FalsePositiveGovernance
from helmet_monitoring.services.identity_resolver import build_identity_resolver
from helmet_monitoring.services.notifier import NotificationService
from helmet_monitoring.services.operations import operations_paths, write_monitor_heartbeat
from helmet_monitoring.services.video_sources import CameraStream
from helmet_monitoring.storage.evidence_store import EvidenceStore
from helmet_monitoring.storage.repository import AlertRepository, build_repository


class SafetyHelmetMonitor:
    def __init__(self, settings: AppSettings, repository: AlertRepository | None = None) -> None:
        if not settings.cameras:
            raise ValueError("At least one camera source is required in configs/runtime.json")
        self.streams = [
            CameraStream(camera, retry_seconds=settings.monitoring.camera_retry_seconds)
            for camera in settings.cameras
            if camera.enabled
        ]
        if not self.streams:
            raise ValueError("At least one enabled camera source is required in configs/runtime.json")
        self.settings = settings
        self.repository = repository or build_repository(settings)
        self.evidence_store = EvidenceStore(settings)
        self.detector = HelmetDetector(settings.model, settings.tracking)
        self.event_engine = ViolationEventEngine(settings.event_rules)
        self.identity_resolver = build_identity_resolver(settings)
        self.governance = FalsePositiveGovernance(settings)
        self.clip_recorder = ClipRecorder(settings, self.evidence_store)
        self.notifier = NotificationService(settings, self.repository)
        self._last_heartbeat: dict[str, float] = {}
        self._last_status: dict[str, str] = {}
        self._processed_frames = 0
        self._last_alert_event_no: str | None = None
        self._last_preview_ts: dict[str, float] = {}
        self._preview_state: dict[str, dict[str, str]] = {}
        self._preview_interval_seconds = 1.0 / max(1.0, float(self.settings.monitoring.preview_fps))

    def _record_pipeline_error(
        self,
        stream: CameraStream,
        stage: str,
        exc: Exception,
        *,
        observed_at=None,
        payload: dict[str, object] | None = None,
    ) -> None:
        timestamp = observed_at or utc_now()
        detail = f"{stage}: {exc}"
        stream.last_error = detail
        preview_state = self._preview_state.setdefault(stream.camera.camera_id, {})
        preview_state["last_error"] = detail
        preview_state["last_error_at"] = timestamp.isoformat()
        try:
            self._upsert_camera(stream, "error")
        except Exception as camera_exc:
            print(
                "[monitor][error]",
                f"camera={stream.camera.camera_id}",
                "stage=upsert_camera_error",
                f"error={camera_exc}",
            )
        try:
            self.repository.insert_audit_log(
                {
                    "audit_id": uuid.uuid4().hex,
                    "entity_type": "camera",
                    "entity_id": stream.camera.camera_id,
                    "action_type": "pipeline_error",
                    "actor": "system",
                    "actor_role": "worker",
                    "payload": {
                        "camera_name": stream.camera.camera_name,
                        "stage": stage,
                        "error": str(exc),
                        **(payload or {}),
                    },
                    "created_at": timestamp.isoformat(),
                }
            )
        except Exception as audit_exc:
            print(
                "[monitor][error]",
                f"camera={stream.camera.camera_id}",
                "stage=audit_log_error",
                f"error={audit_exc}",
            )
        self._write_service_state("running", f"Camera {stream.camera.camera_name} {stage} failed: {exc}")
        print(
            "[monitor][error]",
            f"camera={stream.camera.camera_id}",
            f"stage={stage}",
            f"error={exc}",
        )

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

    def _advance_frame_budget(self, processed_frames: int, hard_limit: int | None) -> tuple[int, bool]:
        processed_frames += 1
        self._processed_frames = processed_frames
        if hard_limit and processed_frames >= hard_limit:
            print(f"[monitor] Reached frame limit: {hard_limit}")
            return processed_frames, True
        return processed_frames, False

    def _camera_statuses(self) -> list[dict[str, object]]:
        statuses: list[dict[str, object]] = []
        for stream in self.streams:
            payload = {
                "camera_id": stream.camera.camera_id,
                "camera_name": stream.camera.camera_name,
                "status": self._last_status.get(stream.camera.camera_id, "unknown"),
                "retry_count": stream.retry_count,
                "reconnect_count": stream.reconnect_count,
                "last_error": stream.last_error,
                "last_fps": stream.last_fps,
            }
            payload.update(self._preview_state.get(stream.camera.camera_id, {}))
            statuses.append(payload)
        return statuses

    def _write_service_state(self, status: str, detail: str | None = None) -> None:
        write_monitor_heartbeat(
            self.settings,
            status=status,
            detail=detail,
            processed_frames=self._processed_frames,
            repository_backend=self.repository.backend_name,
            config_path=str(self.settings.config_path),
            model_path=self.settings.model.path,
            camera_statuses=self._camera_statuses(),
            last_alert_event_no=self._last_alert_event_no,
        )

    def _live_preview_path(self, camera_id: str) -> Path:
        paths = operations_paths(self.settings)
        target = paths["live_frames_dir"] / f"{camera_id}.jpg"
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _write_preview_frame(self, stream: CameraStream, frame, observed_at) -> None:
        preview_frame = frame.copy()
        height, width = preview_frame.shape[:2]
        max_width = 960
        if width > max_width:
            scaled_height = max(1, int(height * (max_width / float(width))))
            preview_frame = cv2.resize(preview_frame, (max_width, scaled_height))

        success, encoded = cv2.imencode(".jpg", preview_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not success:
            return

        preview_path = self._live_preview_path(stream.camera.camera_id)
        temp_path = preview_path.with_suffix(preview_path.suffix + ".tmp")
        temp_path.write_bytes(encoded.tobytes())
        os.replace(temp_path, preview_path)
        self._preview_state[stream.camera.camera_id] = {
            "preview_path": str(preview_path),
            "preview_updated_at": observed_at.isoformat(),
        }

    def _update_live_preview(self, stream: CameraStream, frame, observed_at) -> None:
        now_ts = observed_at.timestamp()
        last_write = self._last_preview_ts.get(stream.camera.camera_id, 0.0)
        if now_ts - last_write < self._preview_interval_seconds:
            return
        self._write_preview_frame(stream, frame, observed_at)
        self._last_preview_ts[stream.camera.camera_id] = now_ts

    def _mark_preview_offline(self, stream: CameraStream, observed_at) -> None:
        now_ts = observed_at.timestamp()
        last_write = self._last_preview_ts.get(stream.camera.camera_id, 0.0)
        if now_ts - last_write < self._preview_interval_seconds:
            return

        canvas = np.zeros((540, 960, 3), dtype=np.uint8)
        cv2.putText(canvas, "STREAM OFFLINE", (42, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.25, (0, 170, 255), 3)
        cv2.putText(canvas, f"Camera: {stream.camera.camera_name}", (42, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (235, 235, 235), 2)
        cv2.putText(canvas, f"Updated: {observed_at.isoformat()}", (42, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 200), 2)
        detail = stream.last_error or "Waiting for the phone stream to reconnect."
        cv2.putText(canvas, detail[:88], (42, 320), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 2)
        self._write_preview_frame(stream, canvas, observed_at)
        self._last_preview_ts[stream.camera.camera_id] = now_ts

    def _process_alert_candidate(self, stream: CameraStream, candidate, annotated, frame, observed_at) -> None:
        governance = self.governance.evaluate(stream.camera, candidate, observed_at)
        if not governance.allow:
            return

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
        self._last_alert_event_no = alert.event_no
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
        self._write_service_state("running", f"Latest alert: {alert.event_no}")

    def _process_online_frame(self, stream: CameraStream, frame, observed_at) -> None:
        self._finalize_pending_clips(stream, frame, observed_at)
        self._upsert_camera(stream, "online")
        self._write_service_state("running", f"Camera {stream.camera.camera_name} is online.")

        if stream.frames_seen % self.settings.monitoring.frame_stride != 0:
            self._update_live_preview(stream, frame, observed_at)
            return

        detections = self.detector.detect(frame)
        preview_frame = self.detector.annotate(frame, detections) if detections else frame
        self._update_live_preview(stream, preview_frame, observed_at)
        alert_candidates = self.event_engine.evaluate(
            stream.camera.camera_id,
            detections,
            observed_at,
        )
        if not alert_candidates:
            return

        annotated = preview_frame
        for candidate in alert_candidates:
            try:
                self._process_alert_candidate(stream, candidate, annotated, frame, observed_at)
            except Exception as exc:
                self._record_pipeline_error(
                    stream,
                    "alert_candidate",
                    exc,
                    observed_at=observed_at,
                    payload={"event_key": candidate.event_key, "track_id": candidate.track_id},
                )

    def run(self, max_frames: int | None = None) -> None:
        hard_limit = max_frames if max_frames is not None else self.settings.monitoring.max_frames
        processed_frames = 0
        print(f"[monitor] Starting with repository={self.repository.backend_name} cameras={len(self.streams)}")
        self._write_service_state("starting", f"Initializing {len(self.streams)} camera streams.")
        try:
            while True:
                for stream in self.streams:
                    try:
                        success, frame = stream.read()
                    except Exception as exc:
                        self._record_pipeline_error(stream, "camera_read", exc)
                        processed_frames, should_stop = self._advance_frame_budget(processed_frames, hard_limit)
                        if should_stop:
                            self._write_service_state("stopped", f"Frame limit reached at {hard_limit}.")
                            return
                        continue
                    if not success:
                        self._mark_preview_offline(stream, utc_now())
                        self._upsert_camera(stream, "offline")
                        self._write_service_state("running", f"Camera {stream.camera.camera_name} is offline.")
                        processed_frames, should_stop = self._advance_frame_budget(processed_frames, hard_limit)
                        if should_stop:
                            self._write_service_state("stopped", f"Frame limit reached at {hard_limit}.")
                            return
                        continue

                    observed_at = utc_now()
                    try:
                        self._process_online_frame(stream, frame, observed_at)
                    except Exception as exc:
                        self._record_pipeline_error(stream, "camera_pipeline", exc, observed_at=observed_at)

                    processed_frames, should_stop = self._advance_frame_budget(processed_frames, hard_limit)
                    if should_stop:
                        self._write_service_state("stopped", f"Frame limit reached at {hard_limit}.")
                        return
                time.sleep(0.01)
        finally:
            self._write_service_state("stopped", "Monitor process stopped.")
            for stream in self.streams:
                stream.release()
