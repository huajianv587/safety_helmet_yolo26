from __future__ import annotations

import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from pathlib import Path
from threading import Event, Lock, RLock, Thread
from typing import Any

import cv2
import numpy as np

from helmet_monitoring.core.config import AppSettings
from helmet_monitoring.core.schemas import AlertCandidate, AlertRecord, CameraHeartbeat, ResolvedPerson, utc_now
from helmet_monitoring.api.websocket import dispatch_topic_message
from helmet_monitoring.services.clip_recorder import ClipRecorder
from helmet_monitoring.services.detector import HelmetDetector
from helmet_monitoring.services.event_engine import ViolationEventEngine
from helmet_monitoring.services.governance import FalsePositiveGovernance
from helmet_monitoring.services.identity_resolver import build_identity_resolver
from helmet_monitoring.services.live_frame_hub import get_live_frame_hub
from helmet_monitoring.services.notifier import NotificationService
from helmet_monitoring.services.operations import operations_paths, write_monitor_heartbeat
from helmet_monitoring.services.video_sources import CameraStream
from helmet_monitoring.storage.evidence_store import EvidenceStore
from helmet_monitoring.storage.repository import AlertRepository, build_repository
from helmet_monitoring.tasks.alert_tasks import (
    artifact_idempotency_key,
    deliver_alert_email,
    notification_idempotency_key,
    upload_alert_artifact,
)
from helmet_monitoring.tasks.task_queue import get_queue_stats


@dataclass(slots=True)
class CapturedFrame:
    stream: CameraStream
    frame: Any
    observed_at: Any
    frame_index: int
    stride: int


@dataclass(slots=True)
class InferenceFrame:
    captured: CapturedFrame
    detections: list[Any]
    annotated_frame: Any


@dataclass(slots=True)
class PersistAlertJob:
    candidate: AlertCandidate
    governance: Any
    resolved_person: ResolvedPerson


