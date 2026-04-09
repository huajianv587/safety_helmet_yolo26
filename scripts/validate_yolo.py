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
    parser = argparse.ArgumentParser(description="Validate a YOLO detector with the current project layout.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--data", default="configs/datasets/shwd_yolo26.yaml", help="Dataset YAML path.")
    parser.add_argument("--weights", default="artifacts/models/yolov8n.pt", help="Trained YOLO weights.")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size.")
    parser.add_argument("--batch", type=int, default=16, help="Batch size.")
    parser.add_argument("--device", default="", help="Device, for example cpu, 0, or 0,1.")
    parser.add_argument("--workers", type=int, default=4, help="Dataloader workers.")
    parser.add_argument("--project", default="artifacts/validation_runs", help="Validation output directory.")
    parser.add_argument("--name", default="val_product", help="Run name.")
    return parser.parse_args()


def _resolve_path(settings, value: str) -> str:
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

    data_path = _resolve_path(settings, args.data)
    weights_path = _resolve_path(settings, args.weights)
    project_path = settings.resolve_path(args.project)
    project_path.mkdir(parents=True, exist_ok=True)

    model = YOLO(weights_path)
    results = model.val(
        data=data_path,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device or settings.model.device,
        workers=args.workers,
        project=str(project_path),
        name=args.name,
        exist_ok=True,
    )

    box = results.box
    print(f"save_dir={results.save_dir}")
    print(f"precision={box.mp:.5f}")
    print(f"recall={box.mr:.5f}")
    print(f"map50={box.map50:.5f}")
    print(f"map50_95={box.map:.5f}")


if __name__ == "__main__":
    main()
