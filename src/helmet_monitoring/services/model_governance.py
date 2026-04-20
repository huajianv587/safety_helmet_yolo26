from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from helmet_monitoring.core.config import AppSettings, REPO_ROOT
from helmet_monitoring.core.schemas import utc_now
from helmet_monitoring.services.operations import (
    _atomic_write_json,
    _read_json,
    _record_audit,
    create_release_snapshot,
    ensure_operations_state,
    operations_paths,
    sha256_file,
)
from helmet_monitoring.storage.repository import AlertRepository, parse_timestamp


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
SCENE_TAGS = ("night", "backlight", "crowd", "occlusion", "false_positive", "missed_detection")
ALLOWED_DETECTOR_LABELS = ("helmet", "no_helmet")


def feedback_paths(settings: AppSettings, repo_root: Path | None = None) -> dict[str, Path]:
    base = (repo_root or REPO_ROOT).resolve()
    runtime_dir = Path(settings.persistence.runtime_dir)
    if not runtime_dir.is_absolute():
        runtime_dir = (base / runtime_dir).resolve()
    return {
        "repo_root": base,
        "hard_cases_root": base / "data" / "hard_cases",
        "false_positive_dir": base / "data" / "hard_cases" / "false_positive",
        "missed_detection_dir": base / "data" / "hard_cases" / "missed_detection",
        "night_shift_dir": base / "data" / "hard_cases" / "night_shift",
        "backlight_dir": base / "data" / "hard_cases" / "backlight",
        "crowd_dir": base / "data" / "hard_cases" / "crowd",
        "occlusion_dir": base / "data" / "hard_cases" / "occlusion",
        "labeled_images_train": base / "data" / "hard_cases" / "labeled" / "images" / "train",
        "labeled_images_val": base / "data" / "hard_cases" / "labeled" / "images" / "val",
        "labeled_labels_train": base / "data" / "hard_cases" / "labeled" / "labels" / "train",
        "labeled_labels_val": base / "data" / "hard_cases" / "labeled" / "labels" / "val",
        "feedback_exports_dir": base / "artifacts" / "exports" / "model_feedback",
        "quality_reports_dir": base / "artifacts" / "reports" / "quality",
        "runtime_dir": runtime_dir,
    }


def ensure_feedback_workspace(settings: AppSettings, repo_root: Path | None = None) -> dict[str, Path]:
    paths = feedback_paths(settings, repo_root=repo_root)
    for key in (
        "false_positive_dir",
        "missed_detection_dir",
        "night_shift_dir",
        "backlight_dir",
        "crowd_dir",
        "occlusion_dir",
        "labeled_images_train",
        "labeled_images_val",
        "labeled_labels_train",
        "labeled_labels_val",
        "feedback_exports_dir",
        "quality_reports_dir",
    ):
        paths[key].mkdir(parents=True, exist_ok=True)
    ensure_operations_state(settings, repo_root=repo_root)
    return paths


def _copy_optional(source: str | None, destination_dir: Path, name: str) -> str | None:
    if not source:
        return None
    source_path = Path(source)
    if not source_path.exists() or not source_path.is_file():
        return None
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / f"{name}{source_path.suffix.lower()}"
    shutil.copyfile(source_path, target)
    return str(target)


