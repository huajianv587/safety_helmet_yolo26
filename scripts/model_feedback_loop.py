from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.model_governance import (
    build_feedback_dataset,
    export_feedback_cases,
    feedback_paths,
    promote_model,
    register_model,
)
from helmet_monitoring.services.operations import operations_paths
from helmet_monitoring.services.operations_studio import build_quality_summary
from helmet_monitoring.services.person_directory import PersonDirectory
from helmet_monitoring.storage.repository import build_repository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the model feedback loop: export issues, build datasets, compare models, and optionally promote.")
    parser.add_argument("--config", default=None, help="Runtime config path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export-feedback", help="Export hard cases into a versioned bundle.")
    export.add_argument("--limit", type=int, default=200, help="Maximum hard cases to export.")
    export.add_argument("--case-types", default="", help="Optional comma-separated case types to export.")
    export.add_argument("--actor", default="system", help="Audit actor.")
    export.add_argument("--note", default=None, help="Optional export note.")

    dataset = subparsers.add_parser("build-dataset", help="Build a merged dataset YAML from base data and labeled feedback.")
    dataset.add_argument("--base-data", default="configs/datasets/shwd_yolo26.yaml", help="Base dataset YAML.")
    dataset.add_argument("--source-export-manifest", default=None, help="Optional hard-case export manifest path.")
    dataset.add_argument("--site-benchmark-manifest", default="artifacts/reports/quality/site_benchmark_manifest.json", help="Optional benchmark manifest path.")
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

    train_compare = subparsers.add_parser("train-compare", help="Run a local short-cycle compare training job.")
    train_compare.add_argument("--dataset-yaml", default=None, help="Dataset YAML. Defaults to the latest dataset manifest.")
    train_compare.add_argument("--dataset-manifest", default=None, help="Dataset manifest for registration metadata.")
    train_compare.add_argument("--benchmark-manifest", default="artifacts/reports/quality/site_benchmark_manifest.json", help="Benchmark manifest path.")
    train_compare.add_argument("--weights", default="artifacts/training_runs/helmet_project/yolo26n_cpu_v2_voxel_ft/weights/best.pt", help="Baseline weights.")
    train_compare.add_argument("--epochs", type=int, default=6, help="Training epochs.")
    train_compare.add_argument("--batch", type=int, default=8, help="Batch size.")
    train_compare.add_argument("--workers", type=int, default=2, help="Workers.")
    train_compare.add_argument("--imgsz", type=int, default=640, help="Image size.")
    train_compare.add_argument("--device", default="cpu", help="Training device.")
    train_compare.add_argument("--fraction", type=float, default=0.05, help="Dataset fraction for CPU compare runs.")
    train_compare.add_argument("--train-name", default="", help="Optional run name.")
    train_compare.add_argument("--actor", default="system", help="Audit actor.")
    train_compare.add_argument("--note", default=None, help="Optional training note.")

    validate_compare = subparsers.add_parser("validate-compare", help="Validate the active baseline and a candidate model.")
    validate_compare.add_argument("--candidate-model", default=None, help="Candidate model path. Defaults to the latest compare train artifact.")
    validate_compare.add_argument("--baseline-model", default=None, help="Baseline model path. Defaults to current runtime model.")
    validate_compare.add_argument("--dataset-yaml", default=None, help="Dataset YAML for val metrics. Defaults to latest dataset manifest.")
    validate_compare.add_argument("--benchmark-manifest", default="artifacts/reports/quality/site_benchmark_manifest.json", help="Benchmark manifest path.")
    validate_compare.add_argument("--pilot-limit", type=int, default=60, help="Pilot replay hard-case limit.")
    validate_compare.add_argument("--hard-case-types", default="false_positive,missed_detection,night,backlight,crowd,occlusion", help="Pilot replay case types.")
    validate_compare.add_argument("--imgsz", type=int, default=640, help="Validation image size.")
    validate_compare.add_argument("--batch", type=int, default=8, help="Validation batch size.")
    validate_compare.add_argument("--workers", type=int, default=2, help="Validation workers.")
    validate_compare.add_argument("--device", default="cpu", help="Validation device.")
    validate_compare.add_argument("--actor", default="system", help="Audit actor.")
    validate_compare.add_argument("--note", default=None, help="Optional validation note.")

    compare_report = subparsers.add_parser("compare-report", help="Build a detector compare report and refresh Quality Lab artifacts.")
    compare_report.add_argument("--validation-artifact", default=None, help="Validation artifact path. Defaults to the latest compare validation artifact.")
    compare_report.add_argument("--actor", default="system", help="Audit actor.")
    compare_report.add_argument("--note", default=None, help="Optional report note.")

    cycle = subparsers.add_parser("full-cycle", help="Export feedback, build dataset, run compare train/validate/report, and optionally promote.")
    cycle.add_argument("--base-data", default="configs/datasets/shwd_yolo26.yaml", help="Base dataset YAML.")
    cycle.add_argument("--limit", type=int, default=200, help="Maximum hard cases to export.")
    cycle.add_argument("--train", action="store_true", help="Run local compare training.")
    cycle.add_argument("--promote", action="store_true", help="Promote the resulting model if compare gate passes.")
    cycle.add_argument("--epochs", type=int, default=6, help="Training epochs when --train is used.")
    cycle.add_argument("--fraction", type=float, default=0.05, help="Dataset fraction for CPU compare runs.")
    cycle.add_argument("--train-name", default="", help="Optional compare run name.")
    cycle.add_argument("--pilot-limit", type=int, default=60, help="Pilot replay hard-case limit.")
    cycle.add_argument("--actor", default="system", help="Audit actor.")
    cycle.add_argument("--note", default=None, help="Optional cycle note.")
    return parser.parse_args()


