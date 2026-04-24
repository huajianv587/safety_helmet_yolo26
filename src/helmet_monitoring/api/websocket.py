from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


UTC = timezone.utc
TOPICS = ("alerts", "dashboard", "cameras")


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[str, list[WebSocket]] = defaultdict(list)
        self.connection_info: dict[WebSocket, dict[str, Any]] = {}
        self.sequence_by_topic: dict[str, int] = defaultdict(int)
        self.stats = {
            "total_connections": 0,
            "total_messages": 0,
            "total_disconnects": 0,
        }

    async def connect(self, websocket: WebSocket, topic: str = "default", client_id: str | None = None) -> None:
        await websocket.accept()
        self.connections[topic].append(websocket)
        self.connection_info[websocket] = {
            "topic": topic,
            "client_id": client_id,
            "connected_at": datetime.now(tz=UTC).isoformat(),
        }
        self.stats["total_connections"] += 1
        await self.send_personal_message(
            self.envelope(topic, "connected", {"client_id": client_id, "active": len(self.connections[topic])}),
            websocket,
        )

    def disconnect(self, websocket: WebSocket) -> None:
        info = self.connection_info.pop(websocket, None)
        if not info:
            return
        topic = str(info.get("topic") or "default")
        if websocket in self.connections.get(topic, []):
            self.connections[topic].remove(websocket)
        self.stats["total_disconnects"] += 1

    def envelope(self, topic: str, message_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self.sequence_by_topic[topic] += 1
        return {
            "type": message_type,
            "topic": topic,
            "sequence": self.sequence_by_topic[topic],
            "sent_at": datetime.now(tz=UTC).isoformat(),
            "data": data or {},
        }

    async def send_personal_message(self, message: dict[str, Any], websocket: WebSocket) -> None:
        try:
            await websocket.send_json(message)
            self.stats["total_messages"] += 1
        except Exception:
            self.disconnect(websocket)

    async def broadcast(self, topic: str, message_type: str, data: dict[str, Any] | None = None) -> None:
        connections = list(self.connections.get(topic) or [])
        if not connections:
            return
        message = self.envelope(topic, message_type, data)

        async def send(connection: WebSocket) -> WebSocket | None:
            try:
                await connection.send_json(message)
                self.stats["total_messages"] += 1
                return None
            except Exception:
                return connection

        results = await asyncio.gather(*(send(connection) for connection in connections), return_exceptions=True)
        for result in results:
            if isinstance(result, WebSocket):
                self.disconnect(result)

    async def broadcast_all(self, message_type: str, data: dict[str, Any] | None = None) -> None:
        await asyncio.gather(*(self.broadcast(topic, message_type, data) for topic in TOPICS), return_exceptions=True)

    def get_stats(self) -> dict[str, Any]:
        return {
            **self.stats,
            "active_connections": sum(len(items) for items in self.connections.values()),
            "topics": {topic: len(items) for topic, items in self.connections.items()},
            "sequences": dict(self.sequence_by_topic),
        }


_connection_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager


async def broadcast_topic_message(topic: str, message_type: str, data: dict[str, Any] | None = None) -> None:
    await get_connection_manager().broadcast(topic, message_type, data or {})


def dispatch_topic_message(topic: str, message_type: str, data: dict[str, Any] | None = None) -> None:
    coro = broadcast_topic_message(topic, message_type, data or {})
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
    else:  # pragma: no cover - exercised only under running loop
        loop.create_task(coro)


async def broadcast_alert_created(alert: dict[str, Any]) -> None:
    await broadcast_topic_message("alerts", "alert_created", {"alert": alert})


async def broadcast_alert_updated(alert_id: str, updates: dict[str, Any]) -> None:
    await broadcast_topic_message("alerts", "alert_updated", {"alert_id": alert_id, "updates": updates})


async def broadcast_camera_status(camera_id: str, status: str, details: dict[str, Any] | None = None) -> None:
    await broadcast_topic_message("cameras", "camera_status", {"camera_id": camera_id, "status": status, **(details or {})})


async def broadcast_frame_state(camera_id: str, details: dict[str, Any] | None = None) -> None:
    await broadcast_topic_message("cameras", "frame_state", {"camera_id": camera_id, **(details or {})})


async def broadcast_metrics_update(metrics: dict[str, Any]) -> None:
    await broadcast_topic_message("dashboard", "metrics_update", metrics)


async def broadcast_overview_snapshot(payload: dict[str, Any]) -> None:
    await broadcast_topic_message("dashboard", "overview_snapshot", payload)


async def broadcast_queue_update(payload: dict[str, Any]) -> None:
    await broadcast_topic_message("dashboard", "queue_update", payload)


async def broadcast_system_notification(level: str, message: str, details: dict[str, Any] | None = None) -> None:
    await get_connection_manager().broadcast_all("system_notification", {"level": level, "message": message, **(details or {})})


async def _topic_handler(websocket: WebSocket, topic: str, client_id: str | None = None) -> None:
    manager = get_connection_manager()
    await manager.connect(websocket, topic=topic, client_id=client_id)
    try:
        while True:
            await websocket.receive_text()
            await manager.send_personal_message(manager.envelope(topic, "pong", {}), websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def websocket_alerts_handler(websocket: WebSocket, client_id: str | None = None) -> None:
    await _topic_handler(websocket, "alerts", client_id=client_id)


async def websocket_dashboard_handler(websocket: WebSocket, client_id: str | None = None) -> None:
    await _topic_handler(websocket, "dashboard", client_id=client_id)


async def websocket_cameras_handler(websocket: WebSocket, client_id: str | None = None) -> None:
    await _topic_handler(websocket, "cameras", client_id=client_id)
