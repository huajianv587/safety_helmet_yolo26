from __future__ import annotations

import argparse
import os
import sys
import urllib.request
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.core.schemas import utc_now
from helmet_monitoring.storage.evidence_store import EvidenceStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate storage upload, signed/public URL access, and remote cleanup.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--camera-id", default=None, help="Optional camera id to stamp into the storage path.")
    parser.add_argument("--keep-remote", action="store_true", help="Keep the uploaded remote object instead of deleting it.")
    parser.add_argument("--require-success", action="store_true", help="Fail unless upload, URL access, and cleanup all succeed.")
    return parser.parse_args()


def _select_camera_id(settings, camera_id: str | None) -> str:
    if camera_id:
        return camera_id
    for camera in settings.cameras:
        if camera.enabled:
            return camera.camera_id
    return "storage-validation"


def _sample_bytes() -> bytes:
    dataset_dir = REPO_ROOT / "data" / "helmet_detection_dataset" / "images" / "val"
    for image_path in sorted(dataset_dir.glob("*.jpg")):
        return image_path.read_bytes()
    raise FileNotFoundError(f"No sample image found under {dataset_dir}")


def run_validation(settings, *, camera_id: str | None = None, keep_remote: bool = False, require_success: bool = False) -> dict[str, object]:
    if not settings.persistence.upload_to_supabase_storage:
        raise RuntimeError("Storage upload is disabled in runtime settings.")
    store = EvidenceStore(settings)
    if store.client is None:
        raise RuntimeError("Supabase storage client is unavailable. Check credentials and dependencies.")

    resolved_camera_id = _select_camera_id(settings, camera_id)
    artifact_id = f"storage-validation-{uuid.uuid4().hex[:8]}"
    created_at = utc_now()
    object_path = store._remote_object_path(resolved_camera_id, artifact_id, created_at, "storage_validation", ".jpg")
    local_path: Path | None = None
    access_url: str | None = None
    downloaded_bytes = 0
    remote_deleted = False
    local_deleted = False

    try:
        saved_local_path, access_url = store.save_bytes(
            resolved_camera_id,
            _sample_bytes(),
            artifact_id,
            created_at,
            category="storage_validation",
            extension=".jpg",
            content_type="image/jpeg",
        )
        local_path = Path(saved_local_path)
        if access_url:
            with urllib.request.urlopen(access_url, timeout=20) as response:
                downloaded_bytes = len(response.read())
        if not keep_remote:
            store.client.storage.from_(settings.supabase.storage_bucket).remove([object_path])
            remote_deleted = True
        if local_path.exists():
            local_path.unlink(missing_ok=True)
            local_deleted = True
    finally:
        if local_path and local_path.exists():
            local_path.unlink(missing_ok=True)
            local_deleted = True

    result = {
        "camera_id": resolved_camera_id,
        "bucket": settings.supabase.storage_bucket,
        "object_path": object_path,
        "access_url_present": bool(access_url),
        "downloaded_bytes": downloaded_bytes,
        "remote_deleted": remote_deleted,
        "local_deleted": local_deleted,
        "keep_remote": keep_remote,
    }
    if require_success and (not access_url or downloaded_bytes <= 0 or (not keep_remote and not remote_deleted)):
        raise RuntimeError(f"Storage validation did not complete successfully: {result}")
    return result


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    result = run_validation(
        settings,
        camera_id=args.camera_id,
        keep_remote=args.keep_remote,
        require_success=args.require_success,
    )
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