def _quality_dir(settings) -> Path:
    return feedback_paths(settings, repo_root=REPO_ROOT)["quality_reports_dir"]


def _registry_path(settings, key: str) -> Path:
    return operations_paths(settings, repo_root=REPO_ROOT)[key]


def _latest_registry_entry(settings, key: str) -> dict[str, Any] | None:
    registry_path = _registry_path(settings, "model_feedback_registry")
    if not registry_path.exists():
        return None
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    items = registry.get(key, [])
    return items[-1] if items else None


def _latest_quality_artifact(settings, name: str) -> Path:
    return _quality_dir(settings) / name


def _resolve_manifest_path(path_value: str | None) -> str | None:
    if not path_value:
        return None
    candidate = Path(path_value)
    if candidate.exists():
        return str(candidate)
    fallback = (REPO_ROOT / candidate).resolve() if not candidate.is_absolute() else candidate
    return str(fallback) if fallback.exists() else path_value


def _resolve_dataset_yaml(settings, dataset_yaml: str | None, dataset_manifest_path: str | None = None) -> tuple[str, str | None]:
    if dataset_yaml:
        return dataset_yaml, dataset_manifest_path
    manifest_path = dataset_manifest_path
    if manifest_path is None:
        latest_dataset = _latest_registry_entry(settings, "datasets")
        manifest_path = latest_dataset.get("manifest_path") if latest_dataset else None
    if manifest_path is None:
        return "configs/datasets/shwd_yolo26.yaml", None
    resolved_manifest = _resolve_manifest_path(manifest_path)
    manifest = json.loads(Path(resolved_manifest).read_text(encoding="utf-8"))
    return str(manifest["dataset_yaml"]), str(manifest.get("manifest_path") or resolved_manifest)


def _resolve_candidate_training_artifact(settings) -> dict[str, Any] | None:
    path = _latest_quality_artifact(settings, "detector_compare_train.json")
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_baseline_model(settings) -> str:
    return str(settings.resolve_path(settings.model.path))


def _run_json_command(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    stdout = result.stdout or ""
    for start in range(len(stdout) - 1, -1, -1):
        if stdout[start] != "{":
            continue
        try:
            return json.loads(stdout[start:])
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"Command did not return JSON:\n{stdout}\n{result.stderr}")