def _repo_rel_label(path_value: str | Path | None, repo_root: Path) -> str | None:
    if not path_value:
        return None
    target = Path(path_value)
    if not target.is_absolute():
        target = (repo_root / target).resolve()
    else:
        target = target.resolve()
    try:
        return str(target.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return str(target)


def _resolve_repo_path(path_value: str | Path | None, repo_root: Path) -> Path | None:
    if not path_value:
        return None
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (repo_root / candidate).resolve()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = parse_timestamp(value)
    if parsed == datetime.min.replace(tzinfo=timezone.utc):
        return None
    return parsed


def _parse_date_key(value: str | None) -> str | None:
    parsed = _parse_datetime(value)
    return parsed.date().isoformat() if parsed else None


def _normalize_scene_tag(tag: str) -> str | None:
    lowered = str(tag or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "night_shift": "night",
        "false_positive": "false_positive",
        "falsepositive": "false_positive",
        "missed_detection": "missed_detection",
        "misseddetection": "missed_detection",
        "back_light": "backlight",
    }
    normalized = mapping.get(lowered, lowered)
    return normalized if normalized in SCENE_TAGS else None


def _scene_tags_from_values(*values: Any) -> list[str]:
    tags: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value).lower()
        if "night" in text or "evening" in text or "夜" in text:
            tags.add("night")
        if "backlight" in text or "back light" in text or "逆光" in text:
            tags.add("backlight")
        if "crowd" in text or "dense" in text or "拥挤" in text:
            tags.add("crowd")
        if "occlusion" in text or "遮挡" in text or "blocked" in text:
            tags.add("occlusion")
        if "false positive" in text or "false_positive" in text or "误报" in text:
            tags.add("false_positive")
        if "missed detection" in text or "missed_detection" in text or "漏检" in text:
            tags.add("missed_detection")
    return sorted(tags)


def _label_bucket_from_alert(alert: dict[str, Any]) -> str:
    joined = " ".join(
        str(alert.get(key) or "")
        for key in ("label", "violation_type", "status", "event_no", "identity_status", "governance_note")
    ).lower()
    if "no_helmet" in joined or "without helmet" in joined or "violation" in joined:
        return "no_helmet"
    return "helmet"


def _label_bucket_from_case(case_type: str | None, alert: dict[str, Any]) -> str:
    lowered = str(case_type or "").strip().lower()
    if lowered == "false_positive":
        return "helmet"
    if lowered == "missed_detection":
        return "no_helmet"
    return _label_bucket_from_alert(alert)


