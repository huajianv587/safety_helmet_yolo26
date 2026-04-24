from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.api.cache_manager import CacheTier, TieredCacheManager, stable_cache_key


class _NonCacheableRuntimeObject:
    def __init__(self) -> None:
        self.lock = threading.Lock()


class CacheManagerTest(unittest.TestCase):
    def test_rejects_non_cacheable_runtime_objects_and_tracks_admission_stats(self) -> None:
        cache = TieredCacheManager(max_entries=8)

        stored = cache.set("summaries:ok", {"total": 1, "items": []}, CacheTier.SUMMARIES)
        rejected = cache.set("runtime:services", _NonCacheableRuntimeObject(), CacheTier.METRICS)

        self.assertTrue(stored)
        self.assertFalse(rejected)
        self.assertIsNone(cache.get("runtime:services", CacheTier.METRICS))

        stats = cache.get_stats()
        self.assertEqual(stats["admission_rejections"], 1)
        self.assertIn("unsupported_type:_NonCacheableRuntimeObject", stats["admission_reasons"])

    def test_stable_cache_key_is_deterministic_for_structured_keys(self) -> None:
        key = ("overview", {"days": 7, "role": "viewer"}, ["cam-001", "cam-002"])
        first = stable_cache_key(key)
        second = stable_cache_key(key)

        self.assertEqual(first, second)
        self.assertIn('"overview"', first)
        self.assertIn('"days":7', first)


if __name__ == "__main__":
    unittest.main()
