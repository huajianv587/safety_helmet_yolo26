"""
Tiered caching system for the Safety Helmet Monitoring API.

Provides intelligent, multi-tier caching with automatic invalidation,
cache warming, and performance monitoring.
"""

import copy
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Optional


class CacheTier(Enum):
    """Cache tier definitions with TTL and characteristics."""

    # Static data - rarely changes
    STATIC = ("static", 300.0)  # 5 minutes

    # Configuration data - changes infrequently
    CONFIG = ("config", 120.0)  # 2 minutes

    # Camera list - semi-static
    CAMERAS = ("cameras", 60.0)  # 1 minute

    # Alert summaries and aggregations
    SUMMARIES = ("summaries", 30.0)  # 30 seconds

    # Real-time metrics and counts
    METRICS = ("metrics", 5.0)  # 5 seconds

    # User session data
    SESSION = ("session", 900.0)  # 15 minutes

    def __init__(self, tier_name: str, ttl_seconds: float) -> None:
        self.tier_name = tier_name
        self.ttl_seconds = ttl_seconds


@dataclass
class CacheEntry:
    """Single cache entry with metadata."""
    value: Any
    expires_at: float
    tier: CacheTier
    hit_count: int = 0
    created_at: float = field(default_factory=time.monotonic)
    last_accessed: float = field(default_factory=time.monotonic)

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.monotonic() >= self.expires_at

    def record_hit(self) -> None:
        """Record a cache hit."""
        self.hit_count += 1
        self.last_accessed = time.monotonic()


@dataclass
class CacheStats:
    """Cache performance statistics."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    invalidations: int = 0
    total_entries: int = 0
    admission_rejections: int = 0
    admission_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "invalidations": self.invalidations,
            "total_entries": self.total_entries,
            "hit_rate_percent": round(self.hit_rate, 2),
            "admission_rejections": self.admission_rejections,
            "admission_reasons": dict(self.admission_reasons),
        }


def _stable_json_default(value: Any) -> Any:
    """Convert uncommon key parts into stable string representations."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass
    return str(value)


def stable_cache_key(key: Any) -> str:
    """
    Convert arbitrary cache keys into a deterministic string form.

    This avoids process-randomized `hash()` output and makes cache keys
    observable in logs, metrics, and manual debugging.
    """
    if isinstance(key, str):
        return key
    try:
        return json.dumps(
            key,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            default=_stable_json_default,
        )
    except TypeError:
        return str(key)


def _is_cacheable(value: Any) -> bool:
    """Allow only deepcopy-safe, read-model style payloads into the shared cache."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_cacheable(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, (str, int, float, bool, type(None))) and _is_cacheable(item)
            for key, item in value.items()
        )
    return False


def _clone_cache_value(value: Any) -> Any:
    """Return a safe copy of a cached payload."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return copy.deepcopy(value)


