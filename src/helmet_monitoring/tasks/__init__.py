"""
Task System Initialization

Provides unified interface for background task management.
"""

from helmet_monitoring.tasks.task_queue import (
    get_task_queue,
    submit_task,
    get_task_status,
    get_queue_stats,
    async_task
)

from helmet_monitoring.tasks.file_tasks import (
    upload_evidence_to_storage,
    generate_thumbnail,
    compress_video,
    cleanup_old_files,
    batch_process_images
)

from helmet_monitoring.tasks.notification_tasks import (
    send_email_notification,
    send_alert_notification,
    send_webhook_notification,
    send_batch_notifications,
    send_daily_summary
)


__all__ = [
    # Core task queue
    "get_task_queue",
    "submit_task",
    "get_task_status",
    "get_queue_stats",
    "async_task",

    # File tasks
    "upload_evidence_to_storage",
    "generate_thumbnail",
    "compress_video",
    "cleanup_old_files",
    "batch_process_images",

    # Notification tasks
    "send_email_notification",
    "send_alert_notification",
    "send_webhook_notification",
    "send_batch_notifications",
    "send_daily_summary",
]


def init_task_system():
    """
    Initialize task system on application startup.

    Call this in create_app() to start background workers.
    """
    queue = get_task_queue()
    print(f"[TaskSystem] Initialized with {queue.num_workers} workers")
    return queue


def shutdown_task_system():
    """
    Shutdown task system gracefully.

    Call this on application shutdown.
    """
    queue = get_task_queue()
    queue.stop()
    print("[TaskSystem] Shutdown complete")
