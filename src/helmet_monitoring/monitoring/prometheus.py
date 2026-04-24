"""
Prometheus Metrics Integration

Provides performance metrics for monitoring and alerting.
"""

from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST
from functools import wraps
import time
from typing import Callable, Any


# ============================================================================
# API Metrics
# ============================================================================

# Request counters
api_requests_total = Counter(
    'api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status']
)

api_request_duration_seconds = Histogram(
    'api_request_duration_seconds',
    'API request duration in seconds',
    ['method', 'endpoint'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0)
)

api_request_size_bytes = Histogram(
    'api_request_size_bytes',
    'API request size in bytes',
    ['method', 'endpoint'],
    buckets=(100, 1000, 10000, 100000, 1000000)
)

api_response_size_bytes = Histogram(
    'api_response_size_bytes',
    'API response size in bytes',
    ['method', 'endpoint'],
    buckets=(100, 1000, 10000, 100000, 1000000)
)

# ============================================================================
# Cache Metrics
# ============================================================================

cache_hits_total = Counter(
    'cache_hits_total',
    'Total cache hits',
    ['tier']
)

cache_misses_total = Counter(
    'cache_misses_total',
    'Total cache misses',
    ['tier']
)

cache_size_entries = Gauge(
    'cache_size_entries',
    'Number of entries in cache',
    ['tier']
)

cache_hit_rate = Gauge(
    'cache_hit_rate',
    'Cache hit rate (0-1)',
    ['tier']
)

# ============================================================================
# Database Metrics
# ============================================================================

db_query_duration_seconds = Histogram(
    'db_query_duration_seconds',
    'Database query duration in seconds',
    ['operation', 'table'],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0)
)

db_queries_total = Counter(
    'db_queries_total',
    'Total database queries',
    ['operation', 'table', 'status']
)

db_connection_pool_size = Gauge(
    'db_connection_pool_size',
    'Database connection pool size'
)

db_connection_pool_active = Gauge(
    'db_connection_pool_active',
    'Active database connections'
)

# ============================================================================
# Alert Metrics
# ============================================================================

alerts_created_total = Counter(
    'alerts_created_total',
    'Total alerts created',
    ['camera_id', 'alert_type']
)

alerts_by_status = Gauge(
    'alerts_by_status',
    'Number of alerts by status',
    ['status']
)

alert_processing_duration_seconds = Histogram(
    'alert_processing_duration_seconds',
    'Alert processing duration in seconds',
    ['stage'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
)

# ============================================================================
# Task Queue Metrics
# ============================================================================

task_queue_size = Gauge(
    'task_queue_size',
    'Number of tasks in queue'
)

task_queue_workers = Gauge(
    'task_queue_workers',
    'Number of active workers'
)

tasks_total = Counter(
    'tasks_total',
    'Total tasks submitted',
    ['task_type', 'status']
)

task_duration_seconds = Histogram(
    'task_duration_seconds',
    'Task execution duration in seconds',
    ['task_type'],
    buckets=(0.1, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0)
)

# ============================================================================
# WebSocket Metrics
# ============================================================================

websocket_connections_active = Gauge(
    'websocket_connections_active',
    'Active WebSocket connections',
    ['topic']
)

websocket_messages_total = Counter(
    'websocket_messages_total',
    'Total WebSocket messages sent',
    ['topic', 'message_type']
)

# Optimization: Add WebSocket broadcast latency metric
websocket_broadcast_duration_seconds = Histogram(
    'websocket_broadcast_duration_seconds',
    'WebSocket broadcast duration in seconds',
    ['topic'],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0)
)

websocket_message_latency_seconds = Histogram(
    'websocket_message_latency_seconds',
    'WebSocket message end-to-end latency in seconds',
    ['topic'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0)
)

# ============================================================================
# Cache Optimization Metrics (New)
# ============================================================================

cache_invalidation_duration_seconds = Histogram(
    'cache_invalidation_duration_seconds',
    'Cache invalidation duration in seconds',
    ['tier', 'pattern'],
    buckets=(0.0001, 0.001, 0.005, 0.01, 0.05, 0.1)
)

cache_operation_duration_seconds = Histogram(
    'cache_operation_duration_seconds',
    'Cache operation duration in seconds',
    ['operation', 'tier'],
    buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05)
)

# ============================================================================
# Repository Lock Metrics (New)
# ============================================================================

repository_lock_wait_seconds = Histogram(
    'repository_lock_wait_seconds',
    'Repository lock wait time in seconds',
    ['operation', 'resource'],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0)
)

