from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import cv2
import numpy as np

from helmet_monitoring.core.config import CameraSettings, load_settings
from helmet_monitoring.core.schemas import AlertRecord, DetectionRecord, utc_now
from helmet_monitoring.services.clip_recorder import ClipRecorder
from helmet_monitoring.services.event_engine import ViolationEventEngine
from helmet_monitoring.services.governance import FalsePositiveGovernance
from helmet_monitoring.services.identity_resolver import build_identity_resolver
from helmet_monitoring.services.notifier import NotificationService
from helmet_monitoring.services.readiness import ensure_workspace_scaffold
from helmet_monitoring.services.runtime_profiles import local_smoke_settings
from helmet_monitoring.services.workflow import AlertWorkflowService
from helmet_monitoring.storage.evidence_store import EvidenceStore
from helmet_monitoring.storage.repository import LocalAlertRepository, build_repository
from helmet_monitoring.utils.image_io import read_image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an end-to-end local smoke test for the product pipeline.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--use-model", action="store_true", help="Use the YOLO model for detection instead of simulated detections.")
    parser.add_argument(
        "--strict-runtime",
        action="store_true",
        help="Use the configured backend/services instead of downgrading to the local-only smoke profile.",
    )
    parser.add_argument(
        "--require-model-detection",
        action="store_true",
        help="Fail unless a real model inference finds a no-helmet detection on a labeled smoke sample.",
    )
    parser.add_argument(
        "--max-sample-search",
        type=int,
        default=25,
        help="Maximum labeled samples to inspect when searching for a real no-helmet detection.",
    )
    parser.add_argument(
        "--final-status",
        default="false_positive",
        choices=["false_positive", "remediated", "ignored"],
        help="Final workflow state to apply after creation.",
    )
    parser.add_argument(
        "--notification-mode",
        default="auto",
        choices=["auto", "smtp", "dry_run", "skip"],
        help="Notification validation mode. auto=smtp when configured, otherwise dry_run.",
    )
    parser.add_argument(
        "--notification-recipient",
        action="append",
        default=[],
        help="Repeatable recipient override used by the smoke notification validation.",
    )
    parser.add_argument(
        "--require-notification-success",
        action="store_true",
        help="Fail unless at least one smoke notification is sent successfully in SMTP mode.",
    )
    return parser.parse_args()


def _select_camera(settings) -> CameraSettings:
    for camera in settings.cameras:
        if camera.enabled:
            return camera
    return CameraSettings(
        camera_id="smoke-cam",
        camera_name="Smoke Camera",
        source="0",
        location="Local Smoke Test",
        department="QA",
        enabled=True,
        site_name="Smoke Site",
        building_name="Smoke Building",
        floor_name="Floor 1",
        workshop_name="QA Lab",
        zone_name="Bench 1",
        responsible_department="QA",
    )


