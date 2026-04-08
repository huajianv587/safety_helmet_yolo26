from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a YOLO helmet detector with the current project layout.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--data", default="configs/datasets/shwd_yolo26.yaml", help="Dataset YAML path.")
    parser.add_argument("--weights", default="artifacts/models/yolov8n.pt", help="Base YOLO weights or model name.")
    parser.add_argument("--project", default="artifacts/training_runs/helmet_project", help="Training project directory.")
    parser.add_argument("--name", default="train_product", help="Run name.")
    parser.add_argument("--epochs", type=int, default=80, help="Training epochs.")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size.")
    parser.add_argument("--batch", type=int, default=16, help="Batch size.")
    parser.add_argument("--device", default="", help="Device, for example cpu, 0, or 0,1.")
    parser.add_argument("--workers", type=int, default=4, help="Dataloader workers.")
    parser.add_argument("--patience", type=int, default=20, help="Early stopping patience.")
    parser.add_argument("--export-onnx", action="store_true", help="Export the best checkpoint to ONNX after training.")
    return parser.parse_args()


def _resolve_training_path(settings, value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate)
    resolved = settings.resolve_path(value)
    if resolved.exists():
        return str(resolved)
    return value


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Ultralytics is not installed. Use the project .venv or install requirements.txt.") from exc

    data_path = _resolve_training_path(settings, args.data)
    weights_path = _resolve_training_path(settings, args.weights)
    project_path = settings.resolve_path(args.project)
    project_path.mkdir(parents=True, exist_ok=True)

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
    )

    save_dir = Path(results.save_dir)
    best_path = save_dir / "weights" / "best.pt"
    print(f"save_dir={save_dir}")
    print(f"best_model={best_path}")

    if args.export_onnx and best_path.exists():
        exported = YOLO(str(best_path)).export(format="onnx")
        print(f"onnx_export={exported}")


if __name__ == "__main__":
    main()
