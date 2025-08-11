from __future__ import annotations

import uuid
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch) -> TestClient:
    # Avoid real RabbitMQ connection during app startup
    from app import main as app_main

    class DummyManager:
        async def connect(self) -> None:  # pragma: no cover
            return None

        async def start_consumers(self) -> None:  # pragma: no cover
            return None

        async def close(self) -> None:  # pragma: no cover
            return None

    monkeypatch.setattr(app_main, "get_connection_manager", lambda: DummyManager())

    # Also stub publish to avoid sending anything
    from app.api import routes as routes_mod
    from app.services import rabbit as rabbit_mod

    async def dummy_publish(queue: str, message: Dict[str, Any]) -> None:
        return None

    # Patch both the rabbit module and the name imported into routes
    monkeypatch.setattr(rabbit_mod, "publish_to_queue", dummy_publish)
    monkeypatch.setattr(routes_mod, "publish_to_queue", dummy_publish)

    return TestClient(app_main.app)


def test_post_notificar_creates_trace_and_status(client: TestClient):
    payload = {"message_content": "hello", "notification_type": "EMAIL"}
    resp = client.post("/api/notificar", json=payload)
    assert resp.status_code == 202
    data = resp.json()
    assert "message_id" in data and "trace_id" in data
    trace_id = data["trace_id"]

    # Check status in memory
    from app.services.status_store import INITIAL_STATUS, status_store

    status = status_store.get(trace_id)
    assert status is not None
    assert status.status == INITIAL_STATUS
    assert status.notification_type == "EMAIL"
    assert status.message_content == "hello"


def test_get_status_not_found(client: TestClient):
    missing = str(uuid.uuid4())
    resp = client.get(f"/api/notificacao/status/{missing}")
    assert resp.status_code == 404
