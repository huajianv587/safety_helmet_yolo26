from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from helmet_monitoring.core.config import AppSettings, REPO_ROOT
from helmet_monitoring.services.operations import (
    operations_paths,
    ping_dashboard,
    service_health_report,
    write_dashboard_status,
    write_monitor_heartbeat,
)


@dataclass(slots=True, frozen=True)
class ManagedServiceSpec:
    service_name: str
    command: tuple[str, ...]
    log_path: Path
    health_mode: str
    health_url: str | None = None
    restart_delay_seconds: float = 3.0
    startup_grace_seconds: float = 30.0
    stale_after_seconds: int = 90


def managed_service_status_path(spec: ManagedServiceSpec, settings: AppSettings) -> Path:
    paths = operations_paths(settings)
    if spec.health_mode == "dashboard":
        return paths["dashboard_health"]
    if spec.health_mode == "monitor":
        return paths["monitor_health"]
    return paths["ops_dir"] / f"{spec.service_name}_health.json"


def build_managed_service_spec(
    service_name: str,
    *,
    repo_root: Path | None = None,
    python_executable: str | None = None,
    config_path: str | None = None,
    dashboard_port: int = 8501,
    restart_delay_seconds: float = 3.0,
    startup_grace_seconds: float | None = None,
    stale_after_seconds: int | None = None,
) -> ManagedServiceSpec:
    root = (repo_root or REPO_ROOT).resolve()
    python_cmd = python_executable or sys.executable
    services_dir = root / "artifacts" / "runtime" / "services"
    services_dir.mkdir(parents=True, exist_ok=True)

    if service_name == "dashboard":
        command = (
            python_cmd,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.port",
            str(dashboard_port),
            "--server.address",
            "0.0.0.0",
            "--server.headless",
            "true",
        )
        return ManagedServiceSpec(
            service_name="dashboard",
            command=command,
            log_path=services_dir / "dashboard_service.log",
            health_mode="dashboard",
            health_url=f"http://127.0.0.1:{dashboard_port}/_stcore/health",
            restart_delay_seconds=restart_delay_seconds,
            startup_grace_seconds=startup_grace_seconds if startup_grace_seconds is not None else 30.0,
            stale_after_seconds=stale_after_seconds if stale_after_seconds is not None else 60,
        )

    if service_name == "monitor":
        command = [python_cmd, "-u", "scripts/run_monitor.py"]
        if config_path:
            command.extend(["--config", config_path])
        return ManagedServiceSpec(
            service_name="monitor",
            command=tuple(command),
            log_path=services_dir / "monitor_service.log",
            health_mode="monitor",
            restart_delay_seconds=restart_delay_seconds,
            startup_grace_seconds=startup_grace_seconds if startup_grace_seconds is not None else 45.0,
            stale_after_seconds=stale_after_seconds if stale_after_seconds is not None else 90,
        )

    raise ValueError(f"Unsupported managed service: {service_name}")


def check_managed_service_health(spec: ManagedServiceSpec, settings: AppSettings) -> tuple[bool, str]:
    if spec.health_mode == "dashboard":
        detail, latency_ms = ping_dashboard(spec.health_url or "http://127.0.0.1:8501/_stcore/health", timeout_seconds=5.0)
        status = "ready" if detail == "ok" else "error"
        write_dashboard_status(
            settings,
            status=status,
            detail=detail,
            url=spec.health_url or "http://127.0.0.1:8501/_stcore/health",
            latency_ms=latency_ms,
        )
        return status == "ready", detail

    if spec.health_mode == "monitor":
        report = service_health_report(
            operations_paths(settings)["monitor_health"],
            service_name="monitor",
            stale_after_seconds=spec.stale_after_seconds,
        )
        return report["status"] == "ready", str(report["detail"])

    return True, "healthcheck-disabled"


def mark_managed_service_state(spec: ManagedServiceSpec, settings: AppSettings, *, status: str, detail: str) -> None:
    if spec.health_mode == "dashboard":
        write_dashboard_status(
            settings,
            status=status,
            detail=detail,
            url=spec.health_url or "http://127.0.0.1:8501/_stcore/health",
            latency_ms=None,
        )
        return

    if spec.health_mode == "monitor":
        write_monitor_heartbeat(
            settings,
            status=status,
            processed_frames=0,
            repository_backend=settings.repository_backend,
            config_path=str(settings.config_path),
            model_path=settings.model.path,
            camera_statuses=[],
            detail=detail,
        )
