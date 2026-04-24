from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.core.config import (
    AppSettings,
    ClipSettings,
    EventRuleSettings,
    FaceRecognitionSettings,
    GovernanceSettings,
    IdentitySettings,
    LlmFallbackSettings,
    ModelSettings,
    MonitoringSettings,
    NotificationSettings,
    OcrSettings,
    PersistenceSettings,
    SecuritySettings,
    SupabaseSettings,
    TrackingSettings,
)
from helmet_monitoring.services.optimized_dashboard import OptimizedDashboardAggregator
from helmet_monitoring.storage.repository import LocalAlertRepository
from tests.performance.benchmark import PerformanceBenchmark


def _build_settings(root: Path) -> AppSettings:
    registry_path = root / "persons.json"
    registry_path.write_text("[]", encoding="utf-8")
    return AppSettings(
        repository_backend="local",
        model=ModelSettings(path="models/best.pt"),
        event_rules=EventRuleSettings(),
        persistence=PersistenceSettings(
            snapshot_dir=str(root / "captures"),
            runtime_dir=str(root / "runtime"),
            upload_to_supabase_storage=False,
        ),
        monitoring=MonitoringSettings(),
        identity=IdentitySettings(registry_path=str(registry_path)),
        face_recognition=FaceRecognitionSettings(enabled=False),
        ocr=OcrSettings(enabled=False),
        llm_fallback=LlmFallbackSettings(enabled=False),
        tracking=TrackingSettings(),
        governance=GovernanceSettings(),
        clip=ClipSettings(),
        notifications=NotificationSettings(enabled=False, email_enabled=False),
        security=SecuritySettings(),
        supabase=SupabaseSettings(),
        cameras=(),
        config_path=root / "runtime.json",
    )


class PerformanceBenchmarkHealthTest(unittest.TestCase):
    def test_benchmark_dependencies_are_importable_and_aggregator_runs(self) -> None:
        self.assertIsNotNone(PerformanceBenchmark)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = _build_settings(root)
            repository = LocalAlertRepository(settings.resolve_path(settings.persistence.runtime_dir))
            aggregator = OptimizedDashboardAggregator(settings, repository)

            payload = aggregator.build_overview_payload(days=7)
            repository.close()

        self.assertEqual(payload["repository_backend"], "local")
        self.assertEqual(payload["window_days"], 7)
        self.assertIn("metrics", payload)


if __name__ == "__main__":
    unittest.main()
