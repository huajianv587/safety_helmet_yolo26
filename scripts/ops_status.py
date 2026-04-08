from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.operations import collect_operations_status, send_operations_email


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize ops health, backup state, release state, and active model.")
    parser.add_argument("--config", default=None, help="Runtime config path.")
    parser.add_argument("--json", action="store_true", help="Output JSON only.")
    parser.add_argument("--fail-on-warning", action="store_true", help="Exit with code 1 when any service is not ready.")
    parser.add_argument("--notify", action="store_true", help="Send an ops email when a service is not ready.")
    return parser.parse_args()


def _print_summary(summary: dict) -> None:
    for name, report in summary["services"].items():
        print(f"{name}_status={report['status']}")
        print(f"{name}_detail={report['detail']}")
    print(f"backup_count={summary['backups']['count']}")
    if summary["backups"]["latest"]:
        print(f"latest_backup={summary['backups']['latest']['backup_name']}")
    print(f"release_count={summary['releases']['count']}")
    print(f"active_release={summary['releases']['active_release']}")
    print(f"active_model={summary['models']['active_model']}")


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    summary = collect_operations_status(settings)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        _print_summary(summary)

    unhealthy = [item for item in summary["services"].values() if item["status"] != "ready"]
    if unhealthy and args.notify:
        subject = f"[helmet-monitoring] ops warning x{len(unhealthy)}"
        body = "\n".join(f"{item['service']}: {item['status']} - {item['detail']}" for item in unhealthy)
        result = send_operations_email(
            settings,
            recipients=settings.notifications.default_recipients,
            subject=subject,
            body=body,
        )
        print(f"ops_notification_status={result['status']}")
        print(f"ops_notification_detail={result['detail']}")
    if unhealthy and args.fail_on_warning:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
