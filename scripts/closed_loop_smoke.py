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
from helmet_monitoring.services.model_governance import build_feedback_dataset, export_feedback_cases
from helmet_monitoring.services.runtime_profiles import local_smoke_settings
from helmet_monitoring.services.workflow import AlertWorkflowService
from helmet_monitoring.storage.repository import build_repository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an end-to-end smoke: inject test alerts, close one operationally, route one into model feedback."
    )
    parser.add_argument("--config", default=None, help="Optional runtime config path.")
    parser.add_argument(
        "--strict-runtime",
        action="store_true",
        help="Use the configured backend and storage instead of the local-only test profile.",
    )
    parser.add_argument("--person-id", default="person-001", help="Registered person used by scripts/trigger_test_alert.py.")
    parser.add_argument("--camera-id", default="", help="Optional camera id for the synthetic alerts.")
    parser.add_argument("--actor", default="ops.closed_loop_smoke", help="Workflow actor written to audit logs.")
    parser.add_argument("--assignee", default="ops.lead", help="Assignee written to the remediated test case.")
    parser.add_argument("--assignee-email", default="ops@example.com", help="Assignee email written to the remediated test case.")
    parser.add_argument("--note", default="closed loop smoke", help="Note written into the workflow actions.")
    parser.add_argument("--build-feedback-dataset", action="store_true", help="Also build the merged feedback dataset after the false-positive case.")
    return parser.parse_args()


def _parse_key_value_lines(stdout: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        payload[key.strip()] = value.strip()
    return payload


def _trigger_test_alert(args: argparse.Namespace) -> dict[str, str]:
    command = [sys.executable, str(REPO_ROOT / "scripts" / "trigger_test_alert.py")]
    if args.config:
        command.extend(["--config", args.config])
    if args.strict_runtime:
        command.append("--strict-runtime")
    if args.person_id:
        command.extend(["--person-id", args.person_id])
    if args.camera_id:
        command.extend(["--camera-id", args.camera_id])
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    payload = _parse_key_value_lines(result.stdout)
    if "event_no" not in payload:
        raise RuntimeError(f"trigger_test_alert.py did not report an event number.\n{result.stdout}")
    return payload


def _find_alert_by_event_no(repository, event_no: str) -> dict:
    for alert in repository.list_alerts(limit=500):
        if alert.get("event_no") == event_no:
            return alert
    raise RuntimeError(f"Alert not found after injection: {event_no}")


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    if not args.strict_runtime:
        settings = local_smoke_settings(settings)
    repository = build_repository(settings, require_requested_backend=args.strict_runtime)
    workflow = AlertWorkflowService(repository, repo_root=REPO_ROOT)

    remediated_seed = _trigger_test_alert(args)
    false_positive_seed = _trigger_test_alert(args)

    remediated_alert = _find_alert_by_event_no(repository, remediated_seed["event_no"])
    workflow.assign(
        remediated_alert,
        actor=args.actor,
        actor_role="admin",
        assignee=args.assignee,
        assignee_email=args.assignee_email,
        note=f"{args.note} / assign",
    )
    remediated_alert = repository.get_alert(remediated_alert["alert_id"])
    workflow.update_status(
        remediated_alert,
        actor=args.actor,
        actor_role="admin",
        new_status="remediated",
        note=f"{args.note} / remediated",
    )
    remediated_alert = repository.get_alert(remediated_alert["alert_id"])

    false_positive_alert = _find_alert_by_event_no(repository, false_positive_seed["event_no"])
    workflow.update_status(
        false_positive_alert,
        actor=args.actor,
        actor_role="admin",
        new_status="false_positive",
        note=f"{args.note} / false_positive",
    )
    false_positive_alert = repository.get_alert(false_positive_alert["alert_id"])

    hard_cases = repository.list_hard_cases(alert_id=false_positive_alert["alert_id"], limit=20)
    remediated_actions = repository.list_alert_actions(alert_id=remediated_alert["alert_id"], limit=20)
    false_positive_actions = repository.list_alert_actions(alert_id=false_positive_alert["alert_id"], limit=20)

    response: dict[str, object] = {
        "backend": repository.backend_name,
        "remediated_case": {
            "event_no": remediated_alert.get("event_no"),
            "status": remediated_alert.get("status"),
            "assigned_to": remediated_alert.get("assigned_to"),
            "closed_at": remediated_alert.get("closed_at"),
            "actions": [item.get("action_type") for item in remediated_actions],
        },
        "false_positive_case": {
            "event_no": false_positive_alert.get("event_no"),
            "status": false_positive_alert.get("status"),
            "closed_at": false_positive_alert.get("closed_at"),
            "hard_case_count": len(hard_cases),
            "actions": [item.get("action_type") for item in false_positive_actions],
        },
    }

    export_record = export_feedback_cases(
        settings,
        repository,
        actor=args.actor,
        note=f"{args.note} / export_feedback",
        case_types=("false_positive",),
    )
    response["feedback_export"] = {
        "export_id": export_record["export_id"],
        "case_count": export_record["case_count"],
        "export_dir": export_record["export_dir"],
    }

    if args.build_feedback_dataset:
        dataset_record = build_feedback_dataset(
            settings,
            actor=args.actor,
            note=f"{args.note} / build_feedback_dataset",
            repository=repository,
        )
        response["feedback_dataset"] = {
            "dataset_id": dataset_record["dataset_id"],
            "dataset_yaml": dataset_record["dataset_yaml"],
            "feedback_train_images": dataset_record["feedback_train_images"],
            "feedback_val_images": dataset_record["feedback_val_images"],
        }

    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
