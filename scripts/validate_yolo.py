from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.model_governance import build_benchmark_dataset_bundle, feedback_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a YOLO detector with dataset YAML, benchmark manifest, and pilot replay.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--data", default="configs/datasets/shwd_yolo26.yaml", help="Dataset YAML path.")
    parser.add_argument("--benchmark-manifest", default="", help="Optional benchmark manifest path.")
    parser.add_argument("--eval-split", default="val", choices=["val", "site_holdout"], help="Benchmark split to validate.")
    parser.add_argument("--generated-data-root", default="", help="Where to write generated benchmark validation files.")
    parser.add_argument("--weights", default="artifacts/models/yolov8n.pt", help="Trained YOLO weights.")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size.")
    parser.add_argument("--batch", type=int, default=16, help="Batch size.")
    parser.add_argument("--device", default="", help="Device, for example cpu, 0, or 0,1.")
    parser.add_argument("--workers", type=int, default=4, help="Dataloader workers.")
    parser.add_argument("--project", default="artifacts/validation_runs", help="Validation output directory.")
    parser.add_argument("--name", default="val_product", help="Run name.")
    parser.add_argument("--pilot-video-eval", action="store_true", help="Run pilot replay on hard-case snapshots and clips.")
    parser.add_argument("--pilot-limit", type=int, default=60, help="Maximum hard-case samples for pilot replay.")
    parser.add_argument(
        "--hard-case-types",
        default="false_positive,missed_detection,night,backlight,crowd,occlusion",
        help="Comma-separated hard-case categories to include in pilot replay.",
    )
    parser.add_argument("--json-output", action="store_true", help="Print structured JSON output.")
    return parser.parse_args()


def _resolve_path(settings, value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate)
    resolved = settings.resolve_path(value)
    if resolved.exists():
        return str(resolved)
    return value


def _scene_tags_from_values(*values: Any) -> list[str]:
    tags: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value).lower()
        if "night" in text or "night_shift" in text:
            tags.add("night")
        if "backlight" in text or "back light" in text:
            tags.add("backlight")
        if "crowd" in text or "dense" in text:
            tags.add("crowd")
        if "occlusion" in text or "blocked" in text:
            tags.add("occlusion")
    return sorted(tags)


def _sample_clip_frames(clip_path: Path, *, max_frames: int = 8) -> list[Any]:
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("OpenCV is required for pilot video replay.") from exc

    capture = cv2.VideoCapture(str(clip_path))
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count <= 0:
            ok, frame = capture.read()
            return [frame] if ok and frame is not None else []
        target_count = max(1, min(int(max_frames), frame_count))
        indices = sorted({int(round(index * (frame_count - 1) / max(target_count - 1, 1))) for index in range(target_count)})
        frames: list[Any] = []
        for frame_index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if ok and frame is not None:
                frames.append(frame)
        return frames
    finally:
        capture.release()


def _load_case_frames(case_manifest: dict[str, Any], *, max_clip_frames: int = 8) -> tuple[list[Any], str | None]:
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("OpenCV is required for pilot video replay.") from exc

    for key in ("local_snapshot_path", "snapshot_path", "source_snapshot_path"):
        path_value = case_manifest.get(key)
        if not path_value:
            continue
        image_path = Path(path_value)
        if not image_path.is_absolute():
            image_path = (REPO_ROOT / image_path).resolve()
        if image_path.exists():
            frame = cv2.imread(str(image_path))
            if frame is not None:
                return [frame], str(image_path)
    for key in ("local_clip_path", "clip_path", "source_clip_path"):
        path_value = case_manifest.get(key)
        if not path_value:
            continue
        clip_path = Path(path_value)
        if not clip_path.is_absolute():
            clip_path = (REPO_ROOT / clip_path).resolve()
        if not clip_path.exists():
            continue
        frames = _sample_clip_frames(clip_path, max_frames=max_clip_frames)
        if frames:
            return frames, str(clip_path)
    return [], None


def _predict_violation(model, frame, *, conf: float, imgsz: int, device: str) -> tuple[bool, float | None, list[str], float]:
    started = time.perf_counter()
    results = model.predict(frame, conf=conf, imgsz=imgsz, device=device, verbose=False)
    latency_ms = (time.perf_counter() - started) * 1000.0
    names = model.names if hasattr(model, "names") else {}
    labels: list[str] = []
    top_confidence: float | None = None
    predicted_violation = False
    for result in results:
        boxes = getattr(result, "boxes", None)
        if boxes is None or boxes.cls is None:
            continue
        classes = boxes.cls.tolist()
        confidences = boxes.conf.tolist() if getattr(boxes, "conf", None) is not None else []
        for index, class_id in enumerate(classes):
            label = str(names.get(int(class_id), class_id))
            labels.append(label)
            confidence = float(confidences[index]) if index < len(confidences) else None
            if confidence is not None and (top_confidence is None or confidence > top_confidence):
                top_confidence = confidence
            if label == "no_helmet":
                predicted_violation = True
    return predicted_violation, top_confidence, labels, round(latency_ms, 3)


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return round(float(ordered[index]), 3)


