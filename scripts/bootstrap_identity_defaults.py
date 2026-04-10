from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.person_directory import PersonDirectory


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect identity sample coverage and optionally write suggested camera default_person_id values."
    )
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--apply", action="store_true", help="Write suggested default_person_id values back to runtime.json.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing default_person_id values when a stronger registry camera-binding suggestion exists.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        handle.write(rendered)
    temp_path.replace(path)


def _count_face_samples(face_root: Path, person_id: str) -> int:
    target_dir = face_root / person_id
    if not target_dir.exists():
        return 0
    return sum(1 for item in target_dir.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES)


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    directory = PersonDirectory(settings)
    people = directory.get_people()
    face_root = settings.resolve_path(settings.face_recognition.face_profile_dir)
    config_payload = _load_json(settings.config_path)
    cameras = list(config_payload.get("cameras", []))

    people_with_aliases = sum(1 for item in people if item.get("aliases"))
    people_with_badge_keywords = sum(1 for item in people if item.get("badge_keywords"))
    people_with_camera_bindings = sum(
        1
        for item in people
        if any(
            item.get(field_name)
            for field_name in (
                "default_camera_ids",
                "default_camera_names",
                "default_locations",
                "default_site_names",
                "default_building_names",
                "default_floor_names",
                "default_workshop_names",
                "default_zone_names",
                "default_departments",
            )
        )
    )
    people_with_face_samples = sum(1 for item in people if _count_face_samples(face_root, str(item.get("person_id") or "")) > 0)

    print(f"identity_people={len(people)}")
    print(f"people_with_aliases={people_with_aliases}")
    print(f"people_with_badge_keywords={people_with_badge_keywords}")
    print(f"people_with_camera_bindings={people_with_camera_bindings}")
    print(f"people_with_face_samples={people_with_face_samples}")
    print(f"face_profile_dir={face_root}")

    updated = 0
    for camera_payload in cameras:
        camera = next((item for item in settings.cameras if item.camera_id == str(camera_payload.get("camera_id") or "")), None)
        if camera is None:
            continue
        suggestion = directory.suggest_default_person_for_camera(camera)
        current_default = str(camera_payload.get("default_person_id") or "").strip()
        suggested_person_id = str(suggestion.get("person_id") or "") if suggestion else ""
        suggested_name = str(suggestion.get("name") or "") if suggestion else ""
        suggested_score = str(suggestion.get("_default_match_score") or "") if suggestion else ""
        suggested_face_samples = _count_face_samples(face_root, suggested_person_id) if suggested_person_id else 0
        should_apply = bool(
            args.apply
            and suggested_person_id
            and (not current_default or args.overwrite)
            and current_default != suggested_person_id
        )
        if should_apply:
            camera_payload["default_person_id"] = suggested_person_id
            updated += 1
        print(
            "camera="
            f"{camera.camera_id}"
            f" current_default={current_default or '--'}"
            f" suggested_default={suggested_person_id or '--'}"
            f" suggested_name={suggested_name or '--'}"
            f" suggested_score={suggested_score or '--'}"
            f" suggested_face_samples={suggested_face_samples}"
            f" applied={'yes' if should_apply else 'no'}"
        )

    if updated:
        config_payload["cameras"] = cameras
        _write_json(settings.config_path, config_payload)
    print(f"updated_defaults={updated}")


if __name__ == "__main__":
    main()
