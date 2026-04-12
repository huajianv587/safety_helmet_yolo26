from __future__ import annotations

from dataclasses import replace

from helmet_monitoring.core.config import AppSettings


def local_smoke_settings(settings: AppSettings) -> AppSettings:
    """Downgrade runtime side effects for smoke and UI validation flows."""
    return replace(
        settings,
        repository_backend="local",
        persistence=replace(
            settings.persistence,
            upload_to_supabase_storage=False,
            keep_local_copy=True,
        ),
    )
