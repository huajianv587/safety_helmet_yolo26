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
from helmet_monitoring.services.readiness import collect_readiness_report, ensure_workspace_scaffold
from helmet_monitoring.storage.repository import build_repository


DEPLOY_STRICT_OPTIONAL_CHECKS = {"training_dataset"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect runtime readiness for industrial deployment.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--json", action="store_true", help="Output JSON only.")
    parser.add_argument("--ensure-scaffold", action="store_true", help="Create missing workspace directories before checking.")
    parser.add_argument("--strict", action="store_true", help="Exit with code 1 when any missing check exists.")
    parser.add_argument(
        "--deploy-strict",
        action="store_true",
        help="Exit with code 1 when any readiness check is not ready or when the effective backend falls back.",
    )
    return parser.parse_args()


def _print_report(report: dict) -> None:
    print(f"python={report['python']['version']}")
    print(f"python_executable={report['python']['executable']}")
    print(f"config={report['config']['path']}")
    print(f"requested_backend={report['config']['repository_backend']}")
    effective_backend = report.get("effective_backend")
    if effective_backend:
        print(f"effective_backend={effective_backend}")
    print(f"model_exists={str(report['model']['exists']).lower()} path={report['model']['path']}")
    print(f"cameras={report['cameras']['configured']} configured, {report['cameras']['enabled']} enabled")
    print(
        "dataset="
        f"train:{report['dataset']['train_images']} "
        f"val:{report['dataset']['val_images']} "
        f"exists:{str(report['dataset']['exists']).lower()}"
    )
    print(f"registry={report['identity']['registry_people']} people exists:{str(report['identity']['registry_exists']).lower()}")
    for check in report["checks"]:
        print(f"[{check['status']}] {check['name']} - {check['detail']}")
    if report["next_actions"]:
        print("next_actions:")
        for item in report["next_actions"]:
            print(f"- {item}")


def deploy_blockers(report: dict) -> list[dict]:
    blockers: list[dict] = []
    for item in report["checks"]:
        if item["status"] == "ready":
            continue
        if item["name"] in DEPLOY_STRICT_OPTIONAL_CHECKS:
            continue
        blockers.append(item)
    return blockers


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    if args.ensure_scaffold:
        created = ensure_workspace_scaffold(settings)
        print(f"scaffold_created={len(created)}")
    report = collect_readiness_report(settings)
    try:
        report["effective_backend"] = build_repository(settings).backend_name
    except Exception as exc:
        report["effective_backend"] = f"error:{exc}"
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    if args.strict and any(item["status"] == "missing" for item in report["checks"]):
        raise SystemExit(1)
    if args.deploy_strict:
        non_ready = deploy_blockers(report)
        requested_backend = report["config"]["repository_backend"]
        effective_backend = report.get("effective_backend", "")
        backend_mismatch = bool(effective_backend) and requested_backend != effective_backend
        if non_ready or backend_mismatch:
            if backend_mismatch:
                print(f"deploy_backend_mismatch=requested:{requested_backend} effective:{effective_backend}")
            if non_ready:
                print("deploy_blockers:")
                for item in non_ready:
                    print(f"- [{item['status']}] {item['name']} - {item['detail']}")
            raise SystemExit(1)


if __name__ == "__main__":
    main()
