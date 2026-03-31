from __future__ import annotations

import uuid

from helmet_monitoring.core.schemas import AlertActionRecord, HardCaseRecord, utc_now
from helmet_monitoring.storage.repository import AlertRepository


class AlertWorkflowService:
    def __init__(self, repository: AlertRepository) -> None:
        self.repository = repository

    def _append_action(
        self,
        alert: dict,
        *,
        action_type: str,
        actor: str,
        actor_role: str,
        note: str | None,
        payload: dict | None = None,
    ) -> None:
        self.repository.append_alert_action(
            AlertActionRecord(
                action_id=uuid.uuid4().hex,
                alert_id=alert["alert_id"],
                event_no=alert.get("event_no"),
                action_type=action_type,
                actor=actor,
                actor_role=actor_role,
                note=note,
                payload=payload or {},
                created_at=utc_now(),
            ).to_record()
        )
        self.repository.insert_audit_log(
            {
                "audit_id": uuid.uuid4().hex,
                "entity_type": "alert",
                "entity_id": alert["alert_id"],
                "action_type": action_type,
                "actor": actor,
                "actor_role": actor_role,
                "payload": payload or {},
                "created_at": utc_now().isoformat(),
            }
        )

    def assign(self, alert: dict, *, actor: str, actor_role: str, assignee: str, assignee_email: str, note: str | None) -> None:
        self.repository.update_alert(
            alert["alert_id"],
            {
                "status": "assigned",
                "assigned_to": assignee,
                "assigned_email": assignee_email,
                "resolution_note": note,
            },
        )
        self._append_action(
            alert,
            action_type="assign",
            actor=actor,
            actor_role=actor_role,
            note=note,
            payload={"assigned_to": assignee, "assigned_email": assignee_email},
        )

    def update_status(
        self,
        alert: dict,
        *,
        actor: str,
        actor_role: str,
        new_status: str,
        note: str | None,
        corrected_identity: dict | None = None,
        remediation_snapshot_path: str | None = None,
        remediation_snapshot_url: str | None = None,
    ) -> None:
        now = utc_now()
        update_payload = {
            "status": new_status,
            "handled_by": actor,
            "handled_at": now.isoformat(),
            "resolution_note": note,
            "remediation_snapshot_path": remediation_snapshot_path,
            "remediation_snapshot_url": remediation_snapshot_url,
        }
        if new_status in {"remediated", "ignored", "false_positive"}:
            update_payload["closed_at"] = now.isoformat()
        if new_status == "false_positive":
            update_payload["false_positive"] = True
        if corrected_identity:
            update_payload.update(corrected_identity)

        self.repository.update_alert(alert["alert_id"], update_payload)
        self._append_action(
            alert,
            action_type=new_status,
            actor=actor,
            actor_role=actor_role,
            note=note,
            payload=corrected_identity or {},
        )

        if new_status == "false_positive":
            self.repository.insert_hard_case(
                HardCaseRecord(
                    case_id=uuid.uuid4().hex,
                    alert_id=alert["alert_id"],
                    event_no=alert.get("event_no"),
                    case_type="false_positive",
                    snapshot_path=alert.get("snapshot_path"),
                    snapshot_url=alert.get("snapshot_url"),
                    clip_path=alert.get("clip_path"),
                    clip_url=alert.get("clip_url"),
                    note=note,
                    created_at=now,
                ).to_record()
            )
