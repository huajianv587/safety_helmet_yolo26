from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import CameraSettings, load_settings
from helmet_monitoring.core.schemas import AlertCandidate, AlertRecord, CameraHeartbeat
from helmet_monitoring.services.identity_resolver import build_identity_resolver
from helmet_monitoring.services.person_directory import PersonDirectory
from helmet_monitoring.storage.evidence_store import EvidenceStore
from helmet_monitoring.storage.repository import build_repository
from helmet_monitoring.utils.image_io import read_image


UTC = timezone.utc
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trigger one test alert into the configured backend.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--person-id", default="person-001", help="Registry person ID whose sample image will be used.")
    parser.add_argument("--image", default="", help="Optional explicit image path. Defaults to the first image under artifacts/identity/faces/<person_id>.")
    parser.add_argument("--camera-id", default="", help="Optional enabled camera ID to attach to the test alert.")
    return parser.parse_args()


def _select_camera(settings, camera_id: str) -> CameraSettings:
    if camera_id:
        for camera in settings.cameras:
            if camera.camera_id == camera_id:
                return camera
        raise RuntimeError(f"Camera not found in runtime config: {camera_id}")
    for camera in settings.cameras:
        if camera.enabled:
            return camera
    raise RuntimeError("No enabled camera found in configs/runtime.json")


def _find_image(settings, person_id: str, image_arg: str) -> Path:
    if image_arg:
        image_path = Path(image_arg)
        if not image_path.is_absolute():
            image_path = (REPO_ROOT / image_path).resolve()
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        return image_path

    face_root = settings.resolve_path(settings.face_recognition.face_profile_dir)
    person_dir = face_root / person_id
    if not person_dir.exists():
        raise FileNotFoundError(f"Person face directory not found: {person_dir}")
    for image_path in sorted(person_dir.iterdir()):
        if image_path.is_file() and image_path.suffix.lower() in IMAGE_SUFFIXES:
            return image_path
    raise FileNotFoundError(f"No face images found under: {person_dir}")


