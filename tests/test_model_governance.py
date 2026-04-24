from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import (
    AppSettings,
    ClipSettings,
    EventRuleSettings,
    FaceRecognitionSettings,
    GovernanceSettings,
    IdentitySettings,
    LlmFallbackSettings,
    ModelSettings,
    MonitoringSettings,
    NotificationSettings,
    OcrSettings,
    PersistenceSettings,
    SecuritySettings,
    SupabaseSettings,
    TrackingSettings,
)
from helmet_monitoring.services.model_governance import (
    build_benchmark_dataset_bundle,
    build_feedback_dataset,
    export_feedback_cases,
    promote_model,
    register_model,
)
from helmet_monitoring.storage.repository import LocalAlertRepository


def build_settings(root: Path) -> AppSettings:
    config_path = root / "configs" / "runtime.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"model": {"path": "models/model-a.pt"}}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "configs" / "person_registry.json").write_text("[]\n", encoding="utf-8")
    base_dataset = root / "data" / "helmet_detection_dataset"
    (base_dataset / "images" / "train").mkdir(parents=True, exist_ok=True)
    (base_dataset / "images" / "val").mkdir(parents=True, exist_ok=True)
    (base_dataset / "labels" / "train").mkdir(parents=True, exist_ok=True)
    (base_dataset / "labels" / "val").mkdir(parents=True, exist_ok=True)
    (base_dataset / "images" / "train" / "base_train.jpg").write_text("train", encoding="utf-8")
    (base_dataset / "images" / "val" / "base_val.jpg").write_text("val", encoding="utf-8")
    (base_dataset / "labels" / "train" / "base_train.txt").write_text("1 0.5 0.5 0.3 0.3\n", encoding="utf-8")
    (base_dataset / "labels" / "val" / "base_val.txt").write_text("0 0.5 0.5 0.3 0.3\n", encoding="utf-8")
    dataset_yaml = root / "configs" / "datasets" / "shwd_yolo26.yaml"
    dataset_yaml.parent.mkdir(parents=True, exist_ok=True)
    dataset_yaml.write_text(
        "path: data/helmet_detection_dataset\ntrain: images/train\nval: images/val\nnames:\n  0: helmet\n  1: no_helmet\n",
        encoding="utf-8",
    )
    (root / "data" / "hard_cases" / "labeled" / "images" / "train").mkdir(parents=True, exist_ok=True)
    (root / "data" / "hard_cases" / "labeled" / "labels" / "train").mkdir(parents=True, exist_ok=True)
    (root / "data" / "hard_cases" / "labeled" / "images" / "train" / "feedback_train.jpg").write_text("feedback", encoding="utf-8")
    (root / "data" / "hard_cases" / "labeled" / "labels" / "train" / "feedback_train.txt").write_text("1 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    quality_dir = root / "artifacts" / "reports" / "quality"
    quality_dir.mkdir(parents=True, exist_ok=True)
    (quality_dir / "site_benchmark_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {"total": 2, "splits": {"train": 1, "val": 1, "site_holdout": 0}},
                "items": [
                    {
                        "id": "train-item",
                        "split": "train",
                        "snapshot_path": "data/helmet_detection_dataset/images/train/base_train.jpg",
                        "scene_tags": ["night"],
                    },
                    {
                        "id": "val-item",
                        "split": "val",
                        "snapshot_path": "data/helmet_detection_dataset/images/val/base_val.jpg",
                        "scene_tags": ["backlight"],
                    },
                ],
                "rules": {"allowed_labels": ["helmet", "no_helmet"], "split_unit": "camera_id + date"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "models" / "model-a.pt").write_text("baseline-model", encoding="utf-8")
    (root / "models" / "model-candidate.pt").write_text("candidate-model", encoding="utf-8")
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="models/model-a.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(
            snapshot_dir=str(root / "artifacts" / "captures"),
            runtime_dir=str(root / "artifacts" / "runtime"),
            upload_to_supabase_storage=False,
        ),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(registry_path=str(root / "configs" / "person_registry.json")),
        face_recognition=FaceRecognitionSettings(enabled=False, face_profile_dir=str(root / "artifacts" / "identity" / "faces")),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(),
        notifications=NotificationSettings(enabled=False, email_enabled=False),
        security=SecuritySettings(),
        supabase=SupabaseSettings(),
        cameras=(),
        config_path=config_path,
    )


