"""
Asynchronous Notification Tasks

Handles email, SMS, and webhook notifications in background.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from helmet_monitoring.tasks.task_queue import async_task


@async_task(max_retries=3, worker_pool="notify")
def send_email_notification(
    to_email: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
    attachments: Optional[list[str]] = None
) -> dict[str, Any]:
    """
    Send email notification asynchronously.

    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Plain text body
        html_body: HTML body (optional)
        attachments: List of file paths to attach (optional)

    Returns:
        Email sending result
    """
    try:
        from helmet_monitoring.core.config import load_settings
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders
        import os

        settings = load_settings()

        # Create message
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.smtp_user
        msg["To"] = to_email
        msg["Subject"] = subject

        # Add text body
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Add HTML body if provided
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        # Add attachments if provided
        if attachments:
            for file_path in attachments:
                if os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header(
                            "Content-Disposition",
                            f"attachment; filename={os.path.basename(file_path)}"
                        )
                        msg.attach(part)

        # Send email
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)

        return {
            "status": "success",
            "to": to_email,
            "subject": subject,
            "sent_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"[NotificationTask] Email failed: {e}")
        raise


@async_task(max_retries=3, worker_pool="notify")
def send_alert_notification(
    alert_id: str,
    alert_type: str,
    camera_name: str,
    timestamp: str,
    image_url: Optional[str] = None,
    recipients: Optional[list[str]] = None
) -> dict[str, Any]:
    """
    Send alert notification to configured recipients.

    Args:
        alert_id: Alert ID
        alert_type: Type of alert (e.g., "no_helmet")
        camera_name: Camera name
        timestamp: Alert timestamp
        image_url: Evidence image URL (optional)
        recipients: List of recipient emails (optional, uses config if not provided)

    Returns:
        Notification result
    """
    try:
        from helmet_monitoring.core.config import load_settings

        settings = load_settings()

        # Use configured recipients if not provided
        if not recipients:
            recipients = [settings.smtp_user]  # Default to admin email

        # Build email content
        subject = f"🚨 Safety Alert: {alert_type} detected at {camera_name}"

        body = f"""
Safety Alert Notification

Alert ID: {alert_id}
Type: {alert_type}
Camera: {camera_name}
Time: {timestamp}

Please review this alert in the monitoring system.
"""

        html_body = f"""
<html>
<body style="font-family: monospace; background: #0a0e0f; color: #00ff88; padding: 20px;">
    <div style="max-width: 600px; margin: 0 auto; border: 1px solid #00ff88; padding: 20px;">
        <h2 style="color: #00ff88; border-bottom: 1px solid #00ff88; padding-bottom: 10px;">
            🚨 Safety Alert
        </h2>

        <div style="margin: 20px 0;">
            <p><strong>Alert ID:</strong> {alert_id}</p>
            <p><strong>Type:</strong> {alert_type}</p>
            <p><strong>Camera:</strong> {camera_name}</p>
            <p><strong>Time:</strong> {timestamp}</p>
        </div>

        {f'<img src="{image_url}" style="max-width: 100%; border: 1px solid #00ff88;" />' if image_url else ''}

        <p style="margin-top: 20px; color: #888;">
            Please review this alert in the monitoring system.
        </p>
    </div>