def _iter_images(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return [item for item in sorted(path.rglob("*")) if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS]


def _label_path_for_image(image_path: Path) -> Path:
    return image_path.with_suffix(".txt")


def _feedback_label_exists(image_path: Path, images_root: Path, labels_root: Path) -> bool:
    try:
        relative_path = image_path.relative_to(images_root).with_suffix(".txt")
    except ValueError:
        return _label_path_for_image(image_path).exists()
    return (labels_root / relative_path).exists()


def _parse_dataset_yaml(dataset_path: Path, repo_root: Path) -> dict[str, Any]:
    path_value = ""
    train_value = ""
    val_value = ""
    names: dict[int, str] = {}
    in_names = False
    for raw_line in dataset_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line.startswith(" ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            in_names = key == "names"
            if key == "path":
                path_value = value
            elif key == "train":
                train_value = value
            elif key == "val":
                val_value = value
            continue
        if in_names and ":" in stripped:
            idx, label = stripped.split(":", 1)
            names[int(idx.strip())] = label.strip()
    dataset_root = Path(path_value)
    if not dataset_root.is_absolute():
        repo_candidate = (repo_root / dataset_root).resolve()
        local_candidate = (dataset_path.parent / dataset_root).resolve()
        dataset_root = repo_candidate if repo_candidate.exists() or not local_candidate.exists() else local_candidate
    return {"root": dataset_root, "train": train_value, "val": val_value, "names": names or {0: "helmet", 1: "no_helmet"}}


def _resolve_dataset_split(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (root / candidate).resolve()


def _resolve_label_path(image_path: Path, *, dataset_root: Path | None = None) -> Path | None:
    direct = image_path.with_suffix(".txt")
    if direct.exists():
        return direct
    if dataset_root:
        try:
            relative = image_path.resolve().relative_to(dataset_root.resolve())
        except ValueError:
            relative = None
        if relative and relative.parts and relative.parts[0] == "images":
            candidate = dataset_root / "labels" / Path(*relative.parts[1:]).with_suffix(".txt")
            if candidate.exists():
                return candidate
    parts = image_path.parts
    if "images" in parts and "labeled" in parts:
        index = parts.index("images")
        labels_candidate = Path(*parts[:index], "labels", *parts[index + 1 :]).with_suffix(".txt")
        if labels_candidate.exists():
            return labels_candidate
    return None


def _load_benchmark_manifest(benchmark_manifest_path: str | Path, repo_root: Path) -> dict[str, Any]:
    manifest_path = _resolve_repo_path(benchmark_manifest_path, repo_root)
    if manifest_path is None or not manifest_path.exists():
        raise FileNotFoundError(f"Benchmark manifest not found: {benchmark_manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def build_benchmark_dataset_bundle(
    settings: AppSettings,
    *,
    benchmark_manifest_path: str,
    output_dir: str | Path,
    train_splits: Iterable[str],
    val_splits: Iterable[str],
    base_dataset_yaml: str = "configs/datasets/shwd_yolo26.yaml",
    repo_root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_feedback_workspace(settings, repo_root=repo_root)
    root = paths["repo_root"]
    manifest = _load_benchmark_manifest(benchmark_manifest_path, root)
    dataset_yaml_path = Path(base_dataset_yaml)
    if not dataset_yaml_path.is_absolute():
        dataset_yaml_path = (root / dataset_yaml_path).resolve()
    dataset_info = _parse_dataset_yaml(dataset_yaml_path, root)
    output_root = Path(output_dir)
    if not output_root.is_absolute():
        output_root = (root / output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    normalized_train = tuple(sorted({str(item).strip() for item in train_splits if str(item).strip()}))
    normalized_val = tuple(sorted({str(item).strip() for item in val_splits if str(item).strip()}))
    if not normalized_val:
        raise ValueError("At least one validation split is required for benchmark dataset generation.")

    split_lists: dict[str, list[str]] = {"train": [], "val": []}
    seen_paths: dict[str, set[str]] = {"train": set(), "val": set()}
    skipped_unlabeled: list[dict[str, Any]] = []
    skipped_missing_images: list[dict[str, Any]] = []
    label_breakdown: Counter[str] = Counter()
    scene_breakdown: Counter[str] = Counter()

    for item in manifest.get("items", []):
        split = str(item.get("split") or "").strip()
        target_key = None
        if split in normalized_train:
            target_key = "train"
        elif split in normalized_val:
            target_key = "val"
        if not target_key:
            continue
        image_path = _resolve_repo_path(item.get("snapshot_path"), root)
        if image_path is None or not image_path.exists():
            skipped_missing_images.append({"id": item.get("id"), "split": split, "snapshot_path": item.get("snapshot_path")})
            continue
        label_path = _resolve_label_path(image_path, dataset_root=dataset_info["root"])
        if label_path is None or not label_path.exists():
            skipped_unlabeled.append({"id": item.get("id"), "split": split, "snapshot_path": item.get("snapshot_path")})
            continue
        resolved = str(image_path.resolve())
        if resolved in seen_paths[target_key]:
            continue
        seen_paths[target_key].add(resolved)
        split_lists[target_key].append(resolved)
        label_text = label_path.read_text(encoding="utf-8").splitlines()
        for raw_line in label_text:
            parts = raw_line.strip().split()
            if not parts:
                continue
            try:
                class_id = int(float(parts[0]))
            except ValueError:
                continue
            label_name = dataset_info["names"].get(class_id)
            if label_name in ALLOWED_DETECTOR_LABELS:
                label_breakdown[label_name] += 1
        for tag in item.get("scene_tags", []) or []:
            normalized_tag = _normalize_scene_tag(tag)
            if normalized_tag:
                scene_breakdown[normalized_tag] += 1

    train_list_path = output_root / "train.txt"
    val_list_path = output_root / "val.txt"
    dataset_output_path = output_root / "benchmark_dataset.yaml"
    summary_path = output_root / "benchmark_dataset_manifest.json"
    train_list_path.write_text("\n".join(split_lists["train"]) + ("\n" if split_lists["train"] else ""), encoding="utf-8")
    val_list_path.write_text("\n".join(split_lists["val"]) + ("\n" if split_lists["val"] else ""), encoding="utf-8")
    names_lines = "\n".join(f"  {index}: {label}" for index, label in sorted(dataset_info["names"].items()))
    dataset_output_path.write_text(
        "\n".join(
            [
                "path: .",
                f"train: {train_list_path}",
                f"val: {val_list_path}",
                "names:",
                names_lines or "  0: helmet\n  1: no_helmet",
                "",
            ]
        ),
        encoding="utf-8",
    )
    payload = {
        "benchmark_manifest_path": _repo_rel_label(benchmark_manifest_path, root),
        "dataset_yaml": str(dataset_output_path),
        "train_list_path": str(train_list_path),
        "val_list_path": str(val_list_path),
        "train_splits": list(normalized_train),
        "val_splits": list(normalized_val),
        "train_count": len(split_lists["train"]),
        "val_count": len(split_lists["val"]),
        "training_ready": bool(split_lists["train"] and split_lists["val"]),
        "label_breakdown": {label: label_breakdown.get(label, 0) for label in ALLOWED_DETECTOR_LABELS},
        "scene_breakdown": {tag: scene_breakdown.get(tag, 0) for tag in SCENE_TAGS},
        "skipped_unlabeled": skipped_unlabeled,
        "skipped_missing_images": skipped_missing_images,
        "allowed_labels": list(ALLOWED_DETECTOR_LABELS),
        "generated_at": utc_now().isoformat(),
    }
    _atomic_write_json(summary_path, payload)
    payload["manifest_path"] = str(summary_path)
    return payload


def _registry_path(settings: AppSettings, key: str, repo_root: Path | None = None) -> Path:
    return operations_paths(settings, repo_root=repo_root)[key]


def _latest_registry_entry(settings: AppSettings, registry_key: str, item_key: str, repo_root: Path | None = None) -> dict[str, Any] | None:
    registry_path = _registry_path(settings, registry_key, repo_root=repo_root)
    registry = _read_json(registry_path, {"exports": [], "datasets": []})
    items = registry.get(item_key, []) if isinstance(registry, dict) else []
    if not items:
        return None
    return items[-1]


def _collect_scene_breakdown_from_cases(cases: Iterable[dict[str, Any]]) -> dict[str, int]:
    counter = Counter({tag: 0 for tag in SCENE_TAGS})
    for case in cases:
        for tag in case.get("scene_tags", []) or []:
            normalized = _normalize_scene_tag(tag)
            if normalized:
                counter[normalized] += 1
    return {tag: counter.get(tag, 0) for tag in SCENE_TAGS}


def _collect_label_breakdown_from_images(
    image_paths: Iterable[Path],
    *,
    dataset_root: Path,
    default_bucket: str = "no_helmet",
) -> dict[str, int]:
    counter = Counter({label: 0 for label in ALLOWED_DETECTOR_LABELS})
    for image_path in image_paths:
        label_path = _resolve_label_path(image_path, dataset_root=dataset_root)
        if label_path is None or not label_path.exists():
            counter[default_bucket] += 1
            continue
        for raw_line in label_path.read_text(encoding="utf-8").splitlines():
            parts = raw_line.strip().split()
            if not parts:
                continue
            try:
                class_id = int(float(parts[0]))
            except ValueError:
                continue
            label_name = {0: "helmet", 1: "no_helmet"}.get(class_id)
            if label_name in ALLOWED_DETECTOR_LABELS:
                counter[label_name] += 1
    return {label: counter.get(label, 0) for label in ALLOWED_DETECTOR_LABELS}


def sink_feedback_case(
    alert: dict[str, Any],
    *,
    case_type: str,
    note: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    base = (repo_root or REPO_ROOT).resolve()
    case_dir = base / "data" / "hard_cases" / case_type / str(alert["alert_id"])
    case_dir.mkdir(parents=True, exist_ok=True)
    local_snapshot = _copy_optional(alert.get("snapshot_path"), case_dir, "snapshot")
    local_clip = _copy_optional(alert.get("clip_path"), case_dir, "clip")
    created_at = alert.get("created_at")
    manifest = {
        "alert_id": alert.get("alert_id"),
        "event_no": alert.get("event_no"),
        "case_type": case_type,
        "status": "queued",
        "note": note,
        "camera_id": alert.get("camera_id"),
        "camera_name": alert.get("camera_name"),
        "date": _parse_date_key(created_at),
        "scene_tags": sorted(set(_scene_tags_from_values(case_type, note, alert.get("review_note"), alert.get("governance_note")))),
        "label_bucket": _label_bucket_from_case(case_type, alert),
        "source_snapshot_path": alert.get("snapshot_path"),
        "source_clip_path": alert.get("clip_path"),
        "local_snapshot_path": local_snapshot,
        "local_clip_path": local_clip,
        "created_at": utc_now().isoformat(),
    }
    _atomic_write_json(case_dir / "case_manifest.json", manifest)
    return manifest


def export_feedback_cases(
    settings: AppSettings,
    repository: AlertRepository,
    *,
    limit: int = 200,
    case_types: tuple[str, ...] | None = None,
    actor: str = "system",
    note: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_feedback_workspace(settings, repo_root=repo_root)
    root = paths["repo_root"]
    export_id = f"feedback-export-{utc_now().strftime('%Y%m%d-%H%M%S')}"
    export_dir = paths["feedback_exports_dir"] / export_id
    export_dir.mkdir(parents=True, exist_ok=True)
    selected_case_types = {item.strip() for item in (case_types or ()) if item.strip()}
    cases = repository.list_hard_cases(limit=limit)
    exported: list[dict[str, Any]] = []

    for case in cases:
        if selected_case_types and case.get("case_type") not in selected_case_types:
            continue
        alert = repository.get_alert(case["alert_id"]) or {}
        case_dir = export_dir / str(case["alert_id"])
        case_dir.mkdir(parents=True, exist_ok=True)
        local_snapshot = _copy_optional(case.get("snapshot_path") or alert.get("snapshot_path"), case_dir, "snapshot")
        local_clip = _copy_optional(case.get("clip_path") or alert.get("clip_path"), case_dir, "clip")
        created_at = case.get("created_at") or alert.get("created_at")
        scene_tags = sorted(
            set(
                _scene_tags_from_values(
                    case.get("case_type"),
                    case.get("note"),
                    alert.get("review_note"),
                    alert.get("governance_note"),
                    alert.get("location"),
                    alert.get("zone_name"),
                    alert.get("workshop_name"),
                )
            )
        )
        record = {
            "case_id": case.get("case_id"),
            "alert_id": case.get("alert_id"),
            "event_no": case.get("event_no") or alert.get("event_no"),
            "case_type": case.get("case_type"),
            "label_bucket": _label_bucket_from_case(case.get("case_type"), alert),
            "scene_tags": scene_tags,
            "camera_id": alert.get("camera_id"),
            "camera_name": alert.get("camera_name"),
            "date": _parse_date_key(created_at),
            "note": case.get("note"),
            "snapshot_path": local_snapshot,
            "clip_path": local_clip,
            "source_snapshot_path": _repo_rel_label(case.get("snapshot_path") or alert.get("snapshot_path"), root),
            "source_clip_path": _repo_rel_label(case.get("clip_path") or alert.get("clip_path"), root),
            "snapshot_exists": bool(local_snapshot and Path(local_snapshot).exists()),
            "clip_exists": bool(local_clip and Path(local_clip).exists()),
            "created_at": created_at,
        }
        _atomic_write_json(case_dir / "export_case.json", record)
        exported.append(record)

    scene_breakdown = _collect_scene_breakdown_from_cases(exported)
    label_breakdown = Counter({label: 0 for label in ALLOWED_DETECTOR_LABELS})
    case_type_breakdown = Counter()
    camera_breakdown = Counter()
    for case in exported:
        label_breakdown[str(case.get("label_bucket") or "no_helmet")] += 1
        case_type_breakdown[str(case.get("case_type") or "unknown")] += 1
        camera_breakdown[str(case.get("camera_id") or "unknown")] += 1

    cases_manifest = {
        "export_id": export_id,
        "created_at": utc_now().isoformat(),
        "case_count": len(exported),
        "case_type_breakdown": dict(sorted(case_type_breakdown.items())),
        "camera_breakdown": dict(sorted(camera_breakdown.items())),
        "scene_breakdown": scene_breakdown,
        "label_breakdown": {label: label_breakdown.get(label, 0) for label in ALLOWED_DETECTOR_LABELS},
        "allowed_labels": list(ALLOWED_DETECTOR_LABELS),
        "cases": exported,
    }
    cases_manifest_path = export_dir / "feedback_cases_manifest.json"
    _atomic_write_json(cases_manifest_path, cases_manifest)

    manifest = {
        "export_id": export_id,
        "export_dir": str(export_dir),
        "case_count": len(exported),
        "case_types": sorted(selected_case_types) if selected_case_types else [],
        "created_at": utc_now().isoformat(),
        "actor": actor,
        "note": note,
        "cases": exported,
        "feedback_cases_manifest_path": str(cases_manifest_path),
        "scene_breakdown": scene_breakdown,
        "label_breakdown": {label: label_breakdown.get(label, 0) for label in ALLOWED_DETECTOR_LABELS},
    }
    _atomic_write_json(export_dir / "feedback_export.json", manifest)
    registry_path = _registry_path(settings, "model_feedback_registry", repo_root=repo_root)
    registry = _read_json(registry_path, {"exports": [], "datasets": []})
    registry.setdefault("exports", []).append(
        {
            "export_id": export_id,
            "export_dir": str(export_dir),
            "case_count": len(exported),
            "manifest_path": str(cases_manifest_path),
            "created_at": manifest["created_at"],
        }
    )
    _atomic_write_json(registry_path, registry)
    _record_audit(
        repository,
        entity_type="model_feedback",
        entity_id=export_id,
        action_type="export_feedback",
        actor=actor,
        payload={
            "case_count": len(exported),
            "export_dir": str(export_dir),
            "case_types": manifest["case_types"],
            "feedback_cases_manifest_path": str(cases_manifest_path),
        },
    )
    return manifest


def build_feedback_dataset(
    settings: AppSettings,
    *,
    base_dataset_yaml: str = "configs/datasets/shwd_yolo26.yaml",
    actor: str = "system",
    note: str | None = None,
    repository: AlertRepository | None = None,
    repo_root: Path | None = None,
    source_export_manifest_path: str | None = None,
    site_benchmark_manifest_path: str | None = None,
) -> dict[str, Any]:
    paths = ensure_feedback_workspace(settings, repo_root=repo_root)
    root = paths["repo_root"]
    dataset_yaml_path = Path(base_dataset_yaml)
    if not dataset_yaml_path.is_absolute():
        dataset_yaml_path = (root / dataset_yaml_path).resolve()
    dataset_info = _parse_dataset_yaml(dataset_yaml_path, root)
    base_train_images = _iter_images(_resolve_dataset_split(dataset_info["root"], dataset_info["train"]))
    base_val_images = _iter_images(_resolve_dataset_split(dataset_info["root"], dataset_info["val"]))
    feedback_train_images = [
        item
        for item in _iter_images(paths["labeled_images_train"])
        if _feedback_label_exists(item, paths["labeled_images_train"], paths["labeled_labels_train"])
    ]
    feedback_val_images = [
        item
        for item in _iter_images(paths["labeled_images_val"])
        if _feedback_label_exists(item, paths["labeled_images_val"], paths["labeled_labels_val"])
    ]

    latest_export = _latest_registry_entry(settings, "model_feedback_registry", "exports", repo_root=repo_root)
    export_manifest_path = source_export_manifest_path or (latest_export or {}).get("manifest_path")
    export_manifest = {}
    if export_manifest_path:
        resolved_export = _resolve_repo_path(export_manifest_path, root)
        if resolved_export and resolved_export.exists():
            export_manifest = json.loads(resolved_export.read_text(encoding="utf-8"))

    benchmark_manifest_path = site_benchmark_manifest_path or str(paths["quality_reports_dir"] / "site_benchmark_manifest.json")
    benchmark_manifest = {}
    resolved_benchmark = _resolve_repo_path(benchmark_manifest_path, root)
    if resolved_benchmark and resolved_benchmark.exists():
        benchmark_manifest = json.loads(resolved_benchmark.read_text(encoding="utf-8"))

    dataset_id = f"feedback-dataset-{utc_now().strftime('%Y%m%d-%H%M%S')}"
    output_dir = paths["feedback_exports_dir"] / dataset_id
    output_dir.mkdir(parents=True, exist_ok=True)
    train_list_path = output_dir / "train.txt"
    val_list_path = output_dir / "val.txt"
    dataset_output_path = output_dir / "feedback_dataset.yaml"
    manifest_path = output_dir / "dataset_manifest.json"

    train_images = [str(item.resolve()) for item in base_train_images + feedback_train_images]
    val_images = [str(item.resolve()) for item in base_val_images + feedback_val_images]
    train_list_path.write_text("\n".join(train_images) + ("\n" if train_images else ""), encoding="utf-8")
    val_list_path.write_text("\n".join(val_images) + ("\n" if val_images else ""), encoding="utf-8")

    names_lines = "\n".join(f"  {index}: {label}" for index, label in sorted(dataset_info["names"].items()))
    dataset_output_path.write_text(
        "\n".join(["path: .", f"train: {train_list_path}", f"val: {val_list_path}", "names:", names_lines or "  0: helmet\n  1: no_helmet", ""]),
        encoding="utf-8",
    )

    feedback_labeled_ready = bool(feedback_train_images or feedback_val_images)
    scene_breakdown = export_manifest.get("scene_breakdown") or {tag: 0 for tag in SCENE_TAGS}
    label_breakdown = _collect_label_breakdown_from_images(
        list(base_train_images) + list(base_val_images) + list(feedback_train_images) + list(feedback_val_images),
        dataset_root=dataset_info["root"],
    )
    benchmark_summary = benchmark_manifest.get("summary", {}) if isinstance(benchmark_manifest, dict) else {}

    manifest = {
        "dataset_id": dataset_id,
        "dataset_yaml": str(dataset_output_path),
        "manifest_path": str(manifest_path),
        "base_dataset_yaml": str(dataset_yaml_path),
        "base_train_images": len(base_train_images),
        "base_val_images": len(base_val_images),
        "feedback_train_images": len(feedback_train_images),
        "feedback_val_images": len(feedback_val_images),
        "feedback_labeled_ready": feedback_labeled_ready,
        "train_total": len(train_images),
        "val_total": len(val_images),
        "scene_breakdown": {tag: int(scene_breakdown.get(tag, 0)) for tag in SCENE_TAGS},
        "label_breakdown": {label: int(label_breakdown.get(label, 0)) for label in ALLOWED_DETECTOR_LABELS},
        "source_exports": [
            {
                "export_id": export_manifest.get("export_id"),
                "manifest_path": _repo_rel_label(export_manifest_path, root) if export_manifest_path else None,
                "case_count": export_manifest.get("case_count"),
            }
        ]
        if export_manifest
        else [],
        "site_benchmark_manifest": {
            "path": _repo_rel_label(benchmark_manifest_path, root) if benchmark_manifest_path else None,
            "status": benchmark_manifest.get("status"),
            "total_items": benchmark_summary.get("total"),
            "splits": benchmark_summary.get("splits", {}),
        }
        if benchmark_manifest
        else None,
        "hard_case_manifest": {
            "path": _repo_rel_label(export_manifest_path, root) if export_manifest_path else None,
            "case_type_breakdown": export_manifest.get("case_type_breakdown", {}),
        }
        if export_manifest
        else None,
        "allowed_labels": list(ALLOWED_DETECTOR_LABELS),
        "created_at": utc_now().isoformat(),
        "actor": actor,
        "note": note,
    }
    _atomic_write_json(manifest_path, manifest)
    registry_path = _registry_path(settings, "model_feedback_registry", repo_root=repo_root)
    registry = _read_json(registry_path, {"exports": [], "datasets": []})
    registry.setdefault("datasets", []).append(
        {
            "dataset_id": dataset_id,
            "dataset_yaml": str(dataset_output_path),
            "manifest_path": str(manifest_path),
            "feedback_labeled_ready": feedback_labeled_ready,
            "created_at": manifest["created_at"],
        }
    )
    _atomic_write_json(registry_path, registry)
    _record_audit(
        repository,
        entity_type="model_dataset",
        entity_id=dataset_id,
        action_type="build_feedback_dataset",
        actor=actor,
        payload={
            "dataset_yaml": str(dataset_output_path),
            "feedback_train_images": len(feedback_train_images),
            "feedback_val_images": len(feedback_val_images),
            "feedback_labeled_ready": feedback_labeled_ready,
        },
    )
    return manifest


def register_model(
    settings: AppSettings,
    *,
    model_path: str,
    dataset_manifest_path: str | None = None,
    metrics: dict[str, Any] | None = None,
    actor: str = "system",
    note: str | None = None,
    repository: AlertRepository | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    ensure_feedback_workspace(settings, repo_root=repo_root)
    registry_path = _registry_path(settings, "model_registry", repo_root=repo_root)
    registry = _read_json(registry_path, {"active_model": None, "models": [], "promotion_history": []})
    target_path = Path(model_path)
    if not target_path.is_absolute():
        target_path = ((repo_root or REPO_ROOT) / target_path).resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"Model file not found: {target_path}")

    model_id = f"model-{utc_now().strftime('%Y%m%d-%H%M%S')}-{target_path.stem}"
    record = {
        "model_id": model_id,
        "model_name": target_path.name,
        "model_path": str(target_path),
        "dataset_manifest_path": dataset_manifest_path,
        "metrics": metrics or {},
        "size_bytes": target_path.stat().st_size,
        "sha256": sha256_file(target_path),
        "registered_at": utc_now().isoformat(),
        "actor": actor,
        "note": note,
        "promoted_at": None,
    }
    models = [item for item in registry.get("models", []) if item.get("model_path") != str(target_path)]
    models.append(record)
    registry["models"] = models
    _atomic_write_json(registry_path, registry)
    _record_audit(
        repository,
        entity_type="model",
        entity_id=model_id,
        action_type="register_model",
        actor=actor,
        payload={"model_path": str(target_path), "dataset_manifest_path": dataset_manifest_path, "sha256": record["sha256"]},
    )
    return record


def _config_relative_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def promote_model(
    settings: AppSettings,
    *,
    model_id: str | None = None,
    model_path: str | None = None,
    actor: str = "system",
    note: str | None = None,
    repository: AlertRepository | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    root = (repo_root or REPO_ROOT).resolve()
    registry_path = _registry_path(settings, "model_registry", repo_root=repo_root)
    registry = _read_json(registry_path, {"active_model": None, "models": [], "promotion_history": []})
    record: dict[str, Any] | None = None

    if model_id:
        record = next((item for item in registry.get("models", []) if item.get("model_id") == model_id), None)
    elif model_path:
        target = Path(model_path)
        if not target.is_absolute():
            target = (root / target).resolve()
        record = next((item for item in registry.get("models", []) if Path(item.get("model_path", "")).resolve() == target), None)
        if record is None:
            record = register_model(
                settings,
                model_path=str(target),
                actor=actor,
                note=note,
                repository=repository,
                repo_root=repo_root,
            )
            registry = _read_json(registry_path, {"active_model": None, "models": [], "promotion_history": []})
    if record is None:
        raise ValueError("A registered model_id or model_path is required for promotion.")

    config_payload = json.loads(settings.config_path.read_text(encoding="utf-8"))
    previous_model = config_payload.get("model", {}).get("path")
    config_payload.setdefault("model", {})["path"] = _config_relative_path(Path(record["model_path"]), root)
    settings.config_path.write_text(json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    promoted_at = utc_now().isoformat()
    for item in registry.get("models", []):
        if item.get("model_id") == record["model_id"]:
            item["promoted_at"] = promoted_at
    promotion = {
        "model_id": record["model_id"],
        "previous_model_path": previous_model,
        "promoted_model_path": config_payload["model"]["path"],
        "promoted_at": promoted_at,
        "actor": actor,
        "note": note,
    }
    registry["active_model"] = record["model_id"]
    registry.setdefault("promotion_history", []).append(promotion)
    _atomic_write_json(registry_path, registry)
    create_release_snapshot(
        settings,
        release_name=f"{record['model_id']}-release",
        activate=True,
        actor=actor,
        note=note,
        release_kind="model_promotion",
        repository=repository,
        repo_root=repo_root,
    )
    _record_audit(repository, entity_type="model", entity_id=record["model_id"], action_type="promote_model", actor=actor, payload=promotion)
    return promotion