class ModelGovernanceTest(unittest.TestCase):
    def test_export_feedback_cases_copies_hard_case_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            runtime_dir = root / "artifacts" / "runtime"
            repo = LocalAlertRepository(runtime_dir)
            snapshot_path = root / "artifacts" / "captures" / "alert-1.jpg"
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text("snapshot", encoding="utf-8")
            repo.insert_alert(
                {
                    "alert_id": "alert-1",
                    "event_no": "AL-1",
                    "snapshot_path": str(snapshot_path),
                    "clip_path": None,
                    "created_at": "2026-04-04T00:00:00+00:00",
                }
            )
            repo.insert_hard_case(
                {
                    "case_id": "case-1",
                    "alert_id": "alert-1",
                    "event_no": "AL-1",
                    "case_type": "false_positive",
                    "snapshot_path": str(snapshot_path),
                    "clip_path": None,
                    "note": "bad angle",
                    "created_at": "2026-04-04T00:01:00+00:00",
                }
            )

            manifest = export_feedback_cases(settings, repo, repo_root=root)
            self.assertEqual(manifest["case_count"], 1)
            export_case = Path(manifest["export_dir"]) / "alert-1" / "export_case.json"
            self.assertTrue(export_case.exists())
            self.assertTrue(Path(manifest["feedback_cases_manifest_path"]).exists())
            self.assertEqual(manifest["label_breakdown"]["helmet"], 1)
            repo.close()

    def test_build_feedback_dataset_writes_merged_lists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            runtime_dir = root / "artifacts" / "runtime"
            repo = LocalAlertRepository(runtime_dir)
            snapshot_path = root / "artifacts" / "captures" / "alert-1.jpg"
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text("snapshot", encoding="utf-8")
            repo.insert_alert(
                {
                    "alert_id": "alert-1",
                    "event_no": "AL-1",
                    "snapshot_path": str(snapshot_path),
                    "clip_path": None,
                    "created_at": "2026-04-04T00:00:00+00:00",
                }
            )
            repo.insert_hard_case(
                {
                    "case_id": "case-1",
                    "alert_id": "alert-1",
                    "event_no": "AL-1",
                    "case_type": "false_positive",
                    "snapshot_path": str(snapshot_path),
                    "clip_path": None,
                    "note": "night backlight",
                    "created_at": "2026-04-04T00:01:00+00:00",
                }
            )
            export_record = export_feedback_cases(settings, repo, repo_root=root)
            manifest = build_feedback_dataset(
                settings,
                base_dataset_yaml="configs/datasets/shwd_yolo26.yaml",
                repo_root=root,
                source_export_manifest_path=export_record["feedback_cases_manifest_path"],
                site_benchmark_manifest_path="artifacts/reports/quality/site_benchmark_manifest.json",
            )
            train_list = Path(manifest["dataset_yaml"]).with_name("train.txt").read_text(encoding="utf-8")
            self.assertIn("base_train.jpg", train_list)
            self.assertIn("feedback_train.jpg", train_list)
            self.assertTrue(manifest["feedback_labeled_ready"])
            self.assertEqual(manifest["site_benchmark_manifest"]["status"], "ready")
            self.assertEqual(manifest["hard_case_manifest"]["case_type_breakdown"]["false_positive"], 1)
            self.assertIn("night", manifest["scene_breakdown"])
            self.assertEqual(set(manifest["allowed_labels"]), {"helmet", "no_helmet"})
            repo.close()

    def test_build_benchmark_dataset_bundle_respects_manifest_splits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            bundle = build_benchmark_dataset_bundle(
                settings,
                benchmark_manifest_path="artifacts/reports/quality/site_benchmark_manifest.json",
                output_dir="artifacts/generated/benchmark_bundle",
                train_splits=["train"],
                val_splits=["val"],
                repo_root=root,
            )
            self.assertTrue(bundle["training_ready"])
            self.assertEqual(bundle["train_count"], 1)
            self.assertEqual(bundle["val_count"], 1)
            self.assertEqual(bundle["label_breakdown"]["helmet"], 1)
            self.assertEqual(bundle["label_breakdown"]["no_helmet"], 1)
            self.assertTrue(Path(bundle["dataset_yaml"]).exists())

    def test_register_and_promote_model_updates_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = build_settings(root)
            record = register_model(settings, model_path="models/model-candidate.pt", repo_root=root)
            promotion = promote_model(settings, model_id=record["model_id"], repo_root=root)
            current_config = json.loads(settings.config_path.read_text(encoding="utf-8"))
            self.assertEqual(current_config["model"]["path"], "models/model-candidate.pt")
            self.assertEqual(promotion["model_id"], record["model_id"])


if __name__ == "__main__":
    unittest.main()