</body>
</html>
"""

        # Send to all recipients
        results = []
        for recipient in recipients:
            try:
                result = send_email_notification(recipient, subject, body, html_body)
                results.append({"recipient": recipient, "status": "success"})
            except Exception as e:
                results.append({"recipient": recipient, "status": "failed", "error": str(e)})

        successful = sum(1 for r in results if r["status"] == "success")

        return {
            "status": "completed",
            "alert_id": alert_id,
            "total_recipients": len(recipients),
            "successful": successful,
            "failed": len(recipients) - successful,
            "results": results,
            "sent_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"[NotificationTask] Alert notification failed: {e}")
        raise


@async_task(max_retries=2, worker_pool="notify")
def send_webhook_notification(
    webhook_url: str,
    payload: dict[str, Any],
    headers: Optional[dict[str, str]] = None
) -> dict[str, Any]:
    """
    Send webhook notification.

    Args:
        webhook_url: Webhook URL
        payload: JSON payload
        headers: Optional HTTP headers

    Returns:
        Webhook result
    """
    try:
        import requests

        default_headers = {"Content-Type": "application/json"}
        if headers:
            default_headers.update(headers)

        response = requests.post(
            webhook_url,
            json=payload,
            headers=default_headers,
            timeout=10
        )

        response.raise_for_status()

        return {
            "status": "success",
            "webhook_url": webhook_url,
            "status_code": response.status_code,
            "response": response.text[:200],  # First 200 chars
            "sent_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"[NotificationTask] Webhook failed: {e}")
        raise


@async_task(max_retries=3, worker_pool="notify")
def send_batch_notifications(
    notifications: list[dict[str, Any]],
    notification_type: str = "email"
) -> dict[str, Any]:
    """
    Send batch notifications.

    Args:
        notifications: List of notification configs
        notification_type: Type of notification ("email", "webhook")

    Returns:
        Batch notification result
    """
    results = []
    errors = []

    for notification in notifications:
        try:
            if notification_type == "email":
                result = send_email_notification(**notification)
                results.append(result)
            elif notification_type == "webhook":
                result = send_webhook_notification(**notification)
                results.append(result)
            else:
                errors.append({"notification": notification, "error": f"Unknown type: {notification_type}"})
        except Exception as e:
            errors.append({"notification": notification, "error": str(e)})

    return {
        "status": "completed",
        "total": len(notifications),
        "successful": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
        "processed_at": datetime.now(timezone.utc).isoformat()
    }


@async_task(max_retries=2, worker_pool="notify")
def send_daily_summary(
    recipient: str,
    date: str,
    stats: dict[str, Any]
) -> dict[str, Any]:
    """
    Send daily summary report.

    Args:
        recipient: Recipient email
        date: Report date (YYYY-MM-DD)
        stats: Statistics dictionary

    Returns:
        Summary sending result
    """
    try:
        subject = f"📊 Daily Safety Report - {date}"

        body = f"""
Daily Safety Monitoring Report

Date: {date}

Summary:
- Total Alerts: {stats.get('total_alerts', 0)}
- Pending: {stats.get('pending', 0)}
- Resolved: {stats.get('resolved', 0)}
- False Positives: {stats.get('false_positive', 0)}

Top Cameras:
{chr(10).join(f"- {cam['name']}: {cam['count']} alerts" for cam in stats.get('top_cameras', [])[:5])}

This is an automated report from the Safety Monitoring System.
"""

        html_body = f"""
<html>
<body style="font-family: monospace; background: #0a0e0f; color: #00ff88; padding: 20px;">
    <div style="max-width: 600px; margin: 0 auto; border: 1px solid #00ff88; padding: 20px;">
        <h2 style="color: #00ff88; border-bottom: 1px solid #00ff88; padding-bottom: 10px;">
            📊 Daily Safety Report
        </h2>

        <p><strong>Date:</strong> {date}</p>

        <h3 style="color: #00ff88; margin-top: 20px;">Summary</h3>
        <ul>
            <li>Total Alerts: {stats.get('total_alerts', 0)}</li>
            <li>Pending: {stats.get('pending', 0)}</li>
            <li>Resolved: {stats.get('resolved', 0)}</li>
            <li>False Positives: {stats.get('false_positive', 0)}</li>
        </ul>

        <h3 style="color: #00ff88; margin-top: 20px;">Top Cameras</h3>
        <ul>
            {''.join(f"<li>{cam['name']}: {cam['count']} alerts</li>" for cam in stats.get('top_cameras', [])[:5])}
        </ul>

        <p style="margin-top: 20px; color: #888;">
            This is an automated report from the Safety Monitoring System.
        </p>
    </div>
</body>
</html>
"""

        result = send_email_notification(recipient, subject, body, html_body)

        return {
            "status": "success",
            "recipient": recipient,
            "date": date,
            "sent_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"[NotificationTask] Daily summary failed: {e}")
        raise
