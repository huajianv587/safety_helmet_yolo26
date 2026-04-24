from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

import cv2
import numpy as np

from helmet_monitoring.core.config import AppSettings
from helmet_monitoring.utils.image_io import write_image

try:
    from supabase import create_client
except ImportError:  # pragma: no cover
    create_client = None


class EvidenceStore:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.snapshot_root = settings.resolve_path(settings.persistence.snapshot_dir)
        self.snapshot_root.mkdir(parents=True, exist_ok=True)
        self.bucket_ready = False
        self.client = None
        if (
            settings.persistence.upload_to_supabase_storage
            and settings.supabase.is_configured
            and create_client is not None
        ):
            self.client = create_client(settings.supabase.url, settings.supabase.service_role_key)

    def _local_path(
        self,
        camera_id: str,
        artifact_id: str,
        created_at: datetime,
        category: str,
        extension: str,
    ) -> Path:
        safe_category = category.strip("/").strip() or "alerts"
        safe_extension = extension if extension.startswith(".") else f".{extension}"
        day_dir = self.snapshot_root / safe_category / created_at.strftime("%Y%m%d") / camera_id
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / f"{created_at.strftime('%H%M%S')}_{artifact_id}{safe_extension}"

    def _ensure_bucket(self) -> bool:
        if self.client is None:
            return False
        if self.bucket_ready:
            return True
        bucket_name = self.settings.supabase.storage_bucket
        try:
            buckets = self.client.storage.list_buckets()
            exists = any(getattr(bucket, "id", None) == bucket_name for bucket in buckets)
            if not exists:
                self.client.storage.create_bucket(bucket_name, options={"public": not self.settings.security.use_private_bucket})
            self.bucket_ready = True
            return True
        except Exception as exc:  # pragma: no cover
            print(f"[evidence] Unable to prepare storage bucket {bucket_name}: {exc}")
            return False

    def _remote_object_path(
        self,
        camera_id: str,
        artifact_id: str,
        created_at: datetime,
        category: str,
        extension: str,
    ) -> str:
        prefix = self.settings.persistence.storage_prefix.strip("/").strip()
        safe_category = category.strip("/").strip() or "alerts"
        safe_extension = extension if extension.startswith(".") else f".{extension}"
        day_key = created_at.strftime("%Y%m%d")
        filename = f"{created_at.strftime('%H%M%S')}_{artifact_id}{safe_extension}"
        parts = [part for part in [prefix, safe_category, day_key, camera_id, filename] if part]
        return "/".join(parts)

    def remote_object_path(
        self,
        camera_id: str,
        artifact_id: str,
        created_at: datetime,
        *,
        category: str,
        extension: str,
    ) -> str:
        return self._remote_object_path(camera_id, artifact_id, created_at, category, extension)

    def _build_access_url(self, object_path: str) -> str | None:
        if self.client is None:
            return None
        bucket = self.settings.supabase.storage_bucket
        try:
            if self.settings.security.use_private_bucket:
                signed = self.client.storage.from_(bucket).create_signed_url(
                    object_path,
                    self.settings.security.signed_url_seconds,
                )
                if isinstance(signed, dict):
                    return signed.get("signedURL") or signed.get("signed_url")
                return getattr(signed, "signedURL", None) or getattr(signed, "signed_url", None)
            return self.client.storage.from_(bucket).get_public_url(object_path)
        except Exception as exc:  # pragma: no cover
            print(f"[evidence] Unable to build access URL for {object_path}: {exc}")
            return None

    def _upload_local_file(self, local_path: Path, object_path: str, content_type: str) -> str | None:
        if not self._ensure_bucket():
            return None
        try:
            self.client.storage.from_(self.settings.supabase.storage_bucket).upload(
                object_path,
                str(local_path),
                {"content-type": content_type, "upsert": "true"},
            )
            return self._build_access_url(object_path)
        except Exception as exc:  # pragma: no cover
            print(f"[evidence] Upload failed, keeping local artifact only: {exc}")
            return None

    def upload_artifact(self, local_path: str | Path, object_path: str, content_type: str) -> str | None:
        return self._upload_local_file(Path(local_path), object_path, content_type)

    def _cleanup_local_copy(self, local_path: Path, access_url: str | None) -> None:
        if not self.settings.persistence.keep_local_copy and access_url:
            try:
                local_path.unlink(missing_ok=True)
            except OSError:
                pass

    def save(
        self,
        camera_id: str,
        frame,
        artifact_id: str,
        created_at: datetime,
        *,
        category: str = "alerts",
    ) -> Tuple[str, str | None]:
        local_path = self._local_path(camera_id, artifact_id, created_at, category, ".jpg")
        if not write_image(local_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
            raise RuntimeError(f"Unable to write image artifact: {local_path}")
        return str(local_path), None

    def save_bytes(
        self,
        camera_id: str,
        file_bytes: bytes,
        artifact_id: str,
        created_at: datetime,
        *,
        category: str,
        extension: str,
        content_type: str,
    ) -> Tuple[str, str | None]:
        local_path = self._local_path(camera_id, artifact_id, created_at, category, extension)
        local_path.write_bytes(file_bytes)
        return str(local_path), None

    def save_existing_file(
        self,
        camera_id: str,
        local_path: str | Path,
        artifact_id: str,
        created_at: datetime,
        *,
        category: str,
        extension: str,
        content_type: str,
    ) -> Tuple[str, str | None]:
        source_path = Path(local_path)
        final_path = self._local_path(camera_id, artifact_id, created_at, category, extension)
        if source_path.resolve() != final_path.resolve():
            final_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.replace(final_path)
        return str(final_path), None

    def save_video_frames(
        self,
        camera_id: str,
        frames: Iterable[np.ndarray],
        artifact_id: str,
        created_at: datetime,
        *,
        category: str = "clips",
        fps: float = 12.0,
        codec: str = "mp4v",
    ) -> Tuple[str, str | None]:
        iterator = iter(frames)
        try:
            first_frame = next(iterator)
        except StopIteration:
            return "", None
        height, width = first_frame.shape[:2]
        local_path = self._local_path(camera_id, artifact_id, created_at, category, ".mp4")
        writer = cv2.VideoWriter(
            str(local_path),
            cv2.VideoWriter_fourcc(*codec[:4]),
            max(1.0, float(fps)),
            (width, height),
        )
        try:
            writer.write(first_frame)
            for frame in iterator:
                writer.write(frame)
        finally:
            writer.release()
        return str(local_path), None
