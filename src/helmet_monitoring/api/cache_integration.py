"""
Cache integration helpers for the Safety Helmet Monitoring API.

Provides decorator-based caching and invalidation hooks for API endpoints.
"""

from functools import wraps
from typing import Any, Callable

from .cache_manager import CacheTier, get_cache_manager


def cached_endpoint(tier: CacheTier, key_builder: Callable[..., str] | None = None):
    """
    Decorator for caching API endpoint responses.

    Args:
        tier: Cache tier to use
        key_builder: Optional function to build cache key from args/kwargs
                    If None, uses function name and all args as key

    Example:
        @cached_endpoint(CacheTier.CAMERAS, lambda camera_id: f"camera:{camera_id}")
        def get_camera(camera_id: str):
            return fetch_camera(camera_id)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = get_cache_manager()

            # Build cache key
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                # Default: use function name + stringified args
                key_parts = [func.__name__]
                key_parts.extend(str(arg) for arg in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = ":".join(key_parts)

            # Try cache first
            cached_value = cache.get(cache_key, tier)
            if cached_value is not None:
                return cached_value

            # Cache miss - execute function
            result = func(*args, **kwargs)

            # Store in cache
            cache.set(cache_key, result, tier)

            return result

        return wrapper
    return decorator


def invalidate_on_mutation(patterns: list[str]):
    """
    Decorator to invalidate cache entries after a mutation.

    Args:
        patterns: List of cache key patterns to invalidate (supports * wildcard)

    Example:
        @invalidate_on_mutation(["alerts:*", "summaries:*"])
        def create_alert(alert_data):
            return save_alert(alert_data)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Execute the mutation
            result = func(*args, **kwargs)

            # Invalidate cache patterns
            cache = get_cache_manager()
            for pattern in patterns:
                cache.invalidate_pattern(pattern)

            return result

        return wrapper
    return decorator


class CacheKeyBuilder:
    """Helper class for building consistent cache keys."""

    @staticmethod
    def alerts_list(
        q: str = "",
        status: str | None = None,
        identity_status: str | None = None,
        department: str | None = None,
        camera_id: str | None = None,
        days: int = 7,
        limit: int = 100,
        offset: int = 0,
        cursor: str | None = None,
        mode: str = "compact",
        include_media: bool = False,
    ) -> str:
        """Build cache key for alerts list endpoint."""
        parts = [
            "alerts:list",
            f"q={q}",
            f"status={status or 'all'}",
            f"identity_status={identity_status or 'all'}",
            f"department={department or 'all'}",
            f"camera_id={camera_id or 'all'}",
            f"days={days}",
            f"limit={limit}",
            f"offset={offset}",
            f"cursor={cursor or 'none'}",
            f"mode={mode}",
            f"media={include_media}",
        ]
        return ":".join(parts)

    @staticmethod
    def alert_detail(alert_id: str) -> str:
        """Build cache key for alert detail endpoint."""
        return f"alerts:detail:{alert_id}"

    @staticmethod
    def cameras_list() -> str:
        """Build cache key for cameras list endpoint."""
        return "cameras:list"

    @staticmethod
    def camera_live(camera_id: str) -> str:
        """Build cache key for live camera status."""
        return f"cameras:live:{camera_id}"

    @staticmethod
    def people_list() -> str:
        """Build cache key for people list endpoint."""
        return "people:list"

    @staticmethod
    def summary_stats(days: int = 7) -> str:
        """Build cache key for summary statistics."""
        return f"summaries:stats:days={days}"

    @staticmethod
    def config_summary() -> str:
        """Build cache key for config summary."""
        return "config:summary"

    @staticmethod
    def accounts_list() -> str:
        """Build cache key for accounts list."""
        return "accounts:list"

    @staticmethod
    def ops_capabilities() -> str:
        """Build cache key for ops capabilities."""
        return "ops:capabilities"

    @staticmethod
    def ops_readiness() -> str:
        """Build cache key for ops readiness."""
        return "ops:readiness"


class CacheInvalidator:
    """Helper class for cache invalidation patterns."""

    @staticmethod
    def on_alert_created() -> list[str]:
        """Patterns to invalidate when an alert is created."""
        return [
            "alerts:list:*",
            "summaries:*",
            "cameras:live:*",
        ]

    @staticmethod
    def on_alert_updated(alert_id: str) -> list[str]:
        """Patterns to invalidate when an alert is updated."""
        return [
            f"alerts:detail:{alert_id}",
            "alerts:list:*",
            "summaries:*",
        ]

    @staticmethod
    def on_alert_status_changed(alert_id: str) -> list[str]:
        """Patterns to invalidate when alert status changes."""
        return [
            f"alerts:detail:{alert_id}",
            "alerts:list:*",
            "summaries:*",
        ]

    @staticmethod
    def on_camera_updated(camera_id: str) -> list[str]:
        """Patterns to invalidate when a camera is updated."""
        return [
            "cameras:list",
            f"cameras:live:{camera_id}",
            "config:summary",
        ]

    @staticmethod
    def on_person_updated(person_id: str) -> list[str]:
        """Patterns to invalidate when a person is updated."""
        return [
            "people:list",
            "alerts:list:*",  # Person info may appear in alerts
        ]

    @staticmethod
    def on_account_changed() -> list[str]:
        """Patterns to invalidate when accounts change."""
        return [
            "accounts:list",
        ]

    @staticmethod
    def on_config_changed() -> list[str]:
        """Patterns to invalidate when config changes."""
        return [
            "config:summary",
            "ops:capabilities",
            "cameras:list",
        ]


def warmup_critical_caches(services: Any) -> int:
    """
    Warm up critical caches on API startup.

    Args:
        services: RuntimeServices instance

    Returns:
        Number of caches warmed
    """
    cache = get_cache_manager()
    count = 0

    # Camera payloads are role-sensitive, so avoid warming them with an
    # unscoped repository payload here.

    # Warm people list
    try:
        people = services.directory.get_people()
        cache.set(CacheKeyBuilder.people_list(), {"items": people}, CacheTier.CAMERAS)
        count += 1
    except Exception:
        pass

    # Warm config summary
    try:
        config_data = {
            "backend": services.repository.backend_name,
            "cameras_count": len(services.repository.list_cameras()),
        }
        cache.set(CacheKeyBuilder.config_summary(), config_data, CacheTier.CONFIG)
        count += 1
    except Exception:
        pass

    return count


def warm_startup_cache(services: Any):
    """
    Warm cache on application startup.

    Args:
        services: RuntimeServices instance
    """
    try:
        count = warmup_critical_caches(services)
        print(f"Cache warmup: {count} caches preloaded")
    except Exception as e:
        print(f"Cache warmup failed: {e}")
