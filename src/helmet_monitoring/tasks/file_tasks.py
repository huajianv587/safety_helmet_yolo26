"""
Asynchronous File Upload Tasks

Handles file uploads, processing, and storage in background.
"""

import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional

from helmet_monitoring.tasks.task_queue import async_task


@async_task(max_retries=3, worker_pool="upload")
def upload_evidence_to_storage(
    local_path: str,
    object_path: str,
    content_type: str = "image/jpeg"
) -> dict[str, Any]:
    """
    Upload evidence file to remote storage asynchronously.

    Args:
        local_path: Local file path
        object_path: Remote object path
        content_type: MIME type

    Returns:
        Upload result with access URL
    """
    try:
        from helmet_monitoring.storage.evidence_store import EvidenceStore
        from helmet_monitoring.core.config import load_settings

        settings = load_settings()
        store = EvidenceStore(settings)

        # Upload to remote storage
        access_url = store._upload_local_file(local_path, object_path, content_type)

        return {
            "status": "success",
            "local_path": local_path,
            "object_path": object_path,
            "access_url": access_url,
            "uploaded_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"[FileTask] Upload failed: {e}")
        raise


@async_task(max_retries=2, worker_pool="upload")
def generate_thumbnail(
    image_path: str,
    thumbnail_path: str,
    max_size: tuple[int, int] = (300, 300)
) -> dict[str, Any]:
    """
    Generate thumbnail for an image.

    Args:
        image_path: Source image path
        thumbnail_path: Output thumbnail path
        max_size: Maximum dimensions (width, height)

    Returns:
        Thumbnail generation result
    """
    try:
        import cv2
        import numpy as np

        # Read image
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Failed to read image: {image_path}")

        # Calculate new dimensions
        h, w = img.shape[:2]
        max_w, max_h = max_size
        scale = min(max_w / w, max_h / h)

        if scale < 1:
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Save thumbnail
        os.makedirs(os.path.dirname(thumbnail_path), exist_ok=True)
        cv2.imwrite(thumbnail_path, img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

        return {
            "status": "success",
            "source": image_path,
            "thumbnail": thumbnail_path,
            "original_size": (w, h),
            "thumbnail_size": img.shape[:2][::-1],
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"[FileTask] Thumbnail generation failed: {e}")
        raise


@async_task(max_retries=2, worker_pool="upload")
def compress_video(
    video_path: str,
    output_path: str,
    target_bitrate: str = "500k"
) -> dict[str, Any]:
    """
    Compress video file.

    Args:
        video_path: Source video path
        output_path: Output compressed video path
        target_bitrate: Target bitrate (e.g., "500k")

    Returns:
        Compression result
    """
    try:
        import subprocess

        # Check if ffmpeg is available
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("ffmpeg not found. Please install ffmpeg.")

        # Compress video
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-b:v", target_bitrate,
            "-c:v", "libx264",
            "-preset", "fast",
            "-y",  # Overwrite output
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr}")

        # Get file sizes
        original_size = os.path.getsize(video_path)
        compressed_size = os.path.getsize(output_path)
        compression_ratio = (1 - compressed_size / original_size) * 100

        return {
            "status": "success",
            "source": video_path,
            "output": output_path,
            "original_size_mb": round(original_size / 1024 / 1024, 2),
            "compressed_size_mb": round(compressed_size / 1024 / 1024, 2),
            "compression_ratio": round(compression_ratio, 2),
            "compressed_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"[FileTask] Video compression failed: {e}")
        raise


@async_task(max_retries=1, worker_pool="persist")
def cleanup_old_files(
    directory: str,
    days_old: int = 30,
    pattern: str = "*"
) -> dict[str, Any]:
    """
    Clean up old files from a directory.

    Args:
        directory: Directory to clean
        days_old: Delete files older than this many days
        pattern: File pattern to match (e.g., "*.jpg")

    Returns:
        Cleanup result
    """
    try:
        from pathlib import Path
        import time

        dir_path = Path(directory)
        if not dir_path.exists():
            return {
                "status": "skipped",
                "reason": "Directory does not exist",
                "directory": directory
            }

        cutoff_time = time.time() - (days_old * 24 * 60 * 60)
        deleted_count = 0
        deleted_size = 0

        for file_path in dir_path.glob(pattern):
            if file_path.is_file():
                if file_path.stat().st_mtime < cutoff_time:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_count += 1
                    deleted_size += file_size

        return {
            "status": "success",
            "directory": directory,
            "deleted_count": deleted_count,
            "deleted_size_mb": round(deleted_size / 1024 / 1024, 2),
            "cleaned_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"[FileTask] Cleanup failed: {e}")
        raise


@async_task(max_retries=3, worker_pool="upload")
def batch_process_images(
    image_paths: list[str],
    operation: str = "thumbnail",
    **kwargs
) -> dict[str, Any]:
    """
    Batch process multiple images.

    Args:
        image_paths: List of image paths
        operation: Operation to perform ("thumbnail", "compress", etc.)
        **kwargs: Operation-specific parameters

    Returns:
        Batch processing result
    """
    results = []
    errors = []

    for image_path in image_paths:
        try:
            if operation == "thumbnail":
                thumbnail_path = kwargs.get("thumbnail_path", image_path.replace(".jpg", "_thumb.jpg"))
                result = generate_thumbnail(image_path, thumbnail_path, kwargs.get("max_size", (300, 300)))
                results.append(result)
            else:
                errors.append({"path": image_path, "error": f"Unknown operation: {operation}"})
        except Exception as e:
            errors.append({"path": image_path, "error": str(e)})

    return {
        "status": "completed",
        "total": len(image_paths),
        "successful": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
        "processed_at": datetime.now(timezone.utc).isoformat()
    }
