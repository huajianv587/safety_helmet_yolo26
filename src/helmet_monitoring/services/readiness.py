from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from helmet_monitoring.core.config import AppSettings, REPO_ROOT


SUPPORTED_PYTHON_MINORS = {(3, 10), (3, 11)}
RECOMMENDED_PYTHON_MINOR = (3, 11)

CORE_DEPENDENCIES = (
    "ultralytics",
    "streamlit",
    "cv2",
    "numpy",
    "pandas",
    "dotenv",
    "supabase",
    "httpx",
    "PIL",
)

IDENTITY_DEPENDENCIES = (
    "torch",
    "facenet_pytorch",
    "paddleocr",
    "rapidocr_onnxruntime",
)


@dataclass(slots=True)
class ReadinessCheck:
    name: str
    status: str
    detail: str


def _package_available(package_name: str) -> bool:
    return importlib.util.find_spec(package_name) is not None


def _load_people_count(registry_path: Path) -> int:
    if not registry_path.exists():
        return 0
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if isinstance(payload, list):
        return len(payload)
    return 0


def _count_images(target: Path) -> int:
    if not target.exists():
        return 0
    total = 0
    for pattern in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
        total += len(list(target.rglob(pattern)))
    return total


def workspace_paths(settings: AppSettings, repo_root: Path | None = None) -> list[Path]:
    base = repo_root or REPO_ROOT
    return [
        settings.resolve_path(settings.persistence.snapshot_dir),
        settings.resolve_path(settings.persistence.runtime_dir),
        settings.resolve_path(settings.persistence.runtime_dir) / "ops",
        settings.resolve_path(settings.face_recognition.face_profile_dir),
        base / "artifacts" / "backups",
        base / "artifacts" / "logs",
        base / "artifacts" / "reports",
        base / "artifacts" / "exports",
        base / "artifacts" / "exports" / "model_feedback",
        base / "artifacts" / "identity" / "badges",
        base / "artifacts" / "identity" / "review",
        base / "artifacts" / "releases",
        base / "artifacts" / "releases" / "snapshots",
        base / "data" / "hard_cases" / "false_positive",
        base / "data" / "hard_cases" / "labeled" / "images" / "train",
        base / "data" / "hard_cases" / "labeled" / "images" / "val",
        base / "data" / "hard_cases" / "labeled" / "labels" / "train",
        base / "data" / "hard_cases" / "labeled" / "labels" / "val",
        base / "data" / "hard_cases" / "missed_detection",
        base / "data" / "hard_cases" / "night_shift",
        base / "data" / "identity" / "faces",
        base / "data" / "identity" / "badges",
        base / "deploy" / "caddy",
        base / "docs",
    ]


def ensure_workspace_scaffold(settings: AppSettings, repo_root: Path | None = None) -> list[Path]:
    created: list[Path] = []
    for path in workspace_paths(settings, repo_root=repo_root):
        if path.exists():
            continue
        path.mkdir(parents=True, exist_ok=True)
        created.append(path)
    return created


