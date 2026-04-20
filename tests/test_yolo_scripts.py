from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import train_yolo, validate_yolo


def _write_runtime(root: Path) -> Path:
    runtime = {
        "repository_backend": "local",
        "model": {"path": "models/best.pt", "device": "cpu", "confidence": 0.52},
        "event_rules": {"min_confidence_for_alert": 0.58},
        "persistence": {"runtime_dir": str(root / "artifacts" / "runtime"), "snapshot_dir": str(root / "artifacts" / "captures")},
        "ocr": {"enabled": False, "provider": "none", "min_confidence": 0.55},
        "face_recognition": {"enabled": False, "provider": "facenet_pytorch", "similarity_threshold": 0.72, "review_threshold": 0.58},
        "notifications": {"enabled": False, "email_enabled": False},
        "cameras": [],
    }
    config_path = root / "configs" / "runtime.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path


def _write_dataset_and_manifest(root: Path) -> tuple[Path, Path]:
    dataset_root = root / "data" / "helmet_detection_dataset"
    for split in ("train", "val"):
        (dataset_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (dataset_root / "labels" / split).mkdir(parents=True, exist_ok=True)
    (dataset_root / "images" / "train" / "train_a.jpg").write_text("train", encoding="utf-8")
    (dataset_root / "labels" / "train" / "train_a.txt").write_text("1 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    (dataset_root / "images" / "val" / "val_a.jpg").write_text("val", encoding="utf-8")
    (dataset_root / "labels" / "val" / "val_a.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    dataset_yaml = root / "configs" / "datasets" / "shwd_yolo26.yaml"
    dataset_yaml.parent.mkdir(parents=True, exist_ok=True)
    dataset_yaml.write_text(
        "path: data/helmet_detection_dataset\ntrain: images/train\nval: images/val\nnames:\n  0: helmet\n  1: no_helmet\n",
        encoding="utf-8",
    )
    quality_dir = root / "artifacts" / "reports" / "quality"
    quality_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = quality_dir / "site_benchmark_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {"total": 2, "splits": {"train": 1, "val": 1, "site_holdout": 1}},
                "items": [
                    {"id": "train", "split": "train", "snapshot_path": "data/helmet_detection_dataset/images/train/train_a.jpg", "scene_tags": []},
                    {"id": "val", "split": "val", "snapshot_path": "data/helmet_detection_dataset/images/val/val_a.jpg", "scene_tags": ["night"]},
                    {"id": "holdout", "split": "site_holdout", "snapshot_path": "data/helmet_detection_dataset/images/val/val_a.jpg", "scene_tags": ["night"]},
                ],
                "rules": {"allowed_labels": ["helmet", "no_helmet"], "split_unit": "camera_id + date"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return dataset_yaml, manifest_path


class _FakeTrainResult:
    def __init__(self, save_dir: Path) -> None:
        self.save_dir = str(save_dir)


class _FakeBox:
    mp = 0.81
    mr = 0.72
    map50 = 0.77
    map = 0.43


class _FakeValResult:
    def __init__(self, save_dir: Path) -> None:
        self.save_dir = str(save_dir)
        self.box = _FakeBox()


class _FakeYOLO:
    def __init__(self, weights_path: str) -> None:
        self.weights_path = weights_path
        self.names = {0: "helmet", 1: "no_helmet"}

    def train(self, **kwargs):
        save_dir = Path(kwargs["project"]) / kwargs["name"]
        (save_dir / "weights").mkdir(parents=True, exist_ok=True)
        (save_dir / "weights" / "best.pt").write_text("weights", encoding="utf-8")
        (save_dir / "results.csv").write_text(
            "epoch,metrics/precision(B),metrics/recall(B),metrics/mAP50(B),metrics/mAP50-95(B)\n"
            "1,0.80000,0.70000,0.76000,0.43000\n",
            encoding="utf-8",
        )
        return _FakeTrainResult(save_dir)

    def val(self, **kwargs):
        save_dir = Path(kwargs["project"]) / kwargs["name"]
        save_dir.mkdir(parents=True, exist_ok=True)
        return _FakeValResult(save_dir)


class YoloScriptManifestTest(unittest.TestCase):
    def test_train_script_prefers_benchmark_manifest_over_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = _write_runtime(root)
            _, manifest_path = _write_dataset_and_manifest(root)
            weights_path = root / "models" / "baseline.pt"
            weights_path.parent.mkdir(parents=True, exist_ok=True)
            weights_path.write_text("baseline", encoding="utf-8")
            args = Namespace(
                config=str(config_path),
                data="configs/datasets/does-not-exist.yaml",
                benchmark_manifest=str(manifest_path),
                manifest_splits="train,val",
                generated_data_root=str(root / "artifacts" / "generated_train"),
                weights=str(weights_path),
                project=str(root / "artifacts" / "training"),
                name="bench-train",
                epochs=1,
                imgsz=640,
                batch=2,
                device="cpu",
                workers=0,
                patience=1,
                fraction=1.0,
                export_onnx=False,
                json_output=True,
            )
            with patch.dict(sys.modules, {"ultralytics": types.SimpleNamespace(YOLO=_FakeYOLO)}):
                payload = train_yolo.run_training(args)
            self.assertIn("benchmark_dataset", payload)
            self.assertTrue(payload["data_path"].endswith("benchmark_dataset.yaml"))
            self.assertEqual(payload["benchmark_dataset"]["train_count"], 1)
            self.assertEqual(payload["benchmark_dataset"]["val_count"], 1)

    def test_validate_script_can_target_site_holdout_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = _write_runtime(root)
            dataset_yaml, manifest_path = _write_dataset_and_manifest(root)
            weights_path = root / "models" / "baseline.pt"
            weights_path.parent.mkdir(parents=True, exist_ok=True)
            weights_path.write_text("baseline", encoding="utf-8")
            args = Namespace(
                config=str(config_path),
                data=str(dataset_yaml),
                benchmark_manifest=str(manifest_path),
                eval_split="site_holdout",
                generated_data_root=str(root / "artifacts" / "generated_val"),
                weights=str(weights_path),
                imgsz=640,
                batch=2,
                device="cpu",
                workers=0,
                project=str(root / "artifacts" / "validation"),
                name="holdout-val",
                pilot_video_eval=False,
                pilot_limit=10,
                hard_case_types="false_positive,missed_detection",
                json_output=True,
            )
            with patch.dict(sys.modules, {"ultralytics": types.SimpleNamespace(YOLO=_FakeYOLO)}):
                payload = validate_yolo.run_validation(args)
            self.assertIn("benchmark_dataset", payload)
            self.assertEqual(payload["eval_split"], "site_holdout")
            self.assertEqual(payload["benchmark_dataset"]["val_count"], 1)
            self.assertAlmostEqual(payload["metrics"]["precision"], 0.81, places=2)


if __name__ == "__main__":
    unittest.main()