repository_lock_held_seconds = Histogram(
    'repository_lock_held_seconds',
    'Repository lock held time in seconds',
    ['operation', 'resource'],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0)
)

# ============================================================================
# Frame Processing Metrics (New)
# ============================================================================

frame_processing_duration_seconds = Histogram(
    'frame_processing_duration_seconds',
    'Frame processing duration in seconds',
    ['camera_id', 'stage'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0)
)

frame_copy_operations_total = Counter(
    'frame_copy_operations_total',
    'Total frame copy operations',
    ['camera_id', 'purpose']
)

frame_resize_operations_total = Counter(
    'frame_resize_operations_total',
    'Total frame resize operations',
    ['camera_id']
)

# ============================================================================
# System Metrics
# ============================================================================

system_info = Info(
    'system_info',
    'System information'
)

application_uptime_seconds = Gauge(
    'application_uptime_seconds',
    'Application uptime in seconds'
)

# ============================================================================
# Decorator for Automatic Instrumentation
# ============================================================================

def track_api_request(endpoint: str):
    """
    Decorator to track API request metrics.

    Usage:
        @track_api_request("/api/v1/alerts")
        def list_alerts():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            method = "GET"  # Default, can be extracted from request
            start_time = time.time()

            try:
                result = await func(*args, **kwargs)
                status = "200"
                return result
            except Exception as e:
                status = "500"
                raise
            finally:
                duration = time.time() - start_time
                api_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
                api_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            method = "GET"
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                status = "200"
                return result
            except Exception as e:
                status = "500"
                raise
            finally:
                duration = time.time() - start_time
                api_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
                api_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)

        # Return appropriate wrapper based on function type
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def track_db_query(operation: str, table: str):
    """
    Decorator to track database query metrics.

    Usage:
        @track_db_query("select", "alerts")
        def list_alerts():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                status = "success"
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.time() - start_time
                db_queries_total.labels(operation=operation, table=table, status=status).inc()
                db_query_duration_seconds.labels(operation=operation, table=table).observe(duration)

        return wrapper
    return decorator


def track_task_execution(task_type: str):
    """
    Decorator to track background task metrics.

    Usage:
        @track_task_execution("file_upload")
        def upload_file():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                status = "success"
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.time() - start_time
                tasks_total.labels(task_type=task_type, status=status).inc()
                task_duration_seconds.labels(task_type=task_type).observe(duration)

        return wrapper
    return decorator


# ============================================================================
# Metrics Update Functions
# ============================================================================

def update_cache_metrics(cache_stats: dict[str, Any]):
    """
    Update cache metrics from cache manager stats.

    Args:
        cache_stats: Cache statistics dictionary
    """
    for tier, stats in cache_stats.items():
        if isinstance(stats, dict):
            hits = stats.get('hits', 0)
            misses = stats.get('misses', 0)
            total = hits + misses

            cache_hits_total.labels(tier=tier).inc(hits)
            cache_misses_total.labels(tier=tier).inc(misses)
            cache_size_entries.labels(tier=tier).set(stats.get('entries', 0))

            if total > 0:
                hit_rate = hits / total
                cache_hit_rate.labels(tier=tier).set(hit_rate)


def update_alert_metrics(alert_stats: dict[str, Any]):
    """
    Update alert metrics from alert statistics.

    Args:
        alert_stats: Alert statistics dictionary
    """
    for status, count in alert_stats.get('by_status', {}).items():
        alerts_by_status.labels(status=status).set(count)


def update_task_queue_metrics(queue_stats: dict[str, Any]):
    """
    Update task queue metrics from queue statistics.

    Args:
        queue_stats: Queue statistics dictionary
    """
    task_queue_size.set(queue_stats.get('queue_size', 0))
    task_queue_workers.set(queue_stats.get('workers', 0))


def update_websocket_metrics(ws_stats: dict[str, Any]):
    """
    Update WebSocket metrics from connection manager stats.

    Args:
        ws_stats: WebSocket statistics dictionary
    """
    for topic, count in ws_stats.get('topics', {}).items():
        websocket_connections_active.labels(topic=topic).set(count)


# ============================================================================
# Metrics Endpoint
# ============================================================================

def get_metrics() -> tuple[bytes, str]:
    """
    Get Prometheus metrics in text format.

    Returns:
        Tuple of (metrics_bytes, content_type)
    """
    return generate_latest(), CONTENT_TYPE_LATEST
