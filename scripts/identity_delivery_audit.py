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
from helmet_monitoring.services.person_directory import _tuple_from_person_values


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit delivery readiness of the identity registry, face samples, and camera bindings.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--json", action="store_true", help="Output JSON.")
    parser.add_argument("--strict", action="store_true", help="Fail when core identity coverage is still missing.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum people to print in the missing-items section.")
    return parser.parse_args()


def _count_face_samples(face_root: Path, person_id: str) -> int:
    target_dir = face_root / person_id
    if not target_dir.exists():
        return 0
    return sum(1 for item in target_dir.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES)


def _has_any(person: dict, *field_names: str) -> bool:
    return any(_tuple_from_person_values(person.get(field_name)) for field_name in field_names)


def build_report(settings) -> dict:
    registry_path = settings.resolve_path(settings.identity.registry_path)
    face_root = settings.resolve_path(settings.face_recognition.face_profile_dir)
    people = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else []
    active_people = [item for item in people if str(item.get("status", "active")).strip().lower() == "active"]

    rows: list[dict] = []
    aliases = 0
    badge_keywords = 0
    camera_bindings = 0
    face_people = 0
    for person in active_people:
        person_id = str(person.get("person_id") or "")
        face_samples = _count_face_samples(face_root, person_id) if person_id else 0
        has_aliases = bool(_tuple_from_person_values(person.get("aliases")))
        has_badge_keywords = bool(_tuple_from_person_values(person.get("badge_keywords")))
        has_camera_binding = _has_any(
            person,
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
        aliases += 1 if has_aliases else 0
        badge_keywords += 1 if has_badge_keywords else 0
        camera_bindings += 1 if has_camera_binding else 0
        face_people += 1 if face_samples > 0 else 0
        missing: list[str] = []
        if not has_aliases:
            missing.append("aliases")
        if not has_badge_keywords:
            missing.append("badge_keywords")
        if not has_camera_binding:
            missing.append("camera_binding")
        if face_samples <= 0:
            missing.append("face_samples")
        rows.append(
            {
                "person_id": person_id,
                "name": str(person.get("name") or "--"),
                "department": str(person.get("department") or "--"),
                "face_samples": face_samples,
                "missing": missing,
            }
        )

    incomplete = [item for item in rows if item["missing"]]
    return {
        "registry_path": str(registry_path),
        "face_profile_dir": str(face_root),
        "active_people": len(active_people),
        "people_with_aliases": aliases,
        "people_with_badge_keywords": badge_keywords,
        "people_with_camera_bindings": camera_bindings,
        "people_with_face_samples": face_people,
        "incomplete_people": incomplete,
    }


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    report = build_report(settings)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"registry_path={report['registry_path']}")
        print(f"face_profile_dir={report['face_profile_dir']}")
        print(f"active_people={report['active_people']}")
        print(f"people_with_aliases={report['people_with_aliases']}")
        print(f"people_with_badge_keywords={report['people_with_badge_keywords']}")
        print(f"people_with_camera_bindings={report['people_with_camera_bindings']}")
        print(f"people_with_face_samples={report['people_with_face_samples']}")
        print("incomplete_people:")
        for item in report["incomplete_people"][: max(0, args.limit)]:
            print(
                f"- {item['person_id']} {item['name']} department={item['department']} "
                f"face_samples={item['face_samples']} missing={','.join(item['missing'])}"
            )

    if args.strict:
        if report["active_people"] <= 0:
            raise SystemExit(1)
        if report["people_with_camera_bindings"] <= 0 or report["people_with_face_samples"] <= 0:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
