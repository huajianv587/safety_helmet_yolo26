from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helmet_monitoring.api.app import app
from helmet_monitoring.api.websocket import dispatch_topic_message


def test_alerts_websocket_receives_connected_envelope_and_broadcast() -> None:
    client = TestClient(app)
    with client.websocket_connect("/ws/alerts") as websocket:
        connected = websocket.receive_json()
        assert connected["topic"] == "alerts"
        assert connected["type"] == "connected"
        assert "sequence" in connected

        dispatch_topic_message("alerts", "alert_created", {"alert_id": "alert-test-001"})
        payload = websocket.receive_json()
        assert payload["topic"] == "alerts"
        assert payload["type"] == "alert_created"
        assert payload["data"]["alert_id"] == "alert-test-001"

        websocket.send_text("ping")
        pong = websocket.receive_json()
        assert pong["topic"] == "alerts"
        assert pong["type"] == "pong"
