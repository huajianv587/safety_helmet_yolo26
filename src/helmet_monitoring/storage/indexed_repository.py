from __future__ import annotations

from pathlib import Path
from typing import Any

from helmet_monitoring.storage.repository import LocalAlertRepository


class IndexedLocalAlertRepository(LocalAlertRepository):
    """
    Compatibility wrapper around the SQLite-backed local repository.

    The old optimized JSONL index layer is no longer needed because the local
    runtime store now uses SQLite indexes and aggregate tables natively.
    """

    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir)

    def get_index_stats(self) -> dict[str, Any]:
        cursor = self._conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM alerts) AS total_alerts,
                (SELECT COUNT(*) FROM cameras) AS total_cameras,
                (SELECT COUNT(*) FROM alert_aggregates_hourly) AS hourly_buckets,
                (SELECT COUNT(*) FROM alert_aggregates_daily) AS daily_buckets
            """
        )
        row = cursor.fetchone()
        return {
            "total_alerts": int(row["total_alerts"]) if row else 0,
            "total_cameras": int(row["total_cameras"]) if row else 0,
            "hourly_buckets": int(row["hourly_buckets"]) if row else 0,
            "daily_buckets": int(row["daily_buckets"]) if row else 0,
            "backend": "sqlite",
        }
