from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.model_governance import build_benchmark_dataset_bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a YOLO helmet detector with dataset YAML or a benchmark manifest.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--data", default="configs/datasets/shwd_yolo26.yaml", help="Dataset YAML path.")
    parser.add_argument("--benchmark-manifest", default="", help="Optional benchmark manifest path.")
    parser.add_argument("--manifest-splits", default="train,val", help="Comma-separated benchmark splits to use for training/validation.")
    parser.add_argument("--generated-data-root", default="", help="Where to write generated manifest-driven train.txt / val.txt / yaml.")
    parser.add_argument("--weights", default="artifacts/models/yolov8n.pt", help="Base YOLO weights or model name.")
    parser.add_argument("--project", default="artifacts/training_runs/helmet_project", help="Training project directory.")
    parser.add_argument("--name", default="train_product", help="Run name.")
    parser.add_argument("--epochs", type=int, default=80, help="Training epochs.")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size.")
    parser.add_argument("--batch", type=int, default=16, help="Batch size.")
    parser.add_argument("--device", default="", help="Device, for example cpu, 0, or 0,1.")
    parser.add_argument("--workers", type=int, default=4, help="Dataloader workers.")
    parser.add_argument("--patience", type=int, default=20, help="Early stopping patience.")
    parser.add_argument("--fraction", type=float, default=1.0, help="Optional Ultralytics data fraction for short compare runs.")
    parser.add_argument("--export-onnx", action="store_true", help="Export the best checkpoint to ONNX after training.")
    parser.add_argument("--json-output", action="store_true", help="Print structured JSON output instead of plain lines.")
    return parser.parse_args()


def _resolve_training_path(settings, value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate)
    resolved = settings.resolve_path(value)
    if resolved.exists():
        return str(resolved)
    return value


def _parse_manifest_splits(raw: str) -> tuple[list[str], list[str]]:
    splits = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    if not splits:
        return ["train"], ["val"]
    if "val" in splits:
        train_splits = [item for item in splits if item != "val"] or ["train"]
        val_splits = ["val"]
    else:
        train_splits = splits[:-1] or splits
        val_splits = [splits[-1]]
    return train_splits, val_splits


def _read_run_metrics(save_dir: Path) -> dict[str, float]:
    results_csv = save_dir / "results.csv"
    if not results_csv.exists():
        return {}
    with results_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    row = rows[-1]
    metrics: dict[str, float] = {}
    mapping = {
        "precision": "metrics/precision(B)",
        "recall": "metrics/recall(B)",
        "map50": "metrics/mAP50(B)",
        "map50_95": "metrics/mAP50-95(B)",
    }
    for target, source in mapping.items():
        try:
            metrics[target] = round(float(row.get(source, "") or 0.0), 5)
        except ValueError:
            continue
    if "precision" in metrics and "recall" in metrics and (metrics["precision"] + metrics["recall"]) > 0:
        precision = metrics["precision"]
        recall = metrics["recall"]
        metrics["f1"] = round(2 * precision * recall / (precision + recall), 5)
    return metrics


def _emit_json(payload: dict[str, Any]) -> None:
    message = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    sys.stdout.buffer.write(message.encode("utf-8", errors="replace"))
    sys.stdout.flush()


def run_training(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.config)
    runtime_root = Path(args.config).resolve().parents[1]

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Ultralytics is not installed. Use the project .venv or install requirements.txt.") from exc

    project_path = settings.resolve_path(args.project)
    project_path.mkdir(parents=True, exist_ok=True)
    manifest_summary: dict[str, Any] | None = None
    data_path = _resolve_training_path(settings, args.data)
    if args.benchmark_manifest:
        train_splits, val_splits = _parse_manifest_splits(args.manifest_splits)
        generated_root = (
            settings.resolve_path(args.generated_data_root)
            if args.generated_data_root
            else project_path / args.name / "benchmark_data"
        )
        manifest_summary = build_benchmark_dataset_bundle(
            settings,
            benchmark_manifest_path=args.benchmark_manifest,
            output_dir=generated_root,
            train_splits=train_splits,
            val_splits=val_splits,
            repo_root=runtime_root,
        )
        if not manifest_summary.get("training_ready"):
            raise RuntimeError(
                "Benchmark manifest does not contain enough labeled train/val items for training. "
                "Use --data for merged dataset training or label more benchmark samples."
            )
        data_path = manifest_summary["dataset_yaml"]

    weights_path = _resolve_training_path(settings, args.weights)
    model = YOLO(weights_path)
    results = model.train(
        data=data_path,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device or settings.model.device,
        workers=args.workers,
        patience=args.patience,
        project=str(project_path),
        name=args.name,
        exist_ok=True,
        fraction=args.fraction,
        verbose=False,
    )

    save_dir = Path(results.save_dir)
    best_path = save_dir / "weights" / "best.pt"
    response: dict[str, Any] = {
        "save_dir": str(save_dir),
        "best_model": str(best_path),
        "data_path": str(data_path),
        "weights_path": str(weights_path),
        "project_path": str(project_path),
        "run_name": args.name,
        "epochs": args.epochs,
        "fraction": args.fraction,
        "metrics": _read_run_metrics(save_dir),
    }
    if manifest_summary:
        response["benchmark_dataset"] = manifest_summary

    if args.export_onnx and best_path.exists():
        exported = YOLO(str(best_path)).export(format="onnx")
        response["onnx_export"] = str(exported)
    return response


def main() -> None:
    args = parse_args()
    payload = run_training(args)
    if args.json_output:
        _emit_json(payload)
        return
    print(f"save_dir={payload['save_dir']}")
    print(f"best_model={payload['best_model']}")
    if payload.get("benchmark_dataset"):
        print(f"benchmark_dataset={payload['benchmark_dataset']['manifest_path']}")
    if payload.get("metrics"):
        print(f"metrics={json.dumps(payload['metrics'], ensure_ascii=False)}")
    if payload.get("onnx_export"):
        print(f"onnx_export={payload['onnx_export']}")


if __name__ == "__main__":
    main()