def _dedupe_recipients(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in values:
        recipient = str(raw).strip()
        if not recipient:
            continue
        normalized = recipient.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(recipient)
    return tuple(ordered)


def _resolve_notification_mode(settings, args: argparse.Namespace) -> str:
    if args.notification_mode != "auto":
        return args.notification_mode
    if settings.notifications.is_email_configured:
        return "smtp"
    return "dry_run"


def _resolve_notification_recipients(settings, camera: CameraSettings, args: argparse.Namespace) -> tuple[str, ...]:
    configured: list[str] = []
    configured.extend(args.notification_recipient or [])
    configured.extend(camera.alert_emails)
    configured.extend(settings.notifications.default_recipients)
    if settings.notifications.is_email_configured:
        fallback_recipient = settings.notifications.smtp_from_email or settings.notifications.smtp_username
        if fallback_recipient:
            configured.append(fallback_recipient)
    if not configured:
        configured.append("smoke@example.local")
    return _dedupe_recipients(configured)


def _normalize_label(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _load_dataset_names() -> dict[int, str]:
    dataset_yaml = REPO_ROOT / "configs" / "datasets" / "shwd_yolo26.yaml"
    if not dataset_yaml.exists():
        return {}
    names: dict[int, str] = {}
    inside_names = False
    for raw_line in dataset_yaml.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not inside_names:
            if stripped == "names:":
                inside_names = True
            continue
        if not raw_line.startswith("  "):
            break
        key, separator, value = stripped.partition(":")
        if separator and key.strip().isdigit():
            names[int(key.strip())] = _normalize_label(value.strip().strip("'\""))
    return names


def _violation_class_ids(settings) -> set[int]:
    dataset_names = _load_dataset_names()
    configured_labels = {_normalize_label(item) for item in settings.model.violation_labels}
    matched = {class_id for class_id, label in dataset_names.items() if label in configured_labels}
    return matched or {1}


def _label_contains_violation(label_path: Path, class_ids: set[int]) -> bool:
    try:
        lines = label_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        class_token = stripped.split(maxsplit=1)[0]
        if class_token.isdigit() and int(class_token) in class_ids:
            return True
    return False


def _resolve_image_path(image_dir: Path, stem: str) -> Path | None:
    for suffix in (".jpg", ".jpeg", ".png"):
        candidate = image_dir / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _iter_sample_paths(settings, *, require_violation: bool, limit: int | None = None):
    images_root = REPO_ROOT / "data" / "helmet_detection_dataset" / "images"
    if require_violation:
        labels_root = REPO_ROOT / "data" / "helmet_detection_dataset" / "labels"
        violation_ids = _violation_class_ids(settings)
        yielded = 0
        for folder in ("val", "train"):
            label_dir = labels_root / folder
            image_dir = images_root / folder
            if not label_dir.exists() or not image_dir.exists():
                continue
            for label_path in sorted(label_dir.glob("*.txt")):
                if not _label_contains_violation(label_path, violation_ids):
                    continue
                image_path = _resolve_image_path(image_dir, label_path.stem)
                if image_path is None:
                    continue
                yield image_path
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
        return

    yielded = 0
    for folder in ("val", "train"):
        image_dir = images_root / folder
        if not image_dir.exists():
            continue
        for pattern in ("*.jpg", "*.jpeg", "*.png"):
            for image_path in sorted(image_dir.glob(pattern)):
                yield image_path
                yielded += 1
                if limit is not None and yielded >= limit:
                    return


def _load_sample_frame_with_source(
    settings=None,
    *,
    require_violation: bool = False,
    limit: int | None = None,
) -> tuple[np.ndarray, str]:
    if settings is not None:
        for image_path in _iter_sample_paths(settings, require_violation=require_violation, limit=limit):
            frame = read_image(image_path)
            if frame is not None:
                return frame, str(image_path)
    else:
        images_root = REPO_ROOT / "data" / "helmet_detection_dataset" / "images"
        for folder in ("val", "train"):
            image_dir = images_root / folder
            if not image_dir.exists():
                continue
            for pattern in ("*.jpg", "*.jpeg", "*.png"):
                for image_path in sorted(image_dir.glob(pattern)):
                    frame = read_image(image_path)
                    if frame is not None:
                        return frame, str(image_path)
    return np.full((480, 640, 3), 220, dtype=np.uint8), "synthetic_blank_frame"


def _simulate_detection(frame, settings) -> list[DetectionRecord]:
    height, width = frame.shape[:2]
    return [
        DetectionRecord(
            class_id=1,
            label="no_helmet",
            confidence=max(0.85, settings.event_rules.min_confidence_for_alert),
            x1=max(20, width // 4),
            y1=max(20, height // 8),
            x2=min(width - 20, width * 3 // 4),
            y2=min(height - 20, height * 7 // 8),
            is_violation=True,
            track_id="smoke-track-1",
        )
    ]


def _collect_detections(
    frame,
    settings,
    use_model: bool,
    *,
    require_model_detection: bool = False,
) -> tuple[list[DetectionRecord], str]:
    if use_model:
        try:
            from helmet_monitoring.services.detector import HelmetDetector

            detector = HelmetDetector(settings.model, settings.tracking)
            detections = detector.detect(frame)
            violations = [item for item in detections if item.is_violation]
            if violations:
                return violations, detector.model_name
            if require_model_detection:
                raise RuntimeError("Model did not detect any no-helmet targets on the selected labeled smoke sample.")
            return _simulate_detection(frame, settings), f"{detector.model_name}|fallback_no_violation"
        except Exception as exc:
            if require_model_detection:
                raise
            return _simulate_detection(frame, settings), f"simulated_detector|model_error={type(exc).__name__}"
    return _simulate_detection(frame, settings), "simulated_detector"


def _prepare_smoke_input(settings, args: argparse.Namespace) -> tuple[np.ndarray, list[DetectionRecord], str, str]:
    if args.require_model_detection and not args.use_model:
        raise RuntimeError("--require-model-detection requires --use-model.")

    if not args.use_model:
        frame, sample_source = _load_sample_frame_with_source()
        detections, model_name = _collect_detections(frame, settings, use_model=False)
        return frame, detections, model_name, sample_source

    if args.require_model_detection:
        from helmet_monitoring.services.detector import HelmetDetector

        detector = HelmetDetector(settings.model, settings.tracking)
        tested = 0
        for sample_path in _iter_sample_paths(
            settings,
            require_violation=True,
            limit=max(1, args.max_sample_search),
        ):
            frame = read_image(sample_path)
            if frame is None:
                continue
            tested += 1
            detections = detector.detect(frame)
            violations = [item for item in detections if item.is_violation]
            if violations:
                return frame, violations, detector.model_name, str(sample_path)
        raise RuntimeError(
            f"Model did not detect a no-helmet violation in the first {tested or 0} labeled smoke samples."
        )

    frame, sample_source = _load_sample_frame_with_source()
    detections, model_name = _collect_detections(frame, settings, use_model=True)
    return frame, detections, model_name, sample_source


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    if not args.strict_runtime:
        settings = local_smoke_settings(settings)
        settings = replace(
            settings,
            face_recognition=replace(settings.face_recognition, enabled=False),
            ocr=replace(settings.ocr, enabled=False, provider="none"),
            llm_fallback=replace(settings.llm_fallback, enabled=False),
        )
    ensure_workspace_scaffold(settings)

    repository = LocalAlertRepository(settings.resolve_path(settings.persistence.runtime_dir))
    if args.strict_runtime:
        repository = build_repository(settings, require_requested_backend=True)
    evidence_store = EvidenceStore(settings)
    notifier = NotificationService(settings, repository)
    workflow = AlertWorkflowService(repository)
    event_engine = ViolationEventEngine(settings.event_rules)
    governance = FalsePositiveGovernance(settings)
    identity_resolver = build_identity_resolver(settings)
    clip_recorder = ClipRecorder(settings, evidence_store)

    camera = _select_camera(settings)
    frame, detections, model_name, sample_source = _prepare_smoke_input(settings, args)

    observed_at = utc_now()
    candidate = None
    for index in range(settings.event_rules.alert_frames):
        alerts = event_engine.evaluate(camera.camera_id, detections, observed_at + timedelta(milliseconds=200 * index))
        if alerts:
            candidate = alerts[0]
            break
    if candidate is None:
        raise RuntimeError("Smoke test failed to synthesize an alert candidate.")

    decision = governance.evaluate(camera, candidate, observed_at)
    if not decision.allow:
        raise RuntimeError(f"Governance blocked smoke alert: {decision.note}")

    resolved_person = identity_resolver.resolve(camera, candidate, frame)
    alert_id = uuid.uuid4().hex
    event_no = f"SMK-{observed_at.strftime('%Y%m%d-%H%M%S')}-{alert_id[:6].upper()}"
    annotated = frame.copy()
    cv2.putText(annotated, event_no, (24, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    snapshot_path, snapshot_url = evidence_store.save(camera.camera_id, annotated, alert_id, observed_at)

    face_crop_path = face_crop_url = None
    badge_crop_path = badge_crop_url = None
    if resolved_person.face_crop is not None:
        face_crop_path, face_crop_url = evidence_store.save(
            camera.camera_id,
            resolved_person.face_crop,
            f"{alert_id}_face",
            observed_at,
            category="faces",
        )
    if resolved_person.badge_crop is not None:
        badge_crop_path, badge_crop_url = evidence_store.save(
            camera.camera_id,
            resolved_person.badge_crop,
            f"{alert_id}_badge",
            observed_at,
            category="badges",
        )

    for offset in range(max(1, clip_recorder.buffer_size)):
        clip_recorder.capture(camera, frame, observed_at + timedelta(milliseconds=offset * 80))
    clip_recorder.start(camera, alert_id, event_no, observed_at)
    clip_path = None
    clip_url = None
    for offset in range(max(1, clip_recorder.post_frames)):
        completed = clip_recorder.capture(camera, frame, observed_at + timedelta(milliseconds=1000 + offset * 80))
        if completed:
            clip_path = completed[0]["clip_path"]
            clip_url = completed[0]["clip_url"]

    review_notes = [item for item in [resolved_person.review_note, decision.note] if item]
    alert = AlertRecord(
        alert_id=alert_id,
        event_key=candidate.event_key,
        event_no=event_no,
        camera_id=camera.camera_id,
        camera_name=camera.camera_name,
        location=camera.location,
        department=camera.department,
        violation_type="no_helmet",
        risk_level=decision.risk_level,
        confidence=round(candidate.confidence, 4),
        snapshot_path=snapshot_path,
        snapshot_url=snapshot_url,
        status="pending",
        bbox=candidate.bbox,
        model_name=model_name,
        person_id=resolved_person.person_id,
        person_name=resolved_person.person_name,
        employee_id=resolved_person.employee_id,
        team=resolved_person.team,
        role=resolved_person.role,
        phone=resolved_person.phone,
        identity_status=resolved_person.identity_status,
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
        clip_path=clip_path,
        clip_url=clip_url,
        alert_source="smoke_product",
        governance_note=decision.note,
        track_id=candidate.track_id,
        site_name=camera.site_name,
        building_name=camera.building_name,
        floor_name=camera.floor_name,
        workshop_name=camera.workshop_name,
        zone_name=camera.zone_name,
        responsible_department=camera.responsible_department or camera.department,
        created_at=observed_at,
    )
    repository.insert_alert(alert.to_record())
    repository.insert_audit_log(
        {
            "audit_id": uuid.uuid4().hex,
            "entity_type": "alert",
            "entity_id": alert_id,
            "action_type": "created",
            "actor": "smoke_test",
            "actor_role": "system",
            "payload": {"event_no": event_no, "risk_level": alert.risk_level},
            "created_at": utc_now().isoformat(),
        }
    )

    notification_mode = _resolve_notification_mode(settings, args)
    recipients = _resolve_notification_recipients(settings, camera, args)
    if notification_mode == "smtp":
        notifier.send_alert_email(alert, recipients)
    elif notification_mode == "dry_run":
        notifier.simulate_alert_email(alert, recipients, reason="smoke_product")
    workflow.assign(
        alert.to_record(),
        actor="smoke.operator",
        actor_role="admin",
        assignee="safety.manager",
        assignee_email="safety.manager@example.local",
        note="Smoke test assignment.",
    )
    workflow.update_status(
        alert.to_record(),
        actor="smoke.operator",
        actor_role="admin",
        new_status=args.final_status,
        note="Smoke test closure.",
        corrected_identity=None,
    )

    alert_actions = repository.list_alert_actions(alert_id=alert_id, limit=20)
    notification_logs = repository.list_notification_logs(alert_id=alert_id, limit=20)
    hard_cases = repository.list_hard_cases(alert_id=alert_id, limit=20)
    final_alert = repository.get_alert(alert_id) or {}

    if notification_mode != "skip" and not notification_logs:
        raise RuntimeError("Smoke notification validation did not create any notification log records.")
    if args.require_notification_success and notification_mode == "smtp":
        sent_count = sum(1 for item in notification_logs if str(item.get("status") or "").strip().lower() == "sent")
        if sent_count <= 0:
            raise RuntimeError("Smoke notification validation did not send any successful SMTP notifications.")

    notification_statuses = ",".join(
        str(item.get("status") or "--")
        for item in notification_logs
    )

    print(f"backend={repository.backend_name}")
    print(f"event_no={event_no}")
    print(f"model_name={model_name}")
    print(f"sample_source={sample_source}")
    print(f"snapshot_path={snapshot_path}")
    print(f"clip_path={clip_path}")
    print(f"identity_status={resolved_person.identity_status}")
    print(f"notification_mode={notification_mode}")
    print(f"notification_recipients={','.join(recipients)}")
    print(f"notification_statuses={notification_statuses}")
    print(f"final_status={final_alert.get('status')}")
    print(f"actions={len(alert_actions)}")
    print(f"notifications={len(notification_logs)}")
    print(f"hard_cases={len(hard_cases)}")


if __name__ == "__main__":
    main()
