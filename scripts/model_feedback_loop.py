from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.model_governance import build_feedback_dataset, export_feedback_cases, promote_model, register_model
from helmet_monitoring.storage.repository import build_repository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the model feedback loop: export issues, build datasets, register models, and promote versions.")
    parser.add_argument("--config", default=None, help="Runtime config path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export-feedback", help="Export hard cases into a versioned bundle.")
    export.add_argument("--limit", type=int, default=200, help="Maximum hard cases to export.")
    export.add_argument("--actor", default="system", help="Audit actor.")
    export.add_argument("--note", default=None, help="Optional export note.")

    dataset = subparsers.add_parser("build-dataset", help="Build a merged dataset YAML from base data and labeled feedback.")
    dataset.add_argument("--base-data", default="configs/datasets/shwd_yolo26.yaml", help="Base dataset YAML.")
    dataset.add_argument("--actor", default="system", help="Audit actor.")
    dataset.add_argument("--note", default=None, help="Optional dataset note.")

    register = subparsers.add_parser("register-model", help="Register a trained model file.")
    register.add_argument("model_path", help="Model file path.")
    register.add_argument("--dataset-manifest", default=None, help="Dataset manifest path.")
    register.add_argument("--actor", default="system", help="Audit actor.")
    register.add_argument("--note", default=None, help="Optional registration note.")

    promote = subparsers.add_parser("promote-model", help="Promote a registered or on-disk model into runtime.json.")
    promote.add_argument("--model-id", default=None, help="Registered model id.")
    promote.add_argument("--model-path", default=None, help="Model file path to register/promote.")
    promote.add_argument("--actor", default="system", help="Audit actor.")
    promote.add_argument("--note", default=None, help="Optional promotion note.")

    cycle = subparsers.add_parser("full-cycle", help="Export feedback, build dataset, optionally train, then register/promote.")
    cycle.add_argument("--base-data", default="configs/datasets/shwd_yolo26.yaml", help="Base dataset YAML.")
    cycle.add_argument("--train", action="store_true", help="Run scripts/train_yolo.py with the merged dataset.")
    cycle.add_argument("--promote", action="store_true", help="Promote the resulting model after registration.")
    cycle.add_argument("--train-name", default="feedback_cycle", help="Training run name.")
    cycle.add_argument("--epochs", type=int, default=80, help="Training epochs when --train is used.")
    cycle.add_argument("--actor", default="system", help="Audit actor.")
    cycle.add_argument("--note", default=None, help="Optional cycle note.")
    return parser.parse_args()


def _run_training(dataset_yaml: str, train_name: str, epochs: int) -> str:
    command = [
        sys.executable,
        "scripts/train_yolo.py",
        "--data",
        dataset_yaml,
        "--name",
        train_name,
        "--epochs",
        str(epochs),
    ]
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    best_model = ""
    for line in result.stdout.splitlines():
        if line.startswith("best_model="):
            best_model = line.split("=", 1)[1].strip()
            break
    if not best_model:
        raise RuntimeError(f"Training completed but best_model was not reported.\n{result.stdout}")
    return best_model


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    repository = build_repository(settings)

    if args.command == "export-feedback":
        print(json.dumps(export_feedback_cases(settings, repository, limit=args.limit, actor=args.actor, note=args.note), ensure_ascii=False, indent=2))
        return
    if args.command == "build-dataset":
        print(json.dumps(build_feedback_dataset(settings, base_dataset_yaml=args.base_data, actor=args.actor, note=args.note, repository=repository), ensure_ascii=False, indent=2))
        return
    if args.command == "register-model":
        print(json.dumps(register_model(settings, model_path=args.model_path, dataset_manifest_path=args.dataset_manifest, actor=args.actor, note=args.note, repository=repository), ensure_ascii=False, indent=2))
        return
    if args.command == "promote-model":
        print(json.dumps(promote_model(settings, model_id=args.model_id, model_path=args.model_path, actor=args.actor, note=args.note, repository=repository), ensure_ascii=False, indent=2))
        return

    export_record = export_feedback_cases(settings, repository, actor=args.actor, note=args.note)
    dataset_record = build_feedback_dataset(
        settings,
        base_dataset_yaml=args.base_data,
        actor=args.actor,
        note=args.note,
        repository=repository,
    )
    response: dict[str, object] = {"export": export_record, "dataset": dataset_record}
    if args.train:
        best_model = _run_training(dataset_record["dataset_yaml"], args.train_name, args.epochs)
        model_record = register_model(
            settings,
            model_path=best_model,
            dataset_manifest_path=dataset_record["manifest_path"],
            actor=args.actor,
            note=args.note,
            repository=repository,
        )
        response["model"] = model_record
        if args.promote:
            response["promotion"] = promote_model(
                settings,
                model_id=model_record["model_id"],
                actor=args.actor,
                note=args.note,
                repository=repository,
            )
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
