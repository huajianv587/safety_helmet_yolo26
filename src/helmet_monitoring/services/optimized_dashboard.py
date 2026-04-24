"""
Compatibility wrapper for dashboard aggregation.

This module keeps the "optimized dashboard" entrypoints stable while the
aggregation logic is consolidated back onto the canonical dashboard payload
builder. That avoids benchmark/import drift and keeps the API contract aligned
with the production implementation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from helmet_monitoring.core.config import AppSettings
from helmet_monitoring.services.dashboard_api import build_overview_payload
from helmet_monitoring.storage.repository import AlertRepository


class OptimizedDashboardAggregator:
    """
    Stable adapter used by benchmarks and future optimization work.

    The class preserves the intended optimized-dashboard public surface while
    delegating to the authoritative payload builder for now.
    """

    def __init__(self, settings: AppSettings, repository: AlertRepository) -> None:
        self.settings = settings
        self.repository = repository

    def build_overview_payload(
        self,
        *,
        days: int = 7,
        recent_limit: int = 12,
        evidence_limit: int = 6,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return build_overview_payload(
            self.settings,
            self.repository,
            days=days,
            recent_limit=recent_limit,
            evidence_limit=evidence_limit,
            now=now,
        )


# Backwards-compatible alias for earlier drafts of this module.
DashboardAggregator = OptimizedDashboardAggregator


def build_overview_payload_optimized(
    settings: AppSettings,
    repository: AlertRepository,
    *,
    days: int = 7,
    recent_limit: int = 12,
    evidence_limit: int = 6,
    now: datetime | None = None,
) -> dict[str, Any]:
    return build_overview_payload(
        settings,
        repository,
        days=days,
        recent_limit=recent_limit,
        evidence_limit=evidence_limit,
        now=now,
    )
