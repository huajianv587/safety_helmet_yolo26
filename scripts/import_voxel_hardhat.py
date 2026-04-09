from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "artifacts" / "external_datasets" / "voxel_hardhat_meta"
SAMPLES_JSON = SOURCE_ROOT / "samples.json"
OUTPUT_ROOT = REPO_ROOT / "data" / "external_datasets" / "voxel_hardhat_yolo"
MERGED_ROOT = REPO_ROOT / "data" / "helmet_detection_dataset_merged_voxel"

LABEL_MAP = {
    "helmet": 0,
    "head": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert the Voxel51 hard-hat dataset into the repo's YOLO two-class format.")
    parser.add_argument("--source-root", default=str(SOURCE_ROOT), help="Root directory of the cloned Voxel51 dataset.")
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT), help="Output directory for converted YOLO images/labels.")
    parser.add_argument("--merged-root", default=str(MERGED_ROOT), help="Output directory for merged train/val file lists.")
    parser.add_argument("--base-root", default="data/helmet_detection_dataset", help="Existing base dataset root.")
    return parser.parse_args()


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def _stable_split(key: str) -> str:
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return "val" if int(digest[:8], 16) % 10 == 0 else "train"


def _to_yolo_line(class_id: int, bbox: list[float]) -> str:
    x, y, w, h = bbox
    center_x = x + (w / 2.0)
    center_y = y + (h / 2.0)
    return f"{class_id} {center_x:.8f} {center_y:.8f} {w:.8f} {h:.8f}"


def _iter_base_images(target: Path) -> list[Path]:
    if not target.exists():
        return []
    images: list[Path] = []
    for pattern in ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp"):
        images.extend(sorted(target.glob(pattern)))
    return images


def main() -> int:
    args = parse_args()
    source_root = _resolve(args.source_root)
    output_root = _resolve(args.output_root)
    merged_root = _resolve(args.merged_root)
    base_root = _resolve(args.base_root)
    samples_path = source_root / "samples.json"

    if not samples_path.exists():
        raise FileNotFoundError(f"Missing samples.json: {samples_path}")

    payload = json.loads(samples_path.read_text(encoding="utf-8"))
    samples = payload.get("samples", [])
    if not isinstance(samples, list):
        raise RuntimeError("Unexpected samples.json format: 'samples' is not a list.")

    converted_images: dict[str, list[Path]] = {"train": [], "val": []}
    converted_counts = {"samples": 0, "helmet_boxes": 0, "no_helmet_boxes": 0, "ignored_boxes": 0}

    for split in ("train", "val"):
        (output_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_root / "labels" / split).mkdir(parents=True, exist_ok=True)
    merged_root.mkdir(parents=True, exist_ok=True)

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        relative_path = str(sample.get("filepath", "")).strip()
        if not relative_path:
            continue
        image_source = source_root / relative_path
        if not image_source.exists():
            continue

        split = _stable_split(relative_path)
        stem = f"voxel_{Path(relative_path).stem}"
        image_target = output_root / "images" / split / f"{stem}{image_source.suffix.lower()}"
        label_target = output_root / "labels" / split / f"{stem}.txt"

        if not image_target.exists():
            shutil.copyfile(image_source, image_target)

        detections = (((sample.get("ground_truth") or {}).get("detections")) or [])
        lines: list[str] = []
        for detection in detections:
            label = str((detection or {}).get("label", "")).strip().lower()
            bbox = (detection or {}).get("bounding_box")
            if label not in LABEL_MAP or not isinstance(bbox, list) or len(bbox) != 4:
                converted_counts["ignored_boxes"] += 1
                continue
            class_id = LABEL_MAP[label]
            lines.append(_to_yolo_line(class_id, [float(item) for item in bbox]))
            if class_id == 0:
                converted_counts["helmet_boxes"] += 1
            else:
                converted_counts["no_helmet_boxes"] += 1

        label_target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        converted_images[split].append(image_target.resolve())
        converted_counts["samples"] += 1

    merged_images = {
        "train": [path.resolve() for path in _iter_base_images(base_root / "images" / "train")] + converted_images["train"],
        "val": [path.resolve() for path in _iter_base_images(base_root / "images" / "val")] + converted_images["val"],
    }

    train_list = merged_root / "train.txt"
    val_list = merged_root / "val.txt"
    train_list.write_text("\n".join(str(path) for path in merged_images["train"]) + "\n", encoding="utf-8")
    val_list.write_text("\n".join(str(path) for path in merged_images["val"]) + "\n", encoding="utf-8")

    summary = {
        "source_root": str(source_root),
        "output_root": str(output_root),
        "merged_root": str(merged_root),
        "base_train_images": len(_iter_base_images(base_root / "images" / "train")),
        "base_val_images": len(_iter_base_images(base_root / "images" / "val")),
        "external_train_images": len(converted_images["train"]),
        "external_val_images": len(converted_images["val"]),
        "merged_train_images": len(merged_images["train"]),
        "merged_val_images": len(merged_images["val"]),
        **converted_counts,
    }
    summary_path = merged_root / "import_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
