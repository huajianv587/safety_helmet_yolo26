from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich person_registry.json with aliases, badge keywords, and safe default camera bindings."
    )
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--write", action="store_true", help="Persist the enriched registry back to disk.")
    return parser.parse_args()


def _compact_token(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in str(value).strip().upper() if ch.isalnum())


def _unique_tokens(values) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in values:
        token = str(raw).strip()
        if not token:
            continue
        key = _compact_token(token)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(token)
    return ordered


def _iter_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _drop_short_tokens(values: list[str], minimum_compact_length: int = 2) -> list[str]:
    return [item for item in values if len(_compact_token(item)) >= minimum_compact_length]


def _name_aliases(name: str | None) -> list[str]:
    raw_name = str(name or "").strip()
    if not raw_name:
        return []
    compact = _compact_token(raw_name)
    parts = [part for part in raw_name.replace("-", " ").split() if part]
    if len(parts) <= 1:
        return _unique_tokens([compact])
    initials = "".join(part[0].upper() for part in parts if part)
    aliases = [raw_name]
    if initials and len(initials) > 1 and initials != compact:
        aliases.append(initials)
    return _unique_tokens(aliases)


def _badge_keywords(person: dict) -> list[str]:
    employee_id = str(person.get("employee_id") or "").strip().upper()
    name = str(person.get("name") or "").strip()
    compact_name = _compact_token(name)
    digits_only = "".join(ch for ch in employee_id if ch.isdigit())
    parts = [part for part in name.replace("-", " ").split() if part]
    initials = "".join(part[0].upper() for part in parts if part)
    values = [employee_id, digits_only, compact_name]
    if len(initials) > 1 and initials != compact_name:
        values.append(initials)
    return _unique_tokens(values)


def _count_face_samples(face_root: Path, person_id: str) -> int:
    target = face_root / person_id
    if not target.exists():
        return 0
    return sum(1 for item in target.rglob("*") if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES)


def enrich_registry_payload(payload: list[dict], cameras: list[dict], face_root: Path) -> tuple[list[dict], dict[str, int]]:
    face_samples_by_person = {
        str(person.get("person_id") or ""): _count_face_samples(face_root, str(person.get("person_id") or ""))
        for person in payload
    }
    face_sample_people = [
        person
        for person in payload
        if face_samples_by_person.get(str(person.get("person_id") or ""), 0) > 0 and str(person.get("status", "active")) == "active"
    ]
    unique_face_sample_people_by_department: dict[str, list[dict]] = defaultdict(list)
    for person in face_sample_people:
        department_key = _compact_token(person.get("department"))
        if department_key:
            unique_face_sample_people_by_department[department_key].append(person)

    camera_ids_by_department: dict[str, list[str]] = defaultdict(list)
    for camera in cameras:
        if not bool(camera.get("enabled", True)):
            continue
        department_key = _compact_token(camera.get("responsible_department") or camera.get("department"))
        if department_key:
            camera_ids_by_department[department_key].append(str(camera.get("camera_id") or ""))

    enriched: list[dict] = []
    summary = {
        "aliases_added": 0,
        "badge_keywords_added": 0,
        "camera_bindings_added": 0,
        "people_updated": 0,
    }

    for person in payload:
        record = dict(person)
        changed = False

        existing_aliases = _unique_tokens(_iter_values(record.get("aliases")))
        aliases = _drop_short_tokens(_unique_tokens([*existing_aliases, *_name_aliases(record.get("name"))]))
        if aliases != existing_aliases:
            record["aliases"] = aliases
            changed = True
        if aliases:
            summary["aliases_added"] += 1

        existing_badge_keywords = _unique_tokens(_iter_values(record.get("badge_keywords")))
        badge_keywords = _drop_short_tokens(_unique_tokens([*existing_badge_keywords, *_badge_keywords(record)]))
        if badge_keywords != existing_badge_keywords:
            record["badge_keywords"] = badge_keywords
            changed = True
        if badge_keywords:
            summary["badge_keywords_added"] += 1

        department_key = _compact_token(record.get("department"))
        face_samples = face_samples_by_person.get(str(record.get("person_id") or ""), 0)
        existing_defaults = _unique_tokens(_iter_values(record.get("default_camera_ids")))
        inferred_defaults = list(existing_defaults)
        if department_key:
            candidates = unique_face_sample_people_by_department.get(department_key, [])
            if len(candidates) == 1 and candidates[0].get("person_id") == record.get("person_id") and face_samples > 0:
                inferred_defaults = _unique_tokens([*existing_defaults, *camera_ids_by_department.get(department_key, [])])
        if inferred_defaults != existing_defaults:
            record["default_camera_ids"] = inferred_defaults
            changed = True
        if inferred_defaults:
            summary["camera_bindings_added"] += 1

        if changed:
            summary["people_updated"] += 1
        enriched.append(record)
    return enriched, summary


def _write_json(path: Path, payload: list[dict]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(rendered, encoding="utf-8")
    temp_path.replace(path)


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    registry_path = settings.resolve_path(settings.identity.registry_path)
    if not registry_path.exists():
        raise FileNotFoundError(f"Person registry not found: {registry_path}")
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("person_registry.json must be a JSON array of person records.")
    config_payload = json.loads(settings.config_path.read_text(encoding="utf-8"))
    cameras = list(config_payload.get("cameras", []))
    face_root = settings.resolve_path(settings.face_recognition.face_profile_dir)

    enriched, summary = enrich_registry_payload(payload, cameras, face_root)
    if args.write:
        _write_json(registry_path, enriched)

    print(f"registry_path={registry_path}")
    print(f"face_profile_dir={face_root}")
    print(f"people={len(enriched)}")
    print(f"people_updated={summary['people_updated']}")
    print(f"people_with_aliases={summary['aliases_added']}")
    print(f"people_with_badge_keywords={summary['badge_keywords_added']}")
    print(f"people_with_camera_bindings={summary['camera_bindings_added']}")
    print(f"write_applied={'true' if args.write else 'false'}")


if __name__ == "__main__":
    main()
