from __future__ import annotations

import smtplib
import uuid
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from helmet_monitoring.core.config import AppSettings
from helmet_monitoring.core.schemas import AlertRecord, NotificationLogRecord, utc_now
from helmet_monitoring.storage.repository import AlertRepository


class NotificationService:
    def __init__(self, settings: AppSettings, repository: AlertRepository) -> None:
        self.settings = settings
        self.repository = repository

    def _value(self, alert: AlertRecord | dict[str, Any], field_name: str, default: Any = "") -> Any:
        if isinstance(alert, dict):
            return alert.get(field_name, default)
        return getattr(alert, field_name, default)

    def _created_at(self, alert: AlertRecord | dict[str, Any]) -> datetime:
        value = self._value(alert, "created_at", utc_now())
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return utc_now()

    def _build_email(self, recipient: str, alert: AlertRecord | dict[str, Any]) -> EmailMessage:
        event_no = self._value(alert, "event_no") or self._value(alert, "alert_id")
        subject = f"[Safety Alert] {event_no} {self._value(alert, 'camera_name')} no helmet"
        body = "\n".join(
            [
                f"Event No: {event_no}",
                f"Camera: {self._value(alert, 'camera_name')}",
                f"Location: {self._value(alert, 'location')}",
                f"Department: {self._value(alert, 'department')}",
                f"Time: {self._created_at(alert).isoformat()}",
                f"Person: {self._value(alert, 'person_name')}",
                f"Employee ID: {self._value(alert, 'employee_id') or 'N/A'}",
                f"Risk: {self._value(alert, 'risk_level')}",
                f"Status: {self._value(alert, 'status')}",
                f"Snapshot: {self._value(alert, 'snapshot_url') or self._value(alert, 'snapshot_path')}",
                f"Clip: {self._value(alert, 'clip_url') or self._value(alert, 'clip_path') or 'pending'}",
            ]
        )
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.notifications.smtp_from_email or self.settings.notifications.smtp_username or "no-reply@localhost"
        message["To"] = recipient
        message.set_content(body)
        return message

    def _log(
        self,
        alert: AlertRecord | dict[str, Any],
        recipient: str,
        subject: str,
        status: str,
        error_message: str | None,
        *,
        payload_extra: dict | None = None,
    ) -> None:
        payload = {
            "camera_name": self._value(alert, "camera_name"),
            "location": self._value(alert, "location"),
            "snapshot_url": self._value(alert, "snapshot_url"),
            "clip_url": self._value(alert, "clip_url"),
        }
        if payload_extra:
            payload.update(payload_extra)
        self.repository.insert_notification_log(
            NotificationLogRecord(
                notification_id=uuid.uuid4().hex,
                alert_id=str(self._value(alert, "alert_id")),
                event_no=self._value(alert, "event_no"),
                channel="email",
                recipient=recipient,
                subject=subject,
                status=status,
                error_message=error_message,
                payload=payload,
                created_at=utc_now(),
            ).to_record()
        )

    def simulate_alert_email(self, alert: AlertRecord | dict[str, Any], recipients: tuple[str, ...], *, reason: str = "dry_run") -> None:
        for recipient in recipients:
            message = self._build_email(recipient, alert)
            body_preview = "\n".join(str(message.get_content()).splitlines()[:4])
            self._log(
                alert,
                recipient,
                message["Subject"],
                "dry_run",
                f"Notification dry-run verified without SMTP delivery ({reason}).",
                payload_extra={
                    "mode": reason,
                    "body_preview": body_preview,
                    "from_email": message["From"],
                },
            )

    def send_alert_email(self, alert: AlertRecord | dict[str, Any], recipients: tuple[str, ...]) -> None:
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