def _temporal_stability(frame_hits: list[bool]) -> float | None:
    if len(frame_hits) <= 1:
        return 1.0 if frame_hits else None
    transitions = sum(1 for index in range(1, len(frame_hits)) if frame_hits[index] != frame_hits[index - 1])
    return round(1.0 - (transitions / float(len(frame_hits) - 1)), 4)


def _run_pilot_video_eval(settings, model, args: argparse.Namespace) -> dict[str, Any]:
    root_paths = feedback_paths(settings, repo_root=REPO_ROOT)
    selected_types = {item.strip() for item in str(args.hard_case_types or "").split(",") if item.strip()}
    case_manifests: list[tuple[str, Path, dict[str, Any]]] = []

    directory_map = {
        "false_positive": root_paths["false_positive_dir"],
        "missed_detection": root_paths["missed_detection_dir"],
        "night": root_paths["night_shift_dir"],
        "backlight": root_paths["backlight_dir"],
        "crowd": root_paths["crowd_dir"],
        "occlusion": root_paths["occlusion_dir"],
    }
    for case_type in selected_types:
        case_root = directory_map.get(case_type)
        if case_root is None or not case_root.exists():
            continue
        for manifest_path in sorted(case_root.glob("*/case_manifest.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            case_manifests.append((case_type, manifest_path, payload))

    samples: list[dict[str, Any]] = []
    scene_stats = {tag: {"samples": 0, "failures": 0} for tag in ("night", "backlight", "crowd", "occlusion")}
    false_positive = 0
    missed_detection = 0
    latency_values: list[float] = []
    stability_values: list[float] = []
    expected_violation_total = 0
    expected_violation_hits = 0
    sampled = 0

    for case_type, manifest_path, payload in case_manifests[: args.pilot_limit]:
        frames, source_path = _load_case_frames(payload, max_clip_frames=8)
        if not frames:
            continue
        frame_results = [
            _predict_violation(
                model,
                frame,
                conf=float(settings.model.confidence),
                imgsz=args.imgsz,
                device=args.device or settings.model.device,
            )
            for frame in frames
        ]
        frame_hits = [item[0] for item in frame_results]
        predicted_violation = any(frame_hits)
        top_confidence = max((item[1] for item in frame_results if item[1] is not None), default=None)
        labels = sorted({label for item in frame_results for label in item[2]})
        case_latency_values = [item[3] for item in frame_results]
        latency_values.extend(case_latency_values)
        stability = _temporal_stability(frame_hits)
        if stability is not None:
            stability_values.append(stability)
        scene_tags = sorted(set(_scene_tags_from_values(case_type, payload.get("note"), manifest_path.parent.name)))
        expected_violation = case_type != "false_positive"
        failed = False
        if expected_violation:
            expected_violation_total += 1
            if predicted_violation:
                expected_violation_hits += 1
        if case_type == "false_positive" and predicted_violation:
            false_positive += 1
            failed = True
        if case_type == "missed_detection" and not predicted_violation:
            missed_detection += 1
            failed = True
        for tag in scene_tags:
            if tag in scene_stats:
                scene_stats[tag]["samples"] += 1
                if failed:
                    scene_stats[tag]["failures"] += 1
        samples.append(
            {
                "case_type": case_type,
                "expected_violation": expected_violation,
                "predicted_violation": predicted_violation,
                "top_confidence": top_confidence,
                "labels": labels,
                "frame_count": len(frames),
                "latency_ms": round(sum(case_latency_values) / len(case_latency_values), 3) if case_latency_values else None,
                "mean_latency_ms": round(sum(case_latency_values) / len(case_latency_values), 3) if case_latency_values else None,
                "p95_latency_ms": _percentile(case_latency_values, 0.95),
                "temporal_stability": stability,
                "scene_tags": scene_tags,
                "source_path": source_path,
            }
        )
        sampled += 1

    notes: list[str] = []
    status = "ready"
    if sampled < max(5, int(settings.quality.pilot_replay_min_samples)):
        status = "review_required"
        notes.append("Pilot replay still has too few sampled hard-case frames for a promotion decision.")
    if not any(item["case_type"] == "missed_detection" for item in samples):
        status = "review_required"
        notes.append("Pilot replay still lacks missed-detection samples, so recall cannot be signed off yet.")
    mean_latency_ms = round(sum(latency_values) / len(latency_values), 3) if latency_values else None
    p95_latency_ms = _percentile(latency_values, 0.95)
    clip_hit_rate = round(expected_violation_hits / expected_violation_total, 4) if expected_violation_total else None
    temporal_stability = round(sum(stability_values) / len(stability_values), 4) if stability_values else None
    if mean_latency_ms is None or p95_latency_ms is None:
        status = "review_required"
        notes.append("Pilot replay still lacks latency samples.")
    else:
        if mean_latency_ms > float(settings.quality.mean_latency_ms_threshold):
            status = "review_required"
            notes.append("Pilot replay mean latency is above the configured gate.")
        if p95_latency_ms > float(settings.quality.p95_latency_ms_threshold):
            status = "review_required"
            notes.append("Pilot replay p95 latency is above the configured gate.")

    return {
        "status": status,
        "evaluation_mode": "hard_case_replay",
        "sampled_cases": sampled,
        "sampled_clips": sampled,
        "false_positive": false_positive,
        "missed_detection": missed_detection,
        "mean_latency_ms": mean_latency_ms,
        "average_latency_ms": mean_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "clip_hit_rate": clip_hit_rate,
        "temporal_stability": temporal_stability,
        "case_types": sorted(selected_types),
        "scene_results": scene_stats,
        "notes": notes,
        "samples": samples,
    }


def _emit_json(payload: dict[str, Any]) -> None:
    message = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    sys.stdout.buffer.write(message.encode("utf-8", errors="replace"))
    sys.stdout.flush()


def run_validation(args: argparse.Namespace) -> dict[str, Any]:
    settings = load_settings(args.config)
    runtime_root = Path(args.config).resolve().parents[1]

    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Ultralytics is not installed. Use the project .venv or install requirements.txt.") from exc

    project_path = settings.resolve_path(args.project)
    project_path.mkdir(parents=True, exist_ok=True)
    manifest_summary: dict[str, Any] | None = None
    data_path = _resolve_path(settings, args.data)
    if args.benchmark_manifest:
        generated_root = (
            settings.resolve_path(args.generated_data_root)
            if args.generated_data_root
            else project_path / args.name / f"benchmark_{args.eval_split}"
        )
        manifest_summary = build_benchmark_dataset_bundle(
            settings,
            benchmark_manifest_path=args.benchmark_manifest,
            output_dir=generated_root,
            train_splits=[],
            val_splits=[args.eval_split],
            repo_root=runtime_root,
        )
        if manifest_summary.get("val_count", 0) == 0:
            raise RuntimeError(f"Benchmark split '{args.eval_split}' does not contain labeled samples to validate.")
        data_path = manifest_summary["dataset_yaml"]

    weights_path = _resolve_path(settings, args.weights)
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
        verbose=False,
    )

    box = results.box
    payload: dict[str, Any] = {
        "save_dir": str(results.save_dir),
        "weights_path": str(weights_path),
        "data_path": str(data_path),
        "eval_split": args.eval_split,
        "metrics": {
            "precision": round(float(box.mp), 5),
            "recall": round(float(box.mr), 5),
            "map50": round(float(box.map50), 5),
            "map50_95": round(float(box.map), 5),
        },
    }
    precision = payload["metrics"]["precision"]
    recall = payload["metrics"]["recall"]
    if precision + recall > 0:
        payload["metrics"]["f1"] = round(2 * precision * recall / (precision + recall), 5)
    if manifest_summary:
        payload["benchmark_dataset"] = manifest_summary
    if args.pilot_video_eval:
        payload["pilot_video_eval"] = _run_pilot_video_eval(settings, model, args)
    return payload


def main() -> None:
    args = parse_args()
    payload = run_validation(args)
    if args.json_output:
        _emit_json(payload)
        return
    print(f"save_dir={payload['save_dir']}")
    print(f"precision={payload['metrics']['precision']:.5f}")
    print(f"recall={payload['metrics']['recall']:.5f}")
    print(f"map50={payload['metrics']['map50']:.5f}")
    print(f"map50_95={payload['metrics']['map50_95']:.5f}")
    if "f1" in payload["metrics"]:
        print(f"f1={payload['metrics']['f1']:.5f}")
    if payload.get("benchmark_dataset"):
        print(f"benchmark_dataset={payload['benchmark_dataset']['manifest_path']}")
    if payload.get("pilot_video_eval"):
        print(f"pilot_video_eval={json.dumps(payload['pilot_video_eval'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
