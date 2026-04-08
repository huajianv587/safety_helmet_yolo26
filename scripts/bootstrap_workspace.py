from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.services.readiness import ensure_workspace_scaffold


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the industrial workspace scaffold and missing starter files.")
    parser.add_argument("--config", default="configs/runtime.json", help="Runtime config path.")
    parser.add_argument("--copy-env-example", action="store_true", help="Copy configs/supabase.example.env to .env when missing.")
    parser.add_argument(
        "--copy-registry-example",
        action="store_true",
        help="Copy configs/person_registry.example.json to the runtime registry path when missing.",
    )
    return parser.parse_args()


def _copy_if_missing(source: Path, target: Path) -> bool:
    if target.exists() or not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return True


def main() -> None:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (REPO_ROOT / config_path).resolve()

    runtime_example = REPO_ROOT / "configs" / "runtime.example.json"
    if _copy_if_missing(runtime_example, config_path):
        print(f"created_config={config_path}")

    if args.copy_env_example:
        env_example = REPO_ROOT / "configs" / "supabase.example.env"
        env_target = REPO_ROOT / ".env"
        if _copy_if_missing(env_example, env_target):
            print(f"created_env={env_target}")

    settings = load_settings(config_path)
    created_dirs = ensure_workspace_scaffold(settings)

    if args.copy_registry_example:
        registry_example = REPO_ROOT / "configs" / "person_registry.example.json"
        registry_target = settings.resolve_path(settings.identity.registry_path)
        if _copy_if_missing(registry_example, registry_target):
            print(f"created_registry={registry_target}")

    print(f"created_directories={len(created_dirs)}")
    for path in created_dirs:
        print(str(path))


if __name__ == "__main__":
    main()