class TieredCacheManager:
    """
    Multi-tier cache manager with automatic expiration and invalidation.

    Features:
    - Tiered TTLs based on data volatility
    - Thread-safe operations
    - Cache statistics and monitoring
    - Automatic cleanup of expired entries
    - Cache warming support
    - Namespace isolation
    """

    def __init__(self, max_entries: int = 1000) -> None:
        """
        Initialize cache manager.

        Args:
            max_entries: Maximum number of cache entries before eviction
        """
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = Lock()
        self._stats = CacheStats()
        self._max_entries = max_entries
        self._warmup_callbacks: dict[str, Callable[[], Any]] = {}

    def get(self, key: Any, tier: CacheTier) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key
            tier: Cache tier (for validation)

        Returns:
            Cached value or None if not found/expired
        """
        normalized_key = stable_cache_key(key)
        with self._lock:
            entry = self._cache.get(normalized_key)

            if entry is None:
                self._stats.misses += 1
                return None

            if entry.is_expired():
                # Expired entry - remove and count as miss
                del self._cache[normalized_key]
                self._stats.misses += 1
                self._stats.evictions += 1
                self._stats.total_entries = len(self._cache)
                return None

            # Valid cache hit
            entry.record_hit()
            self._stats.hits += 1
            # Move to end for LRU tracking
            self._cache.move_to_end(normalized_key)
            return _clone_cache_value(entry.value)

    def set(self, key: Any, value: Any, tier: CacheTier) -> bool:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            tier: Cache tier (determines TTL)
        """
        normalized_key = stable_cache_key(key)
        with self._lock:
            if not _is_cacheable(value):
                reason = f"unsupported_type:{type(value).__name__}"
                self._stats.admission_rejections += 1
                self._stats.admission_reasons[reason] = self._stats.admission_reasons.get(reason, 0) + 1
                return False

            # Check if we need to evict entries
            if normalized_key not in self._cache and len(self._cache) >= self._max_entries:
                self._evict_lru()

            expires_at = time.monotonic() + tier.ttl_seconds
            cached_value = _clone_cache_value(value)

            self._cache[normalized_key] = CacheEntry(
                value=cached_value,
                expires_at=expires_at,
                tier=tier,
            )
            self._cache.move_to_end(normalized_key)
            self._stats.total_entries = len(self._cache)
            return True

    def invalidate(self, key: Any) -> bool:
        """
        Invalidate a specific cache entry.

        Args:
            key: Cache key to invalidate

        Returns:
            True if entry was found and removed
        """
        normalized_key = stable_cache_key(key)
        with self._lock:
            if normalized_key in self._cache:
                del self._cache[normalized_key]
                self._stats.invalidations += 1
                self._stats.total_entries = len(self._cache)
                return True
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all cache entries matching a pattern.

        Args:
            pattern: Key pattern (supports * wildcard)

        Returns:
            Number of entries invalidated
        """
        with self._lock:
            keys_to_remove = []

            if "*" in pattern:
                # Wildcard pattern matching
                prefix = pattern.split("*")[0]
                suffix = pattern.split("*")[-1] if pattern.count("*") > 0 else ""

                for key in self._cache:
                    if key.startswith(prefix) and key.endswith(suffix):
                        keys_to_remove.append(key)
            else:
                # Exact match
                if pattern in self._cache:
                    keys_to_remove.append(pattern)

            for key in keys_to_remove:
                del self._cache[key]

            count = len(keys_to_remove)
            self._stats.invalidations += count
            self._stats.total_entries = len(self._cache)
            return count

    def invalidate_tier(self, tier: CacheTier) -> int:
        """
        Invalidate all entries in a specific tier.

        Args:
            tier: Cache tier to invalidate

        Returns:
            Number of entries invalidated
        """
        with self._lock:
            keys_to_remove = [
                key for key, entry in self._cache.items()
                if entry.tier == tier
            ]

            for key in keys_to_remove:
                del self._cache[key]

            count = len(keys_to_remove)
            self._stats.invalidations += count
            self._stats.total_entries = len(self._cache)
            return count

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._stats.invalidations += count
            self._stats.total_entries = 0

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            now = time.monotonic()
            keys_to_remove = [
                key for key, entry in self._cache.items()
                if entry.expires_at <= now
            ]

            for key in keys_to_remove:
                del self._cache[key]

            count = len(keys_to_remove)
            self._stats.evictions += count
            self._stats.total_entries = len(self._cache)
            return count

    def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            stats = self._stats.to_dict()

            # Add per-tier statistics
            tier_stats: dict[str, dict[str, int]] = {}
            for entry in self._cache.values():
                tier_name = entry.tier.tier_name
                if tier_name not in tier_stats:
                    tier_stats[tier_name] = {"count": 0, "total_hits": 0}
                tier_stats[tier_name]["count"] += 1
                tier_stats[tier_name]["total_hits"] += entry.hit_count

            stats["tiers"] = tier_stats
            return stats

    def register_warmup(self, key: str, callback: Callable[[], Any], tier: CacheTier) -> None:
        """
        Register a cache warmup callback.

        Args:
            key: Cache key to warm
            callback: Function that returns the value to cache
            tier: Cache tier for the warmed data
        """
        self._warmup_callbacks[key] = (callback, tier)

    def warmup(self) -> int:
        """
        Execute all registered warmup callbacks.

        Returns:
            Number of entries warmed
        """
        count = 0
        for key, (callback, tier) in self._warmup_callbacks.items():
            try:
                value = callback()
                self.set(key, value, tier)
                count += 1
            except Exception:
                # Silently skip failed warmups
                pass
        return count

    def _evict_lru(self) -> None:
        """Evict least recently used entry (internal, assumes lock held)."""
        if not self._cache:
            return

        # Optimization: O(1) eviction using OrderedDict
        # Remove the first (oldest) item
        self._cache.popitem(last=False)
        self._stats.evictions += 1


# Global cache manager instance
_cache_manager: Optional[TieredCacheManager] = None
_cache_manager_lock = Lock()


def get_cache_manager() -> TieredCacheManager:
    """Get or create the global cache manager instance."""
    global _cache_manager

    if _cache_manager is None:
        with _cache_manager_lock:
            if _cache_manager is None:
                _cache_manager = TieredCacheManager(max_entries=1000)

    return _cache_manager


def reset_cache_manager() -> None:
    """Reset the global cache manager (for testing)."""
    global _cache_manager
    with _cache_manager_lock:
        _cache_manager = None
