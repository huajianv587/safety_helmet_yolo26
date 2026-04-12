from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from helmet_monitoring.core.config import load_settings
from scripts import closed_loop_smoke, trigger_test_alert


def _build_settings():
    runtime_payload = {
        "repository_backend": "supabase",
        "model": {"path": "artifacts/models/example.pt"},
        "persistence": {
            "runtime_dir": "artifacts/runtime",
            "snapshot_dir": "artifacts/captures",
            "upload_to_supabase_storage": True,
            "keep_local_copy": False,
        },
        "cameras": [
            {
                "camera_id": "cam-local-001",
                "camera_name": "Laptop Camera",
                "source": "0",
                "enabled": True,
                "location": "Local Workstation",
                "department": "Safety",
            }
        ],
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "runtime.json"
        config_path.write_text(json.dumps(runtime_payload, ensure_ascii=False), encoding="utf-8")
        with patch("helmet_monitoring.core.config._load_env_files", return_value=None), patch.dict(os.environ, {}, clear=True):
            return load_settings(config_path)


class TriggerTestAlertScriptTest(unittest.TestCase):
    def test_main_uses_local_profile_by_default(self) -> None:
        settings = _build_settings()
        args = Namespace(config="runtime.json", strict_runtime=False, person_id="person-001", image="", camera_id="")

        with (
            patch.object(trigger_test_alert, "parse_args", return_value=args),
            patch.object(trigger_test_alert, "load_settings", return_value=settings),
            patch.object(trigger_test_alert, "build_repository", side_effect=RuntimeError("stop")) as build_repository_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                trigger_test_alert.main()

        effective_settings = build_repository_mock.call_args.args[0]
        self.assertEqual(effective_settings.repository_backend, "local")
        self.assertFalse(effective_settings.persistence.upload_to_supabase_storage)
        self.assertTrue(effective_settings.persistence.keep_local_copy)
        self.assertFalse(build_repository_mock.call_args.kwargs["require_requested_backend"])

    def test_main_preserves_requested_backend_in_strict_mode(self) -> None:
        settings = _build_settings()
        args = Namespace(config="runtime.json", strict_runtime=True, person_id="person-001", image="", camera_id="")

        with (
            patch.object(trigger_test_alert, "parse_args", return_value=args),
            patch.object(trigger_test_alert, "load_settings", return_value=settings),
            patch.object(trigger_test_alert, "build_repository", side_effect=RuntimeError("stop")) as build_repository_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                trigger_test_alert.main()

        effective_settings = build_repository_mock.call_args.args[0]
        self.assertEqual(effective_settings.repository_backend, "supabase")
        self.assertTrue(effective_settings.persistence.upload_to_supabase_storage)
        self.assertTrue(build_repository_mock.call_args.kwargs["require_requested_backend"])


class ClosedLoopSmokeScriptTest(unittest.TestCase):
    def test_main_uses_local_profile_by_default(self) -> None:
        settings = _build_settings()
        args = Namespace(
            config="runtime.json",
            strict_runtime=False,
            person_id="person-001",
            camera_id="",
            actor="ops.closed_loop_smoke",
            assignee="ops.lead",
            assignee_email="ops@example.com",
            note="closed loop smoke",
            build_feedback_dataset=False,
        )

        with (
            patch.object(closed_loop_smoke, "parse_args", return_value=args),
            patch.object(closed_loop_smoke, "load_settings", return_value=settings),
            patch.object(closed_loop_smoke, "build_repository", side_effect=RuntimeError("stop")) as build_repository_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                closed_loop_smoke.main()

        effective_settings = build_repository_mock.call_args.args[0]
        self.assertEqual(effective_settings.repository_backend, "local")
        self.assertFalse(effective_settings.persistence.upload_to_supabase_storage)
        self.assertFalse(build_repository_mock.call_args.kwargs["require_requested_backend"])

    def test_trigger_subprocess_forwards_strict_runtime_flag(self) -> None:
        args = Namespace(config="runtime.json", strict_runtime=True, person_id="person-001", camera_id="cam-local-001")
        completed = Mock(stdout="event_no=TST-001\n", returncode=0)

        with patch.object(closed_loop_smoke.subprocess, "run", return_value=completed) as run_mock:
            closed_loop_smoke._trigger_test_alert(args)

        command = run_mock.call_args.args[0]
        self.assertIn("--strict-runtime", command)
        self.assertIn("--camera-id", command)
        self.assertIn("cam-local-001", command)


if __name__ == "__main__":
    unittest.main()
