from __future__ import annotations

import smtplib
import uuid
from email.message import EmailMessage

from helmet_monitoring.core.config import AppSettings
from helmet_monitoring.core.schemas import AlertRecord, NotificationLogRecord, utc_now
from helmet_monitoring.storage.repository import AlertRepository


class NotificationService:
    def __init__(self, settings: AppSettings, repository: AlertRepository) -> None:
        self.settings = settings
        self.repository = repository

    def _build_email(self, recipient: str, alert: AlertRecord) -> EmailMessage:
        subject = f"[Safety Alert] {alert.event_no or alert.alert_id} {alert.camera_name} no helmet"
        body = "\n".join(
            [
                f"Event No: {alert.event_no or alert.alert_id}",
                f"Camera: {alert.camera_name}",
                f"Location: {alert.location}",
                f"Department: {alert.department}",
                f"Time: {alert.created_at.isoformat()}",
                f"Person: {alert.person_name}",
                f"Employee ID: {alert.employee_id or 'N/A'}",
                f"Risk: {alert.risk_level}",
                f"Status: {alert.status}",
                f"Snapshot: {alert.snapshot_url or alert.snapshot_path}",
                f"Clip: {alert.clip_url or alert.clip_path or 'pending'}",
            ]
        )
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.notifications.smtp_from_email
        message["To"] = recipient
        message.set_content(body)
        return message

    def _log(self, alert: AlertRecord, recipient: str, subject: str, status: str, error_message: str | None) -> None:
        self.repository.insert_notification_log(
            NotificationLogRecord(
                notification_id=uuid.uuid4().hex,
                alert_id=alert.alert_id,
                event_no=alert.event_no,
                channel="email",
                recipient=recipient,
                subject=subject,
                status=status,
                error_message=error_message,
                payload={
                    "camera_name": alert.camera_name,
                    "location": alert.location,
                    "snapshot_url": alert.snapshot_url,
                    "clip_url": alert.clip_url,
                },
                created_at=utc_now(),
            ).to_record()
        )

    def send_alert_email(self, alert: AlertRecord, recipients: tuple[str, ...]) -> None:
        if not recipients:
            return
        if not (self.settings.notifications.enabled and self.settings.notifications.email_enabled):
            for recipient in recipients:
                self._log(alert, recipient, "email-disabled", "skipped", "Email notifications are disabled.")
            return
        if not self.settings.notifications.is_email_configured:
            for recipient in recipients:
                self._log(alert, recipient, "email-not-configured", "skipped", "SMTP is not configured.")
            return

        for recipient in recipients:
            message = self._build_email(recipient, alert)
            error_message = None
            status = "sent"
            try:
                with smtplib.SMTP(self.settings.notifications.smtp_host, self.settings.notifications.smtp_port, timeout=20) as smtp:
                    if self.settings.notifications.use_tls:
                        smtp.starttls()
                    if self.settings.notifications.smtp_username:
                        smtp.login(
                            self.settings.notifications.smtp_username,
                            self.settings.notifications.smtp_password,
                        )
                    smtp.send_message(message)
            except Exception as exc:  # pragma: no cover
                status = "failed"
                error_message = str(exc)
            self._log(alert, recipient, message["Subject"], status, error_message)

    def send_test_email(self, recipient: str, subject: str, body: str) -> str:
        if not self.settings.notifications.is_email_configured:
            return "SMTP is not configured."
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.notifications.smtp_from_email
        message["To"] = recipient
        message.set_content(body)
        try:
            with smtplib.SMTP(self.settings.notifications.smtp_host, self.settings.notifications.smtp_port, timeout=20) as smtp:
                if self.settings.notifications.use_tls:
                    smtp.starttls()
                if self.settings.notifications.smtp_username:
                    smtp.login(self.settings.notifications.smtp_username, self.settings.notifications.smtp_password)
                smtp.send_message(message)
        except Exception as exc:  # pragma: no cover
            return str(exc)
        return "sent"