def _run_json_command_or_placeholder(command: list[str], *, fallback_status: str, fallback_note: str) -> dict[str, Any]:
    try:
        return _run_json_command(command)
    except subprocess.CalledProcessError as exc:
        return {
            "status": fallback_status,
            "metrics": {},
            "notes": [fallback_note, exc.stderr.strip() or exc.stdout.strip()],
        }


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _write_markdown(path: Path, lines: list[str]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _emit_json(payload: dict[str, Any]) -> None:
    message = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    sys.stdout.buffer.write(message.encode("utf-8", errors="replace"))
    sys.stdout.flush()


def _compare_gate(validation_payload: dict[str, Any], dataset_manifest: dict[str, Any] | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    candidate = validation_payload["candidate"]
    baseline = validation_payload["baseline"]
    site_holdout_candidate = candidate.get("site_holdout", {}).get("metrics", {})
    site_holdout_baseline = baseline.get("site_holdout", {}).get("metrics", {})
    pilot_candidate = candidate.get("pilot_video_eval", {})
    pilot_baseline = baseline.get("pilot_video_eval", {})

    if dataset_manifest and not dataset_manifest.get("feedback_labeled_ready", False):
        reasons.append("feedback_labeled_ready=false")
    if candidate.get("site_holdout", {}).get("benchmark_dataset", {}).get("val_count", 0) < 1:
        reasons.append("site benchmark still lacks labeled site_holdout samples")
    candidate_f1 = float(site_holdout_candidate.get("f1") or 0.0)
    baseline_f1 = float(site_holdout_baseline.get("f1") or 0.0)
    if candidate_f1 < baseline_f1:
        reasons.append("candidate site_holdout F1 regressed")
    fp_candidate = int(pilot_candidate.get("false_positive") or 0)
    fp_baseline = int(pilot_baseline.get("false_positive") or 0)
    md_candidate = int(pilot_candidate.get("missed_detection") or 0)
    md_baseline = int(pilot_baseline.get("missed_detection") or 0)
    improved = (fp_candidate < fp_baseline) or (md_candidate < md_baseline)
    not_worse = fp_candidate <= fp_baseline and md_candidate <= md_baseline
    if not improved:
        reasons.append("pilot replay did not improve false positives or missed detections")
    if not not_worse:
        reasons.append("pilot replay regressed at least one error type")
    for tag in ("night", "backlight", "crowd", "occlusion"):
        candidate_scene = candidate.get("pilot_video_eval", {}).get("scene_results", {}).get(tag, {})
        baseline_scene = baseline.get("pilot_video_eval", {}).get("scene_results", {}).get(tag, {})
        if int(candidate_scene.get("samples") or 0) == 0 or int(baseline_scene.get("samples") or 0) == 0:
            continue
        candidate_rate = (candidate_scene.get("failures", 0) / candidate_scene.get("samples", 1)) if candidate_scene.get("samples") else 0.0
        baseline_rate = (baseline_scene.get("failures", 0) / baseline_scene.get("samples", 1)) if baseline_scene.get("samples") else 0.0
        if candidate_rate > baseline_rate:
            reasons.append(f"{tag} scene replay regressed")
    status = "promote" if not reasons else "review_required"
    return status, reasons


def _refresh_quality_summary(settings, repository) -> dict[str, Any]:
    directory = PersonDirectory(settings)
    return build_quality_summary(settings, repository, directory)


def _write_compare_report(settings, validation_payload: dict[str, Any], actor: str, note: str | None) -> dict[str, Any]:
    dataset_manifest_path = validation_payload.get("dataset_manifest_path")
    dataset_manifest = json.loads(Path(dataset_manifest_path).read_text(encoding="utf-8")) if dataset_manifest_path and Path(dataset_manifest_path).exists() else None
    gate_status, gate_reasons = _compare_gate(validation_payload, dataset_manifest)
    report = {
        "generated_at": validation_payload.get("generated_at"),
        "actor": actor,
        "note": note,
        "baseline_model": validation_payload["baseline"]["model_path"],
        "candidate_model": validation_payload["candidate"]["model_path"],
        "dataset_manifest_path": dataset_manifest_path,
        "val": {
            "baseline": validation_payload["baseline"].get("val", {}).get("metrics", {}),
            "candidate": validation_payload["candidate"].get("val", {}).get("metrics", {}),
        },
        "site_holdout": {
            "baseline": validation_payload["baseline"].get("site_holdout", {}).get("metrics", {}),
            "candidate": validation_payload["candidate"].get("site_holdout", {}).get("metrics", {}),
        },
        "pilot_replay": {
            "baseline": validation_payload["baseline"].get("pilot_video_eval", {}),
            "candidate": validation_payload["candidate"].get("pilot_video_eval", {}),
        },
        "scene_breakdown": validation_payload["candidate"].get("pilot_video_eval", {}).get("scene_results", {}),
        "conclusion": gate_status,
        "block_reasons": gate_reasons,
        "next_action": "continue_collecting_hard_cases" if gate_status != "promote" else "promotion_ready",
    }
    quality_dir = _quality_dir(settings)
    json_path = quality_dir / "detector_compare_report.json"
    markdown_path = quality_dir / "detector_compare_report.md"
    _write_json(json_path, report)
    _write_markdown(
        markdown_path,
        [
            "# Detector Compare Report",
            "",
            f"- Baseline: `{report['baseline_model']}`",
            f"- Candidate: `{report['candidate_model']}`",
            f"- Conclusion: `{report['conclusion']}`",
            "",
            "## Blocking reasons",
            *([f"- {item}" for item in gate_reasons] or ["- none"]),
        ],
    )
    report["artifacts"] = {"json": str(json_path), "markdown": str(markdown_path)}
    return report


def _train_compare(settings, repository, args: argparse.Namespace) -> dict[str, Any]:
    dataset_yaml, dataset_manifest_path = _resolve_dataset_yaml(settings, args.dataset_yaml, args.dataset_manifest)
    train_name = args.train_name or f"site_benchmark_compare_{Path.cwd().name}_{Path.cwd().stat().st_mtime_ns}"
    command = [
        sys.executable,
        "scripts/train_yolo.py",
        "--config",
        str(settings.config_path),
        "--data",
        dataset_yaml,
        "--benchmark-manifest",
        args.benchmark_manifest,
        "--weights",
        args.weights,
        "--name",
        train_name,
        "--epochs",
        str(args.epochs),
        "--batch",
        str(args.batch),
        "--workers",
        str(args.workers),
        "--imgsz",
        str(args.imgsz),
        "--device",
        args.device,
        "--fraction",
        str(args.fraction),
        "--json-output",
    ]
    train_payload = _run_json_command(command)
    model_record = register_model(
        settings,
        model_path=train_payload["best_model"],
        dataset_manifest_path=dataset_manifest_path,
        metrics=train_payload.get("metrics"),
        actor=args.actor,
        note=args.note,
        repository=repository,
        repo_root=REPO_ROOT,
    )
    payload = {
        "generated_at": train_payload.get("generated_at"),
        "dataset_yaml": dataset_yaml,
        "dataset_manifest_path": dataset_manifest_path,
        "train_payload": train_payload,
        "candidate_model_record": model_record,
    }
    _write_json(_quality_dir(settings) / "detector_compare_train.json", payload)
    return payload


def _validate_single(settings, model_path: str, dataset_yaml: str, benchmark_manifest: str, pilot_limit: int, hard_case_types: str, imgsz: int, batch: int, workers: int, device: str, name_prefix: str) -> dict[str, Any]:
    val_payload = _run_json_command(
        [
            sys.executable,
            "scripts/validate_yolo.py",
            "--config",
            str(settings.config_path),
            "--data",
            dataset_yaml,
            "--weights",
            model_path,
            "--imgsz",
            str(imgsz),
            "--batch",
            str(batch),
            "--workers",
            str(workers),
            "--device",
            device,
            "--name",
            f"{name_prefix}_val",
            "--json-output",
        ]
    )
    holdout_payload = _run_json_command_or_placeholder(
        [
            sys.executable,
            "scripts/validate_yolo.py",
            "--config",
            str(settings.config_path),
            "--weights",
            model_path,
            "--benchmark-manifest",
            benchmark_manifest,
            "--eval-split",
            "site_holdout",
            "--imgsz",
            str(imgsz),
            "--batch",
            str(batch),
            "--workers",
            str(workers),
            "--device",
            device,
            "--name",
            f"{name_prefix}_site_holdout",
            "--json-output",
        ],
        fallback_status="review_required",
        fallback_note="Site holdout validation could not run because the benchmark split still lacks labeled samples.",
    )
    pilot_payload = _run_json_command(
        [
            sys.executable,
            "scripts/validate_yolo.py",
            "--config",
            str(settings.config_path),
            "--weights",
            model_path,
            "--imgsz",
            str(imgsz),
            "--batch",
            str(batch),
            "--workers",
            str(workers),
            "--device",
            device,
            "--pilot-video-eval",
            "--pilot-limit",
            str(pilot_limit),
            "--hard-case-types",
            hard_case_types,
            "--name",
            f"{name_prefix}_pilot",
            "--json-output",
        ]
    )
    return {
        "model_path": model_path,
        "val": val_payload,
        "site_holdout": holdout_payload,
        "pilot_video_eval": pilot_payload.get("pilot_video_eval", {}),
    }


def _validate_compare(settings, args: argparse.Namespace) -> dict[str, Any]:
    dataset_yaml, dataset_manifest_path = _resolve_dataset_yaml(settings, args.dataset_yaml, None)
    benchmark_manifest = args.benchmark_manifest
    train_artifact = _resolve_candidate_training_artifact(settings)
    candidate_model = args.candidate_model or ((train_artifact or {}).get("candidate_model_record") or {}).get("model_path")
    if not candidate_model:
        raise ValueError("Candidate model path is required. Run train-compare first or pass --candidate-model.")
    baseline_model = args.baseline_model or _resolve_baseline_model(settings)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_yaml": dataset_yaml,
        "dataset_manifest_path": dataset_manifest_path,
        "benchmark_manifest": benchmark_manifest,
        "baseline": _validate_single(
            settings,
            baseline_model,
            dataset_yaml,
            benchmark_manifest,
            args.pilot_limit,
            args.hard_case_types,
            args.imgsz,
            args.batch,
            args.workers,
            args.device,
            "baseline_compare",
        ),
        "candidate": _validate_single(
            settings,
            candidate_model,
            dataset_yaml,
            benchmark_manifest,
            args.pilot_limit,
            args.hard_case_types,
            args.imgsz,
            args.batch,
            args.workers,
            args.device,
            "candidate_compare",
        ),
    }
    _write_json(_quality_dir(settings) / "detector_compare_validation.json", payload)
    _write_json(
        _quality_dir(settings) / "pilot_video_eval.json",
        {
            "generated_at": payload["generated_at"],
            "status": payload["candidate"].get("pilot_video_eval", {}).get("status", "review_required"),
            "evaluation_mode": "compare_candidate_replay",
            "baseline_model": baseline_model,
            "candidate_model": candidate_model,
            **payload["candidate"].get("pilot_video_eval", {}),
        },
    )
    return payload


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    repository = build_repository(settings)

    if args.command == "export-feedback":
        selected_types = tuple(item.strip() for item in args.case_types.split(",") if item.strip()) or None
        _emit_json(export_feedback_cases(settings, repository, limit=args.limit, case_types=selected_types, actor=args.actor, note=args.note))
        return
    if args.command == "build-dataset":
        _emit_json(
            build_feedback_dataset(
                settings,
                base_dataset_yaml=args.base_data,
                source_export_manifest_path=args.source_export_manifest,
                site_benchmark_manifest_path=args.site_benchmark_manifest,
                actor=args.actor,
                note=args.note,
                repository=repository,
            )
        )
        return
    if args.command == "register-model":
        _emit_json(register_model(settings, model_path=args.model_path, dataset_manifest_path=args.dataset_manifest, actor=args.actor, note=args.note, repository=repository))
        return
    if args.command == "promote-model":
        _emit_json(promote_model(settings, model_id=args.model_id, model_path=args.model_path, actor=args.actor, note=args.note, repository=repository))
        return
    if args.command == "train-compare":
        _emit_json(_train_compare(settings, repository, args))
        return
    if args.command == "validate-compare":
        _emit_json(_validate_compare(settings, args))
        return
    if args.command == "compare-report":
        validation_artifact = Path(args.validation_artifact) if args.validation_artifact else _quality_dir(settings) / "detector_compare_validation.json"
        validation_payload = json.loads(validation_artifact.read_text(encoding="utf-8"))
        report = _write_compare_report(settings, validation_payload, args.actor, args.note)
        quality_summary = _refresh_quality_summary(settings, repository)
        quality_summary["latest_compare_report"] = {
            "path": str(report["artifacts"]["json"]),
            "conclusion": report["conclusion"],
            "block_reasons": report["block_reasons"],
        }
        _emit_json({"compare_report": report, "quality_summary": quality_summary})
        return

    export_record = export_feedback_cases(settings, repository, limit=args.limit, actor=args.actor, note=args.note)
    dataset_record = build_feedback_dataset(
        settings,
        base_dataset_yaml=args.base_data,
        source_export_manifest_path=export_record.get("feedback_cases_manifest_path"),
        site_benchmark_manifest_path="artifacts/reports/quality/site_benchmark_manifest.json",
        actor=args.actor,
        note=args.note,
        repository=repository,
    )
    response: dict[str, object] = {"export": export_record, "dataset": dataset_record}
    if args.train:
        train_payload = _train_compare(
            settings,
            repository,
            argparse.Namespace(
                dataset_yaml=dataset_record["dataset_yaml"],
                dataset_manifest=dataset_record["manifest_path"],
                benchmark_manifest="artifacts/reports/quality/site_benchmark_manifest.json",
                weights="artifacts/training_runs/helmet_project/yolo26n_cpu_v2_voxel_ft/weights/best.pt",
                epochs=args.epochs,
                batch=8,
                workers=2,
                imgsz=640,
                device="cpu",
                fraction=args.fraction,
                train_name=args.train_name,
                actor=args.actor,
                note=args.note,
            ),
        )
        response["train_compare"] = train_payload
        validation_payload = _validate_compare(
            settings,
            argparse.Namespace(
                candidate_model=train_payload["candidate_model_record"]["model_path"],
                baseline_model=None,
                dataset_yaml=dataset_record["dataset_yaml"],
                benchmark_manifest="artifacts/reports/quality/site_benchmark_manifest.json",
                pilot_limit=args.pilot_limit,
                hard_case_types="false_positive,missed_detection,night,backlight,crowd,occlusion",
                imgsz=640,
                batch=8,
                workers=2,
                device="cpu",
                actor=args.actor,
                note=args.note,
            ),
        )
        response["validation_compare"] = validation_payload
        report = _write_compare_report(settings, validation_payload, args.actor, args.note)
        response["compare_report"] = report
        if args.promote and report["conclusion"] == "promote":
            response["promotion"] = promote_model(
                settings,
                model_path=train_payload["candidate_model_record"]["model_path"],
                actor=args.actor,
                note=args.note,
                repository=repository,
            )
        elif args.promote:
            response["promotion"] = {
                "status": "blocked",
                "reason": report["block_reasons"],
            }
    quality_summary = _refresh_quality_summary(settings, repository)
    if "compare_report" in response:
        quality_summary["latest_compare_report"] = {
            "path": response["compare_report"]["artifacts"]["json"],
            "conclusion": response["compare_report"]["conclusion"],
            "block_reasons": response["compare_report"]["block_reasons"],
        }
    response["quality_summary"] = quality_summary
    _emit_json(response)


if __name__ == "__main__":
    main()
