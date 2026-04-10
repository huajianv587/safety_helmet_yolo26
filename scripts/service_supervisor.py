from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import load_settings
from helmet_monitoring.core.schemas import utc_now
from helmet_monitoring.services.service_supervisor import (
    build_managed_service_spec,
    check_managed_service_health,
    managed_service_status_path,
    mark_managed_service_state,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a managed dashboard or monitor process with automatic healthcheck-based restarts."
    )
    parser.add_argument("service", choices=["dashboard", "monitor"], help="Managed service name.")
    parser.add_argument("--config", default=None, help="Runtime config path.")
    parser.add_argument("--dashboard-port", type=int, default=8501, help="Dashboard port when service=dashboard.")
    parser.add_argument("--restart-delay", type=float, default=3.0, help="Delay before each restart in seconds.")
    parser.add_argument("--startup-grace", type=float, default=None, help="Grace period before healthchecks begin.")
    parser.add_argument("--stale-after", type=int, default=None, help="Health stale threshold in seconds.")
    parser.add_argument("--check-interval", type=float, default=5.0, help="Health poll interval in seconds.")
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=0,
        help="Maximum restart attempts before exiting. Use 0 to restart forever.",
    )
    return parser.parse_args()


def _supervisor_log(handle, message: str) -> None:
    timestamp = utc_now().isoformat()
    line = f"[supervisor] {timestamp} {message}"
    print(line, flush=True)
    handle.write(line + "\n")
    handle.flush()


def _terminate_process(process: subprocess.Popen[str], *, timeout_seconds: float = 10.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)


def _spawn_process(spec, log_handle) -> subprocess.Popen[str]:
    return subprocess.Popen(
        spec.command,
        cwd=str(REPO_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
    )


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    spec = build_managed_service_spec(
        args.service,
        repo_root=REPO_ROOT,
        python_executable=sys.executable,
        config_path=args.config,
        dashboard_port=args.dashboard_port,
        restart_delay_seconds=args.restart_delay,
        startup_grace_seconds=args.startup_grace,
        stale_after_seconds=args.stale_after,
    )
    spec.log_path.parent.mkdir(parents=True, exist_ok=True)
    status_path = managed_service_status_path(spec, settings)
    restarts = 0
    stopping = False
    process: subprocess.Popen[str] | None = None

    def _request_stop(*_args) -> None:
        nonlocal stopping
        stopping = True

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    with spec.log_path.open("a", encoding="utf-8", buffering=1) as log_handle:
        _supervisor_log(log_handle, f"service={spec.service_name} log_path={spec.log_path}")
        _supervisor_log(log_handle, f"health_status_path={status_path}")
        while not stopping:
            process = _spawn_process(spec, log_handle)
            started_at = time.monotonic()
            _supervisor_log(log_handle, f"started pid={process.pid} command={' '.join(spec.command)}")

            unhealthy_detail: str | None = None
            while not stopping:
                exit_code = process.poll()
                if exit_code is not None:
                    _supervisor_log(log_handle, f"process_exited exit_code={exit_code}")
                    unhealthy_detail = f"process exited with code {exit_code}"
                    break
                if (time.monotonic() - started_at) < spec.startup_grace_seconds:
                    time.sleep(min(args.check_interval, 1.0))
                    continue
                healthy, detail = check_managed_service_health(spec, settings)
                if healthy:
                    time.sleep(args.check_interval)
                    continue
                unhealthy_detail = detail
                _supervisor_log(log_handle, f"health_failed detail={detail}")
                mark_managed_service_state(spec, settings, status="error", detail=f"Supervisor restart: {detail}")
                _terminate_process(process)
                break

            if process.poll() is None:
                _terminate_process(process)

            if stopping:
                mark_managed_service_state(spec, settings, status="stopped", detail="Service stopped by operator.")
                _supervisor_log(log_handle, "stopped_by_operator")
                return

            restarts += 1
            mark_managed_service_state(
                spec,
                settings,
                status="error",
                detail=f"Supervisor restart #{restarts}: {unhealthy_detail or 'unknown failure'}",
            )
            if args.max_restarts > 0 and restarts > args.max_restarts:
                _supervisor_log(log_handle, f"restart_limit_reached max_restarts={args.max_restarts}")
                raise SystemExit(1)
            _supervisor_log(log_handle, f"restarting_in={spec.restart_delay_seconds}s")
            time.sleep(spec.restart_delay_seconds)


if __name__ == "__main__":
    main()
