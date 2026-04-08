from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.face_recognition import FaceRecognitionService
from helmet_monitoring.services.person_directory import FaceProfileRecord, PersonDirectory
from helmet_monitoring.utils.image_io import read_image


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


@dataclass(slots=True)
class ValidationResult:
    person_id: str
    name: str
    image_name: str
    predicted_person_id: str | None
    predicted_name: str | None
    similarity: float | None
    matched_source: str | None
    outcome: str
    is_correct: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate registered face profiles with local face images.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument(
        "--person-ids",
        default="person-001,person-002",
        help="Comma-separated person IDs to validate. Default: person-001,person-002",
    )
    return parser.parse_args()


def iter_face_images(face_root: Path, person_ids: list[str]) -> list[tuple[str, Path]]:
    items: list[tuple[str, Path]] = []
    for person_id in person_ids:
        person_dir = face_root / person_id
        if not person_dir.exists():
            continue
        for image_path in sorted(person_dir.iterdir()):
            if image_path.is_file() and image_path.suffix.lower() in IMAGE_SUFFIXES:
                items.append((person_id, image_path))
    return items


def evaluate_image(
    service: FaceRecognitionService,
    profiles: list[FaceProfileRecord],
    person: dict | None,
    image_path: Path,
) -> ValidationResult:
    expected_person_id = person.get("person_id") if person else image_path.parent.name
    expected_name = person.get("name", expected_person_id) if person else expected_person_id

    image = read_image(image_path)
    if image is None:
        return ValidationResult(
            person_id=expected_person_id,
            name=expected_name,
            image_name=image_path.name,
            predicted_person_id=None,
            predicted_name=None,
            similarity=None,
            matched_source=None,
            outcome="image_read_failed",
            is_correct=False,
        )

    embedding, _ = service._encode_crop(image)
    if embedding is None:
        return ValidationResult(
            person_id=expected_person_id,
            name=expected_name,
            image_name=image_path.name,
            predicted_person_id=None,
            predicted_name=None,
            similarity=None,
            matched_source=None,
            outcome="face_not_detected",
            is_correct=False,
        )

    candidate_profiles = [
        profile
        for profile in profiles
        if not (profile.person.get("person_id") == expected_person_id and profile.source_name == image_path.name)
    ]
    if not candidate_profiles:
        candidate_profiles = profiles

    best_profile: FaceProfileRecord | None = None
    best_similarity: float | None = None
    for profile in candidate_profiles:
        similarity = float(np.dot(embedding, profile.embedding))
        if best_similarity is None or similarity > best_similarity:
            best_similarity = similarity
            best_profile = profile

    if best_profile is None or best_similarity is None:
        return ValidationResult(
            person_id=expected_person_id,
            name=expected_name,
            image_name=image_path.name,
            predicted_person_id=None,
            predicted_name=None,
            similarity=None,
            matched_source=None,
            outcome="no_profiles_available",
            is_correct=False,
        )

    threshold = service.settings.face_recognition.similarity_threshold
    review_threshold = service.settings.face_recognition.review_threshold
    if best_similarity >= threshold:
        outcome = "auto_accept"
    elif best_similarity >= review_threshold:
        outcome = "review_required"
    else:
        outcome = "unmatched"

    predicted_person_id = best_profile.person.get("person_id")
    predicted_name = best_profile.person.get("name")
    return ValidationResult(
        person_id=expected_person_id,
        name=expected_name,
        image_name=image_path.name,
        predicted_person_id=predicted_person_id,
        predicted_name=predicted_name,
        similarity=round(best_similarity, 4),
        matched_source=best_profile.source_name,
        outcome=outcome,
        is_correct=predicted_person_id == expected_person_id,
    )


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    directory = PersonDirectory(settings)
    service = FaceRecognitionService(settings)
    if service.provider == "none":
        raise RuntimeError("Face recognition provider is unavailable in the current environment.")

    person_ids = [item.strip() for item in args.person_ids.split(",") if item.strip()]
    face_root = settings.resolve_path(settings.face_recognition.face_profile_dir)
    items = iter_face_images(face_root, person_ids)
    if not items:
        raise RuntimeError(f"No validation face images found for: {', '.join(person_ids)}")

    profiles = [
        profile for profile in directory.get_face_profiles() if profile.person.get("person_id") in set(person_ids)
    ]
    if not profiles:
        raise RuntimeError("No registered face profiles found in Supabase for the selected person IDs.")

    results: list[ValidationResult] = []
    for person_id, image_path in items:
        person = directory.get_person_by_id(person_id)
        results.append(evaluate_image(service, profiles, person, image_path))

    total = len(results)
    correct = sum(1 for item in results if item.is_correct)
    auto_accept = sum(1 for item in results if item.outcome == "auto_accept")
    review_required = sum(1 for item in results if item.outcome == "review_required")
    unmatched = sum(1 for item in results if item.outcome == "unmatched")
    failed = sum(1 for item in results if item.outcome in {"image_read_failed", "face_not_detected", "no_profiles_available"})

    print(f"validated_images={total}")
    print(f"correct_matches={correct}")
    print(f"accuracy={correct / total:.4f}" if total else "accuracy=0.0000")
    print(f"auto_accept={auto_accept}")
    print(f"review_required={review_required}")
    print(f"unmatched={unmatched}")
    print(f"failed={failed}")
    print("details:")
    for item in results:
        predicted = item.predicted_name or item.predicted_person_id or "None"
        similarity = f"{item.similarity:.4f}" if item.similarity is not None else "None"
        print(
            f"- expected={item.name}({item.person_id}) "
            f"image={item.image_name} "
            f"predicted={predicted} "
            f"similarity={similarity} "
            f"outcome={item.outcome} "
            f"matched_source={item.matched_source or 'None'}"
        )


if __name__ == "__main__":
    main()
