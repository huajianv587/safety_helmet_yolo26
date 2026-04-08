from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

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
from helmet_monitoring.storage.repository import AlertRepository


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}


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
        "labeled_images_train": base / "data" / "hard_cases" / "labeled" / "images" / "train",
        "labeled_images_val": base / "data" / "hard_cases" / "labeled" / "images" / "val",
        "labeled_labels_train": base / "data" / "hard_cases" / "labeled" / "labels" / "train",
        "labeled_labels_val": base / "data" / "hard_cases" / "labeled" / "labels" / "val",
        "feedback_exports_dir": base / "artifacts" / "exports" / "model_feedback",
        "runtime_dir": runtime_dir,
    }


def ensure_feedback_workspace(settings: AppSettings, repo_root: Path | None = None) -> dict[str, Path]:
    paths = feedback_paths(settings, repo_root=repo_root)
    for key in (
        "false_positive_dir",
        "missed_detection_dir",
        "night_shift_dir",
        "labeled_images_train",
        "labeled_images_val",
        "labeled_labels_train",
        "labeled_labels_val",
        "feedback_exports_dir",
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
    manifest = {
        "alert_id": alert.get("alert_id"),
        "event_no": alert.get("event_no"),
        "case_type": case_type,
        "status": "queued",
        "note": note,
        "source_snapshot_path": alert.get("snapshot_path"),
        "source_clip_path": alert.get("clip_path"),
        "local_snapshot_path": local_snapshot,
        "local_clip_path": local_clip,
        "created_at": utc_now().isoformat(),
    }
    _atomic_write_json(case_dir / "case_manifest.json", manifest)
    return manifest


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
    return {"root": dataset_root, "train": train_value, "val": val_value, "names": names}


def _resolve_dataset_split(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (root / candidate).resolve()


def _registry_path(settings: AppSettings, key: str, repo_root: Path | None = None) -> Path:
    return operations_paths(settings, repo_root=repo_root)[key]


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
        case_dir = export_dir / case["alert_id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        local_snapshot = _copy_optional(case.get("snapshot_path") or alert.get("snapshot_path"), case_dir, "snapshot")
        local_clip = _copy_optional(case.get("clip_path") or alert.get("clip_path"), case_dir, "clip")
        record = {
            "case_id": case.get("case_id"),
            "alert_id": case.get("alert_id"),
            "event_no": case.get("event_no") or alert.get("event_no"),
            "case_type": case.get("case_type"),
            "note": case.get("note"),
            "snapshot_path": local_snapshot,
            "clip_path": local_clip,
            "created_at": case.get("created_at"),
        }
        _atomic_write_json(case_dir / "export_case.json", record)
        exported.append(record)

    manifest = {
        "export_id": export_id,
        "export_dir": str(export_dir),
        "case_count": len(exported),
        "case_types": sorted(selected_case_types) if selected_case_types else [],
        "created_at": utc_now().isoformat(),
        "actor": actor,
        "note": note,
        "cases": exported,
    }
    _atomic_write_json(export_dir / "feedback_export.json", manifest)
    registry_path = _registry_path(settings, "model_feedback_registry", repo_root=repo_root)
    registry = _read_json(registry_path, {"exports": [], "datasets": []})
    registry.setdefault("exports", []).append(
        {
            "export_id": export_id,
            "export_dir": str(export_dir),
            "case_count": len(exported),
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
        payload={"case_count": len(exported), "export_dir": str(export_dir), "case_types": manifest["case_types"]},
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
        "\n".join(["path: .", f"train: {train_list_path}", f"val: {val_list_path}", "names:", names_lines or "  0: helmet", ""]),
        encoding="utf-8",
    )

    manifest = {
        "dataset_id": dataset_id,
        "dataset_yaml": str(dataset_output_path),
        "manifest_path": str(manifest_path),
        "base_dataset_yaml": str(dataset_yaml_path),
        "base_train_images": len(base_train_images),
        "base_val_images": len(base_val_images),
        "feedback_train_images": len(feedback_train_images),
        "feedback_val_images": len(feedback_val_images),
        "train_total": len(train_images),
        "val_total": len(val_images),
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