def _build_candidate(frame, camera: CameraSettings, observed_at: datetime) -> AlertCandidate:
    height, width = frame.shape[:2]
    margin_x = max(16, width // 10)
    top = max(8, height // 20)
    bottom = max(top + 32, min(height - 8, int(height * 0.95)))
    bbox = {
        "x1": margin_x,
        "y1": top,
        "x2": max(margin_x + 32, width - margin_x),
        "y2": bottom,
    }
    return AlertCandidate(
        event_key=f"{camera.camera_id}:manual-test",
        camera_id=camera.camera_id,
        confidence=0.98,
        label="no_helmet",
        bbox=bbox,
        first_seen_at=observed_at,
        triggered_at=observed_at,
        consecutive_hits=999,
        track_id="manual-test-track",
    )


def _overlay_snapshot(frame, event_no: str, person_name: str | None, image_name: str) -> object:
    annotated = frame.copy()
    lines = [
        f"Event: {event_no}",
        "Source: manual_test_trigger",
        f"Identity: {person_name or 'Unknown'}",
        f"Image: {image_name}",
    ]
    for index, line in enumerate(lines):
        cv2.putText(
            annotated,
            line,
            (18, 30 + index * 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 215, 255),
            2,
        )
    return annotated


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    repository = build_repository(settings, require_requested_backend=True)
    evidence_store = EvidenceStore(settings)
    identity_resolver = build_identity_resolver(settings)
    directory = PersonDirectory(settings)

    camera = _select_camera(settings, args.camera_id)
    image_path = _find_image(settings, args.person_id, args.image)
    frame = read_image(image_path)
    if frame is None:
        raise RuntimeError(f"Unable to read image: {image_path}")

    observed_at = datetime.now(tz=UTC)
    candidate = _build_candidate(frame, camera, observed_at)
    resolved = identity_resolver.resolve(camera, candidate, frame)
    expected_person = directory.get_person_by_id(args.person_id)
    if expected_person and resolved.person_id is None:
        resolved.person_id = expected_person.get("person_id")
        resolved.person_name = expected_person.get("name", resolved.person_name)
        resolved.employee_id = expected_person.get("employee_id")
        resolved.department = expected_person.get("department", resolved.department)
        resolved.team = expected_person.get("team")
        resolved.role = expected_person.get("role")
        resolved.phone = expected_person.get("phone")
        resolved.identity_status = "resolved"
        resolved.identity_source = "test_dataset_override"
        resolved.review_note = (
            f"Triggered from registered sample image {image_path.name}; identity backfilled from {args.person_id}."
        )

    alert_id = uuid.uuid4().hex
    event_no = f"TST-{observed_at.strftime('%Y%m%d-%H%M%S')}-{alert_id[:6].upper()}"
    snapshot_path, snapshot_url = evidence_store.save(
        camera.camera_id,
        _overlay_snapshot(frame, event_no, resolved.person_name, image_path.name),
        alert_id,
        observed_at,
    )

    face_crop_path = face_crop_url = None
    badge_crop_path = badge_crop_url = None
    if resolved.face_crop is not None:
        face_crop_path, face_crop_url = evidence_store.save(
            camera.camera_id,
            resolved.face_crop,
            f"{alert_id}_face",
            observed_at,
            category="faces",
        )
    if resolved.badge_crop is not None:
        badge_crop_path, badge_crop_url = evidence_store.save(
            camera.camera_id,
            resolved.badge_crop,
            f"{alert_id}_badge",
            observed_at,
            category="badges",
        )

    repository.upsert_camera(
        CameraHeartbeat(
            camera_id=camera.camera_id,
            camera_name=camera.camera_name,
            source=camera.source,
            location=camera.location,
            department=camera.department,
            last_status="online",
            last_seen_at=observed_at,
            site_name=camera.site_name,
            building_name=camera.building_name,
            floor_name=camera.floor_name,
            workshop_name=camera.workshop_name,
            zone_name=camera.zone_name,
            responsible_department=camera.responsible_department or camera.department,
            retry_count=0,
            reconnect_count=0,
            last_error=None,
            last_frame_at=observed_at,
            last_fps=0.0,
        ).to_record()
    )

    review_note = resolved.review_note or f"Triggered from local sample image: {image_path.name}"
    alert = AlertRecord(
        alert_id=alert_id,
        event_key=candidate.event_key,
        event_no=event_no,
        camera_id=camera.camera_id,
        camera_name=camera.camera_name,
        location=camera.location,
        department=camera.department,
        violation_type="no_helmet",
        risk_level="high",
        confidence=candidate.confidence,
        snapshot_path=snapshot_path,
        snapshot_url=snapshot_url,
        status="pending",
        bbox=candidate.bbox,
        model_name=Path(settings.model.path).name,
        person_id=resolved.person_id,
        person_name=resolved.person_name,
        employee_id=resolved.employee_id,
        team=resolved.team,
        role=resolved.role,
        phone=resolved.phone,
        identity_status=resolved.identity_status,
        identity_source=resolved.identity_source,
        identity_confidence=resolved.identity_confidence,
        badge_text=resolved.badge_text,
        badge_confidence=resolved.badge_confidence,
        face_match_score=resolved.face_match_score,
        face_crop_path=face_crop_path,
        face_crop_url=face_crop_url,
        badge_crop_path=badge_crop_path,
        badge_crop_url=badge_crop_url,
        review_note=review_note,
        llm_provider=resolved.llm_provider,
        llm_summary=resolved.llm_summary,
        clip_path=None,
        clip_url=None,
        alert_source="manual_test_trigger",
        governance_note="Synthetic no-helmet alert generated for UI validation.",
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
            "actor": "manual_test_trigger",
            "actor_role": "system",
            "payload": {
                "event_no": event_no,
                "person_id": resolved.person_id,
                "identity_status": resolved.identity_status,
                "source_image": image_path.name,
            },
            "created_at": observed_at.isoformat(),
        }
    )

    print(f"backend={repository.backend_name}")
    print(f"event_no={event_no}")
    print(f"camera_id={camera.camera_id}")
    print(f"source_image={image_path.name}")
    print(f"person_name={resolved.person_name}")
    print(f"identity_status={resolved.identity_status}")
    print(f"snapshot_path={snapshot_path}")
    print(f"snapshot_url={snapshot_url}")


if __name__ == "__main__":
    main()