@dataclass(slots=True)
class PersistFrame:
    stream: CameraStream
    frame: Any
    annotated_frame: Any
    observed_at: Any
    detections: list[Any] = field(default_factory=list)
    alert_jobs: list[PersistAlertJob] = field(default_factory=list)


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
        self._owns_repository = repository is None
        self.repository = repository or build_repository(settings)
        self.evidence_store = EvidenceStore(settings)
        self.detector = HelmetDetector(settings.model, settings.tracking, settings.monitoring)
        self.event_engine = ViolationEventEngine(settings.event_rules)
        self.identity_resolver = build_identity_resolver(settings)
        self.governance = FalsePositiveGovernance(settings)
        self.clip_recorder = ClipRecorder(settings, self.evidence_store)
        self.notifier = NotificationService(settings, self.repository)
        self._live_frame_hub = get_live_frame_hub()
        self._state_lock = RLock()
        self._preview_lock = Lock()
        self._repository_lock = Lock()
        self._clip_lock = Lock()
        self._budget_lock = Lock()
        self._stride_lock = Lock()
        self._last_heartbeat: dict[str, float] = {}
        self._last_status: dict[str, str] = {}
        self._processed_frames = 0
        self._last_alert_event_no: str | None = None
        self._last_preview_ts: dict[str, float] = {}
        self._preview_state: dict[str, dict[str, str]] = {}
        self._dynamic_frame_stride = {
            stream.camera.camera_id: max(1, int(self.settings.monitoring.frame_stride))
            for stream in self.streams
        }
        self._stride_low_water_started: dict[str, float | None] = {
            stream.camera.camera_id: None
            for stream in self.streams
        }
        self._preview_interval_seconds = 1.0 / max(1.0, float(self.settings.monitoring.preview_fps))

        # Optimization: Cache preview frame dimensions to avoid repeated resize calculations
        self._preview_dimensions: dict[str, tuple[int, int]] = {}
        self._preview_max_width = int(os.getenv("HELMET_PREVIEW_MAX_WIDTH", "960"))
        self._jpeg_quality = int(os.getenv("HELMET_JPEG_QUALITY", "75"))

    def _repository_call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        with self._repository_lock:
            method = getattr(self.repository, method_name)
            return method(*args, **kwargs)

    def _broadcast_queue_update(self) -> None:
        try:
            dispatch_topic_message("dashboard", "queue_update", get_queue_stats())
        except Exception:
            pass

    def _queue_fill_ratio(self, queue: Queue[Any] | None) -> float:
        if queue is None or queue.maxsize <= 0:
            return 0.0
        return min(1.0, float(queue.qsize()) / float(queue.maxsize))

    def _rebalance_dynamic_stride(self, inference_queue: Queue[Any] | None) -> None:
        occupancy = self._queue_fill_ratio(inference_queue)
        base_stride = max(1, int(self.settings.monitoring.frame_stride))
        max_stride = max(base_stride, base_stride * 4)
        now = time.monotonic()
        with self._stride_lock:
            for camera_id, current in list(self._dynamic_frame_stride.items()):
                next_value = current
                if occupancy >= 0.75:
                    next_value = min(max_stride, current + 1)
                    self._stride_low_water_started[camera_id] = None
                elif occupancy <= 0.25:
                    started = self._stride_low_water_started.get(camera_id)
                    if current > base_stride:
                        if started is None:
                            self._stride_low_water_started[camera_id] = now
                        elif now - started >= 30.0:
                            next_value = max(base_stride, current - 1)
                            self._stride_low_water_started[camera_id] = now if next_value > base_stride else None
                    else:
                        self._stride_low_water_started[camera_id] = None
                else:
                    self._stride_low_water_started[camera_id] = None
                if next_value != current:
                    self._dynamic_frame_stride[camera_id] = next_value
                self._preview_state.setdefault(camera_id, {})["dynamic_frame_stride"] = str(self._dynamic_frame_stride[camera_id])

    def _current_frame_stride(self, camera_id: str) -> int:
        with self._stride_lock:
            return int(self._dynamic_frame_stride.get(camera_id, max(1, int(self.settings.monitoring.frame_stride))))

    def _record_queue_drop(self, camera_id: str, stage: str) -> None:
        state = self._preview_state.setdefault(camera_id, {})
        key = f"{stage}_dropped_frames"
        current = int(state.get(key, "0") or "0")
        state[key] = str(current + 1)

    def _offer_capture_frame(self, capture_queue: Queue[CapturedFrame], packet: CapturedFrame) -> None:
        try:
            capture_queue.put_nowait(packet)
            return
        except Full:
            pass
        try:
            capture_queue.get_nowait()
        except Empty:
            pass
        try:
            capture_queue.put_nowait(packet)
        except Full:
            self._record_queue_drop(packet.stream.camera.camera_id, "capture")

    def _offer_shared_stage(self, stage_queue: Queue[Any], payload: Any, *, camera_id: str, stage: str) -> bool:
        try:
            stage_queue.put_nowait(payload)
            return True
        except Full:
            self._record_queue_drop(camera_id, stage)
            return False

    def _default_resolved_person(self, stream: CameraStream) -> ResolvedPerson:
        return ResolvedPerson(
            person_id=None,
            person_name=self.settings.identity.unknown_person_name,
            employee_id=None,
            department=stream.camera.department,
            team=None,
            role=None,
            phone=None,
            identity_status="unresolved",
            identity_source="none",
        )

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
        with self._state_lock:
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
            self._repository_call(
                "insert_audit_log",
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
                },
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
        """
        Overlay text on snapshot frame.

        Optimization: Only copy frame when actually needed (not for every call).
        """
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
        with self._state_lock:
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
        self._repository_call("upsert_camera", heartbeat.to_record())
        try:
            dispatch_topic_message(
                "cameras",
                "camera_status",
                {
                    "camera_id": stream.camera.camera_id,
                    "camera_name": stream.camera.camera_name,
                    "status": status,
                    "retry_count": stream.retry_count,
                    "reconnect_count": stream.reconnect_count,
                    "last_error": stream.last_error,
                    "last_fps": stream.last_fps,
                },
            )
        except Exception:
            pass

    def _finalize_pending_clips(self, camera: CameraStream, frame, observed_at) -> None:
        with self._clip_lock:
            completed = self.clip_recorder.capture(camera.camera, frame, observed_at)
        for item in completed:
            self._repository_call(
                "update_alert",
                item["alert_id"],
                {
                    "clip_path": item["clip_path"],
                    "clip_url": item["clip_url"],
                },
            )
            if item.get("clip_path"):
                self._queue_artifact_upload(
                    alert_id=str(item["alert_id"]),
                    camera_id=camera.camera.camera_id,
                    local_path=str(item["clip_path"]),
                    artifact_id=str(item["alert_id"]),
                    created_at=observed_at,
                    category="clips",
                    extension=".mp4",
                    field_name="clip",
                )
            try:
                dispatch_topic_message(
                    "alerts",
                    "alert_updated",
                    {
                        "alert_id": item["alert_id"],
                        "clip_path": item.get("clip_path"),
                        "clip_url": item.get("clip_url"),
                    },
                )
            except Exception:
                pass

    def _advance_frame_budget(self, hard_limit: int | None) -> bool:
        with self._budget_lock:
            self._processed_frames += 1
            if hard_limit and self._processed_frames >= hard_limit:
                print(f"[monitor] Reached frame limit: {hard_limit}")
                return True
            return False

    def _camera_statuses(self) -> list[dict[str, object]]:
        statuses: list[dict[str, object]] = []
        with self._state_lock:
            for stream in self.streams:
                payload = {
                    "camera_id": stream.camera.camera_id,
                    "camera_name": stream.camera.camera_name,
                    "status": self._last_status.get(stream.camera.camera_id, "unknown"),
                    "retry_count": stream.retry_count,
                    "reconnect_count": stream.reconnect_count,
                    "last_error": stream.last_error,
                    "last_fps": stream.last_fps,
                    "dynamic_frame_stride": self._dynamic_frame_stride.get(
                        stream.camera.camera_id,
                        max(1, int(self.settings.monitoring.frame_stride)),
                    ),
                }
                payload.update(self._preview_state.get(stream.camera.camera_id, {}))
                statuses.append(payload)
        return statuses

    def _write_service_state(self, status: str, detail: str | None = None) -> None:
        with self._state_lock:
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
        """
        Write preview frame to disk.

        Optimizations:
        1. Only copy frame if we need to resize (avoid unnecessary copy)
        2. Cache resize dimensions to avoid recalculation
        3. Use configurable JPEG quality (default 75 instead of 85)
        4. Skip frame processing if preview interval not met (checked by caller)
        """
        with self._preview_lock:
            height, width = frame.shape[:2]
            camera_id = stream.camera.camera_id

            if width > self._preview_max_width:
                if camera_id not in self._preview_dimensions:
                    scaled_height = max(1, int(height * (self._preview_max_width / float(width))))
                    self._preview_dimensions[camera_id] = (self._preview_max_width, scaled_height)
                target_width, target_height = self._preview_dimensions[camera_id]
                preview_frame = cv2.resize(frame, (target_width, target_height))
            else:
                preview_frame = frame

            success, encoded = cv2.imencode(".jpg", preview_frame, [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality])
            if not success:
                return

            preview_path = self._live_preview_path(stream.camera.camera_id)
            temp_path = preview_path.with_suffix(preview_path.suffix + ".tmp")
            payload = encoded.tobytes()
            temp_path.write_bytes(payload)
            os.replace(temp_path, preview_path)
            entry = self._live_frame_hub.publish(
                stream.camera.camera_id,
                payload,
                updated_at=observed_at,
                metadata={
                    "preview_path": str(preview_path),
                    "camera_name": stream.camera.camera_name,
                },
            )
            with self._state_lock:
                self._preview_state[stream.camera.camera_id] = {
                    "preview_path": str(preview_path),
                    "preview_updated_at": observed_at.isoformat(),
                    "preview_sequence": str(entry.sequence),
                    "dynamic_frame_stride": str(self._dynamic_frame_stride.get(camera_id, 1)),
                }
            try:
                dispatch_topic_message(
                    "cameras",
                    "frame_state",
                    {
                        "camera_id": stream.camera.camera_id,
                        "camera_name": stream.camera.camera_name,
                        "updated_at": observed_at.isoformat(),
                        "sequence": entry.sequence,
                        "preview_path": str(preview_path),
                        "stream_url": f"/api/v1/helmet/cameras/{stream.camera.camera_id}/stream.mjpg",
                    },
                )
            except Exception:
                pass

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

    def _resolve_person(self, stream: CameraStream, candidate: AlertCandidate, frame) -> ResolvedPerson:
        resolved = self.identity_resolver.resolve(stream.camera, candidate, frame)
        if resolved is None:
            return self._default_resolved_person(stream)
        return resolved

    def _queue_artifact_upload(
        self,
        *,
        alert_id: str,
        camera_id: str,
        local_path: str | None,
        artifact_id: str,
        created_at,
        category: str,
        extension: str,
        field_name: str,
    ) -> None:
        if not self.settings.persistence.upload_to_supabase_storage or not local_path:
            return
        if not Path(str(local_path)).exists():
            return
        upload_alert_artifact.delay(
            alert_id=alert_id,
            camera_id=camera_id,
            artifact_id=artifact_id,
            created_at=created_at.isoformat(),
            local_path=str(local_path),
            category=category,
            extension=extension,
            field_name=field_name,
            idempotency_key=artifact_idempotency_key(alert_id, field_name, str(local_path)),
        )
        self._broadcast_queue_update()

    def _queue_notification_tasks(self, alert: AlertRecord, recipients: tuple[str, ...]) -> None:
        for recipient in recipients:
            deliver_alert_email.delay(
                alert_id=alert.alert_id,
                recipient=recipient,
                idempotency_key=notification_idempotency_key(alert.alert_id, recipient),
            )
        if recipients:
            self._broadcast_queue_update()

    def _persist_alert_job(
        self,
        stream: CameraStream,
        job: PersistAlertJob,
        annotated_frame,
        raw_frame,
        observed_at,
    ) -> None:
        candidate = job.candidate
        governance = job.governance
        resolved_person = job.resolved_person or self._default_resolved_person(stream)
        alert_id = uuid.uuid4().hex
        event_no = self._event_no(stream.camera.camera_id, observed_at, alert_id)
        snapshot_path, snapshot_url = self.evidence_store.save(
            stream.camera.camera_id,
            self._overlay_snapshot(stream, annotated_frame, event_no, observed_at),
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
        self._repository_call("insert_alert", alert.to_record())
        with self._state_lock:
            self._last_alert_event_no = alert.event_no
        self._repository_call(
            "insert_audit_log",
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
                    "backend": self.detector.backend_name,
                },
                "created_at": observed_at.isoformat(),
            },
        )
        with self._clip_lock:
            self.clip_recorder.start(stream.camera, alert.alert_id, alert.event_no or alert.alert_id, observed_at)

        self._queue_artifact_upload(
            alert_id=alert.alert_id,
            camera_id=alert.camera_id,
            local_path=alert.snapshot_path,
            artifact_id=alert.alert_id,
            created_at=observed_at,
            category="alerts",
            extension=".jpg",
            field_name="snapshot",
        )
        self._queue_artifact_upload(
            alert_id=alert.alert_id,
            camera_id=alert.camera_id,
            local_path=alert.face_crop_path,
            artifact_id=f"{alert.alert_id}_face",
            created_at=observed_at,
            category="faces",
            extension=".jpg",
            field_name="face_crop",
        )
        self._queue_artifact_upload(
            alert_id=alert.alert_id,
            camera_id=alert.camera_id,
            local_path=alert.badge_crop_path,
            artifact_id=f"{alert.alert_id}_badge",
            created_at=observed_at,
            category="badges",
            extension=".jpg",
            field_name="badge_crop",
        )

        recipients = tuple(stream.camera.alert_emails or self.settings.notifications.default_recipients)
        self._queue_notification_tasks(alert, recipients)
        try:
            dispatch_topic_message("alerts", "alert_created", alert.to_record())
            dispatch_topic_message(
                "dashboard",
                "metrics_update",
                {
                    "event": "alert_created",
                    "alert_id": alert.alert_id,
                    "camera_id": alert.camera_id,
                    "event_no": alert.event_no,
                    "status": alert.status,
                },
            )
        except Exception:
            pass
        print(
            "[alert]",
            alert.event_no,
            alert.camera_name,
            alert.snapshot_path,
            f"confidence={alert.confidence:.2f}",
        )
        self._write_service_state("running", f"Latest alert: {alert.event_no}")

    def _capture_loop(
        self,
        stream: CameraStream,
        capture_queue: Queue[CapturedFrame],
        persist_queue: Queue[PersistFrame],
        stop_event: Event,
        hard_limit: int | None,
    ) -> None:
        while not stop_event.is_set():
            try:
                success, frame = stream.read()
            except Exception as exc:
                self._record_pipeline_error(stream, "camera_read", exc)
                if self._advance_frame_budget(hard_limit):
                    stop_event.set()
                continue

            observed_at = utc_now()
            try:
                if not success:
                    self._mark_preview_offline(stream, observed_at)
                    self._upsert_camera(stream, "offline")
                    self._write_service_state("running", f"Camera {stream.camera.camera_name} is offline.")
                else:
                    self._upsert_camera(stream, "online")
                    frame_index = max(1, int(getattr(stream, "frames_seen", 1) or 1))
                    stride = self._current_frame_stride(stream.camera.camera_id)
                    if frame_index % stride != 0:
                        self._update_live_preview(stream, frame, observed_at)
                        self._offer_shared_stage(
                            persist_queue,
                            PersistFrame(
                                stream=stream,
                                frame=frame,
                                annotated_frame=frame,
                                observed_at=observed_at,
                            ),
                            camera_id=stream.camera.camera_id,
                            stage="persist",
                        )
                    else:
                        self._offer_capture_frame(
                            capture_queue,
                            CapturedFrame(
                                stream=stream,
                                frame=frame,
                                observed_at=observed_at,
                                frame_index=frame_index,
                                stride=stride,
                            ),
                        )
                    self._write_service_state("running", f"Camera {stream.camera.camera_name} is online.")
            except Exception as exc:
                self._record_pipeline_error(stream, "capture_stage", exc, observed_at=observed_at)
            finally:
                if self._advance_frame_budget(hard_limit):
                    stop_event.set()

    def _inference_worker(
        self,
        inference_queue: Queue[CapturedFrame],
        postprocess_queue: Queue[InferenceFrame],
        drain_event: Event,
    ) -> None:
        while not drain_event.is_set() or not inference_queue.empty():
            try:
                packet = inference_queue.get(timeout=0.05)
            except Empty:
                continue
            try:
                detections = self.detector.detect(packet.frame)
                annotated = packet.frame
                annotate = getattr(self.detector, "annotate", None)
                if detections and callable(annotate):
                    annotated = annotate(packet.frame, detections)
                self._update_live_preview(packet.stream, annotated, packet.observed_at)
                self._offer_shared_stage(
                    postprocess_queue,
                    InferenceFrame(captured=packet, detections=list(detections), annotated_frame=annotated),
                    camera_id=packet.stream.camera.camera_id,
                    stage="postprocess",
                )
            except Exception as exc:
                self._record_pipeline_error(packet.stream, "inference", exc, observed_at=packet.observed_at)
            finally:
                inference_queue.task_done()

    def _postprocess_worker(
        self,
        postprocess_queue: Queue[InferenceFrame],
        persist_queue: Queue[PersistFrame],
        drain_event: Event,
    ) -> None:
        while not drain_event.is_set() or not postprocess_queue.empty():
            try:
                packet = postprocess_queue.get(timeout=0.05)
            except Empty:
                continue
            try:
                alert_jobs: list[PersistAlertJob] = []
                candidates = self.event_engine.evaluate(
                    packet.captured.stream.camera.camera_id,
                    packet.detections,
                    packet.captured.observed_at,
                )
                for candidate in candidates:
                    try:
                        governance = self.governance.evaluate(packet.captured.stream.camera, candidate, packet.captured.observed_at)
                        if not governance.allow:
                            continue
                        resolved_person = self._resolve_person(packet.captured.stream, candidate, packet.captured.frame)
                        alert_jobs.append(
                            PersistAlertJob(
                                candidate=candidate,
                                governance=governance,
                                resolved_person=resolved_person,
                            )
                        )
                    except Exception as exc:
                        self._record_pipeline_error(
                            packet.captured.stream,
                            "postprocess_candidate",
                            exc,
                            observed_at=packet.captured.observed_at,
                            payload={"event_key": candidate.event_key, "track_id": candidate.track_id},
                        )
                self._offer_shared_stage(
                    persist_queue,
                    PersistFrame(
                        stream=packet.captured.stream,
                        frame=packet.captured.frame,
                        annotated_frame=packet.annotated_frame,
                        observed_at=packet.captured.observed_at,
                        detections=packet.detections,
                        alert_jobs=alert_jobs,
                    ),
                    camera_id=packet.captured.stream.camera.camera_id,
                    stage="persist",
                )
            except Exception as exc:
                self._record_pipeline_error(packet.captured.stream, "postprocess", exc, observed_at=packet.captured.observed_at)
            finally:
                postprocess_queue.task_done()

    def _persist_worker(self, persist_queue: Queue[PersistFrame], drain_event: Event) -> None:
        while not drain_event.is_set() or not persist_queue.empty():
            try:
                packet = persist_queue.get(timeout=0.05)
            except Empty:
                continue
            try:
                self._finalize_pending_clips(packet.stream, packet.frame, packet.observed_at)
                for job in packet.alert_jobs:
                    self._persist_alert_job(
                        packet.stream,
                        job,
                        packet.annotated_frame,
                        packet.frame,
                        packet.observed_at,
                    )
            except Exception as exc:
                self._record_pipeline_error(packet.stream, "persist", exc, observed_at=packet.observed_at)
            finally:
                persist_queue.task_done()

    def run(self, max_frames: int | None = None) -> None:
        hard_limit = max_frames if max_frames is not None else self.settings.monitoring.max_frames
        enabled_cameras = len(self.streams)
        capture_queues = {
            stream.camera.camera_id: Queue(maxsize=2)
            for stream in self.streams
        }
        inference_queue: Queue[CapturedFrame] = Queue(maxsize=max(2, enabled_cameras * 2))
        postprocess_queue: Queue[InferenceFrame] = Queue(maxsize=max(2, enabled_cameras * 2))
        persist_queue: Queue[PersistFrame] = Queue(maxsize=max(4, enabled_cameras * 4))
        stop_event = Event()
        drain_event = Event()
        capture_threads = [
            Thread(
                target=self._capture_loop,
                name=f"Capture-{stream.camera.camera_id}",
                args=(stream, capture_queues[stream.camera.camera_id], persist_queue, stop_event, hard_limit),
                daemon=True,
            )
            for stream in self.streams
        ]
        inference_workers = [
            Thread(
                target=self._inference_worker,
                name=f"Inference-{index}",
                args=(inference_queue, postprocess_queue, drain_event),
                daemon=True,
            )
            for index in range(max(1, int(self.settings.monitoring.inference_workers)))
        ]
        postprocess_workers = [
            Thread(
                target=self._postprocess_worker,
                name=f"Postprocess-{index}",
                args=(postprocess_queue, persist_queue, drain_event),
                daemon=True,
            )
            for index in range(max(1, int(self.settings.monitoring.postprocess_workers)))
        ]
        persist_workers = [
            Thread(
                target=self._persist_worker,
                name="Persist-0",
                args=(persist_queue, drain_event),
                daemon=True,
            )
        ]
        backend_name = str(getattr(self.detector, "backend_name", "detector"))

        print(
            f"[monitor] Starting with repository={self.repository.backend_name} "
            f"cameras={len(self.streams)} backend={backend_name}"
        )
        self._write_service_state(
            "starting",
            f"Initializing {len(self.streams)} camera streams with {backend_name}.",
        )

        for thread in [*capture_threads, *inference_workers, *postprocess_workers, *persist_workers]:
            thread.start()

        try:
            while True:
                moved = False
                self._rebalance_dynamic_stride(inference_queue)
                for stream in self.streams:
                    if inference_queue.full():
                        break
                    camera_id = stream.camera.camera_id
                    try:
                        packet = capture_queues[camera_id].get_nowait()
                    except Empty:
                        continue
                    if self._offer_shared_stage(inference_queue, packet, camera_id=camera_id, stage="inference"):
                        moved = True
                    else:
                        self._offer_capture_frame(capture_queues[camera_id], packet)

                capture_pending = any(not queue.empty() for queue in capture_queues.values())
                frame_limit_reached = bool(hard_limit and self._processed_frames >= hard_limit)
                if (
                    (stop_event.is_set() or frame_limit_reached)
                    and not capture_pending
                    and inference_queue.empty()
                    and postprocess_queue.empty()
                    and persist_queue.empty()
                ):
                    break
                if not moved:
                    stop_event.wait(0.01)
        finally:
            stop_event.set()
            for thread in capture_threads:
                thread.join(timeout=2)
            drain_event.set()
            drain_deadline = time.time() + 5.0
            while time.time() < drain_deadline:
                pending = (
                    any(not queue.empty() for queue in capture_queues.values())
                    or not inference_queue.empty()
                    or not postprocess_queue.empty()
                    or not persist_queue.empty()
                )
                if not pending:
                    break
                stop_event.wait(0.05)
            for thread in [*inference_workers, *postprocess_workers, *persist_workers]:
                thread.join(timeout=2)
            self._write_service_state("stopped", "Monitor process stopped.")
            for stream in self.streams:
                stream.release()
            if self._owns_repository:
                try:
                    self.repository.close()
                except Exception:
                    pass
