from __future__ import annotations

import argparse
import sys
from pathlib import Path

from supabase import create_client


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.face_recognition import FaceRecognitionService
from helmet_monitoring.utils.image_io import read_image


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Encode local face samples and sync them into Supabase person_face_profiles.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    return parser.parse_args()


def iter_face_images(face_root: Path):
    if not face_root.exists():
        return
    for person_dir in sorted(face_root.iterdir()):
        if not person_dir.is_dir():
            continue
        for image_path in sorted(person_dir.iterdir()):
            if image_path.suffix.lower() in IMAGE_SUFFIXES:
                yield person_dir.name, image_path


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    if not settings.supabase.is_configured:
        raise RuntimeError("Supabase credentials are not configured in .env")

    service = FaceRecognitionService(settings)
    if service.provider == "none":
        raise RuntimeError(
            "Face recognition provider is unavailable. Install facenet-pytorch and torch, "
            "then rerun this script."
        )

    face_root = settings.resolve_path(settings.face_recognition.face_profile_dir)
    client = create_client(settings.supabase.url, settings.supabase.service_role_key)
    people_response = client.table("persons").select("person_id").eq("status", "active").execute()
    active_person_ids = {item["person_id"] for item in (people_response.data or []) if item.get("person_id")}

    rows: list[dict] = []
    processed_person_ids: set[str] = set()
    skipped_files = 0
    encoded_files = 0

    for person_id, image_path in iter_face_images(face_root):
        if person_id not in active_person_ids:
            skipped_files += 1
            continue
        image = read_image(image_path)
        if image is None:
            skipped_files += 1
            continue
        embedding, _ = service._encode_crop(image)
        if embedding is None:
            skipped_files += 1
            continue
        rows.append(
            {
                "person_id": person_id,
                "source_name": image_path.name,
                "source_photo_url": str(image_path),
                "embedding_json": embedding.tolist(),
                "embedding_version": "facenet_pytorch_vggface2",
            }
        )
        processed_person_ids.add(person_id)
        encoded_files += 1

    for person_id in processed_person_ids:
        client.table("person_face_profiles").delete().eq("person_id", person_id).execute()

    if rows:
        client.table("person_face_profiles").insert(rows).execute()

    print(f"face_profile_dir={face_root}")
    print(f"encoded_files={encoded_files}")
    print(f"skipped_files={skipped_files}")
    print(f"synced_profiles={len(rows)}")


if __name__ == "__main__":
    main()