def collect_readiness_report(settings: AppSettings, repo_root: Path | None = None) -> dict[str, Any]:
    base = repo_root or REPO_ROOT
    checks: list[ReadinessCheck] = []
    python_minor = (sys.version_info.major, sys.version_info.minor)

    config_path = settings.config_path
    model_path = settings.resolve_path(settings.model.path)
    registry_path = settings.resolve_path(settings.identity.registry_path)
    dataset_root = base / "data" / "helmet_detection_dataset"
    dataset_train = dataset_root / "images" / "train"
    dataset_val = dataset_root / "images" / "val"
    enabled_cameras = [camera for camera in settings.cameras if camera.enabled]
    required_paths = workspace_paths(settings, repo_root=base)
    missing_workspace = [str(path) for path in required_paths if not path.exists()]
    core_deps = {name: _package_available(name) for name in CORE_DEPENDENCIES}
    identity_deps = {name: _package_available(name) for name in IDENTITY_DEPENDENCIES}
    supabase_ready = settings.supabase.is_configured
    smtp_ready = settings.notifications.is_email_configured
    openai_ready = bool(os.getenv("OPENAI_API_KEY", "").strip())
    deepseek_ready = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())

    if python_minor == RECOMMENDED_PYTHON_MINOR:
        checks.append(ReadinessCheck("python_runtime", "ready", f"Python {sys.version.split()[0]} detected (recommended runtime)."))
    elif python_minor in SUPPORTED_PYTHON_MINORS:
        checks.append(
            ReadinessCheck(
                "python_runtime",
                "ready",
                f"Python {sys.version.split()[0]} detected (supported; Python 3.11 is the project default).",
            )
        )
    else:
        checks.append(
            ReadinessCheck(
                "python_runtime",
                "warn",
                f"Python {sys.version.split()[0]} detected; use Python 3.11 (preferred) or 3.10 for full compatibility.",
            )
        )

    if config_path.exists():
        checks.append(ReadinessCheck("runtime_config", "ready", f"Using runtime config: {config_path}"))
    else:
        checks.append(ReadinessCheck("runtime_config", "missing", f"Missing runtime config: {config_path}"))

    if model_path.exists():
        checks.append(ReadinessCheck("detector_model", "ready", f"Model found: {model_path}"))
    else:
        checks.append(ReadinessCheck("detector_model", "missing", f"Model not found: {model_path}"))

    if enabled_cameras:
        checks.append(ReadinessCheck("camera_sources", "ready", f"Enabled cameras: {len(enabled_cameras)}"))
    else:
        checks.append(ReadinessCheck("camera_sources", "missing", "No enabled cameras in runtime config."))

    if registry_path.exists():
        checks.append(
            ReadinessCheck(
                "person_registry",
                "ready",
                f"Person registry found with {_load_people_count(registry_path)} records.",
            )
        )
    else:
        checks.append(ReadinessCheck("person_registry", "missing", f"Missing person registry: {registry_path}"))

    if dataset_root.exists() and dataset_train.exists() and dataset_val.exists():
        checks.append(
            ReadinessCheck(
                "training_dataset",
                "ready",
                f"Dataset ready: train={_count_images(dataset_train)} val={_count_images(dataset_val)}",
            )
        )
    else:
        checks.append(ReadinessCheck("training_dataset", "warn", f"Dataset incomplete: {dataset_root}"))

    if missing_workspace:
        checks.append(
            ReadinessCheck(
                "workspace_scaffold",
                "warn",
                f"Missing workspace directories: {', '.join(missing_workspace)}",
            )
        )
    else:
        checks.append(ReadinessCheck("workspace_scaffold", "ready", "Workspace scaffold is complete."))

    gateway_config = base / "deploy" / "caddy" / "Caddyfile"
    if gateway_config.exists():
        checks.append(ReadinessCheck("edge_gateway", "ready", f"Reverse proxy config found: {gateway_config}"))
    else:
        checks.append(ReadinessCheck("edge_gateway", "warn", f"Missing reverse proxy config: {gateway_config}"))

    labeled_feedback_root = base / "data" / "hard_cases" / "labeled"
    if labeled_feedback_root.exists():
        checks.append(ReadinessCheck("model_feedback_workspace", "ready", f"Feedback labeling workspace ready: {labeled_feedback_root}"))
    else:
        checks.append(ReadinessCheck("model_feedback_workspace", "warn", f"Missing feedback labeling workspace: {labeled_feedback_root}"))

    if all(core_deps.values()):
        checks.append(ReadinessCheck("core_dependencies", "ready", "Core runtime dependencies are available."))
    else:
        missing = [name for name, available in core_deps.items() if not available]
        checks.append(ReadinessCheck("core_dependencies", "missing", f"Missing core packages: {', '.join(missing)}"))

    if settings.face_recognition.enabled:
        if identity_deps["torch"] and identity_deps["facenet_pytorch"]:
            checks.append(ReadinessCheck("face_stack", "ready", "Face recognition dependencies are available."))
        else:
            checks.append(
                ReadinessCheck(
                    "face_stack",
                    "warn",
                    "Face recognition is enabled but torch/facenet-pytorch is not fully installed.",
                )
            )

    if settings.ocr.enabled:
        if settings.ocr.provider == "paddleocr" and identity_deps["paddleocr"]:
            checks.append(ReadinessCheck("badge_ocr", "ready", "PaddleOCR is available."))
        elif settings.ocr.provider == "rapidocr" and identity_deps["rapidocr_onnxruntime"]:
            checks.append(ReadinessCheck("badge_ocr", "ready", "RapidOCR is available."))
        elif settings.ocr.provider == "auto" and (identity_deps["paddleocr"] or identity_deps["rapidocr_onnxruntime"]):
            checks.append(ReadinessCheck("badge_ocr", "ready", "At least one OCR backend is available."))
        else:
            checks.append(
                ReadinessCheck(
                    "badge_ocr",
                    "warn",
                    f"OCR is enabled with provider={settings.ocr.provider}, but the backend is unavailable.",
                )
            )

    if settings.repository_backend == "supabase":
        if supabase_ready:
            checks.append(ReadinessCheck("supabase_credentials", "ready", "Supabase credentials are configured."))
        else:
            checks.append(
                ReadinessCheck(
                    "supabase_credentials",
                    "missing",
                    "Repository backend is supabase, but SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY is missing.",
                )
            )
        if settings.persistence.upload_to_supabase_storage:
            if settings.security.use_private_bucket:
                checks.append(
                    ReadinessCheck(
                        "storage_privacy",
                        "ready",
                        "Evidence storage is configured to use a private bucket with signed URLs.",
                    )
                )
            else:
                checks.append(
                    ReadinessCheck(
                        "storage_privacy",
                        "warn",
                        "Supabase evidence uploads are enabled, but use_private_bucket=false exposes public artifact URLs.",
                    )
                )

    if smtp_ready:
        checks.append(ReadinessCheck("smtp", "ready", "SMTP notification settings are configured."))
    else:
        checks.append(ReadinessCheck("smtp", "warn", "SMTP is not fully configured; email closure is disabled."))

    if settings.llm_fallback.enabled:
        if openai_ready or deepseek_ready:
            providers: list[str] = []
            if openai_ready:
                providers.append("OpenAI")
            if deepseek_ready:
                providers.append("DeepSeek")
            checks.append(ReadinessCheck("llm_fallback", "ready", f"LLM fallback ready: {', '.join(providers)}"))
        else:
            checks.append(
                ReadinessCheck(
                    "llm_fallback",
                    "warn",
                    "LLM fallback is enabled, but OPENAI_API_KEY / DEEPSEEK_API_KEY is missing.",
                )
            )

    next_actions: list[str] = []
    if python_minor not in SUPPORTED_PYTHON_MINORS:
        next_actions.append("Rebuild the project virtual environment with Python 3.11 (preferred) or Python 3.10.")
    if not model_path.exists():
        next_actions.append("Train or place a production detector model, then update model.path in configs/runtime.json.")
    if not enabled_cameras:
        next_actions.append("Enable at least one real webcam, RTSP stream, or sample video in configs/runtime.json.")
    if settings.repository_backend == "supabase" and not supabase_ready:
        next_actions.append("Fill SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, then rerun python scripts/check_supabase.py.")
    if (
        settings.repository_backend == "supabase"
        and settings.persistence.upload_to_supabase_storage
        and not settings.security.use_private_bucket
    ):
        next_actions.append("Set security.use_private_bucket=true so evidence is shared through signed URLs instead of public links.")
    if missing_workspace:
        next_actions.append("Run python scripts/bootstrap_workspace.py to create the industrial workspace scaffold.")
    if not registry_path.exists():
        next_actions.append("Prepare configs/person_registry.json and sync it with python scripts/sync_person_registry.py.")
    if not gateway_config.exists():
        next_actions.append("Create deploy/caddy/Caddyfile and enable the edge gateway profile for HTTPS / reverse proxy rollout.")
    if settings.face_recognition.enabled and not (identity_deps["torch"] and identity_deps["facenet_pytorch"]):
        next_actions.append("Install python -m pip install -r requirements.identity.txt for local face recognition.")
    if settings.ocr.enabled and not (identity_deps["paddleocr"] or identity_deps["rapidocr_onnxruntime"]):
        next_actions.append("Install OCR extras from requirements.identity.txt or set ocr.provider to none for now.")
    if not smtp_ready:
        next_actions.append("Provide SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM_EMAIL.")
    if settings.llm_fallback.enabled and not (openai_ready or deepseek_ready):
        next_actions.append("Provide OPENAI_API_KEY or DEEPSEEK_API_KEY for OCR ambiguity fallback.")

    return {
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
        },
        "config": {
            "path": str(config_path),
            "repository_backend": settings.repository_backend,
        },
        "model": {
            "path": str(model_path),
            "exists": model_path.exists(),
        },
        "cameras": {
            "configured": len(settings.cameras),
            "enabled": len(enabled_cameras),
        },
        "identity": {
            "registry_path": str(registry_path),
            "registry_exists": registry_path.exists(),
            "registry_people": _load_people_count(registry_path),
            "face_profile_dir": str(settings.resolve_path(settings.face_recognition.face_profile_dir)),
        },
        "dataset": {
            "root": str(dataset_root),
            "exists": dataset_root.exists(),
            "train_images": _count_images(dataset_train),
            "val_images": _count_images(dataset_val),
        },
        "workspace": {
            "required_paths": [str(path) for path in required_paths],
            "missing_paths": missing_workspace,
        },
        "services": {
            "supabase": {
                "configured": supabase_ready,
                "url_present": bool(settings.supabase.url),
                "service_role_present": bool(settings.supabase.service_role_key),
            },
            "smtp": {
                "configured": smtp_ready,
                "default_recipients": list(settings.notifications.default_recipients),
            },
            "llm": {
                "enabled": settings.llm_fallback.enabled,
                "openai_key_present": openai_ready,
                "deepseek_key_present": deepseek_ready,
            },
        },
        "security": {
            "use_private_bucket": settings.security.use_private_bucket,
            "signed_url_seconds": settings.security.signed_url_seconds,
            "audit_enabled": settings.security.audit_enabled,
        },
        "dependencies": {
            "core": core_deps,
            "identity": identity_deps,
        },
        "checks": [asdict(check) for check in checks],
        "next_actions": next_actions,
    }
