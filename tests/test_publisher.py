import json
from typing import Any, Dict

import pytest


@pytest.mark.asyncio
async def test_publish_to_queue_monkeypatch(monkeypatch):
    # Lazy import to avoid importing aio-pika during collection
    from app.services import rabbit as rabbit_mod

    published: Dict[str, Any] = {}

    class DummyChannel:
        class DummyExchange:
            async def publish(self, msg, routing_key: str):
                published["routing_key"] = routing_key
                published["body"] = msg.body

        default_exchange = DummyExchange()

    class DummyManager:
        def __init__(self) -> None:
            self._channel = DummyChannel()

    monkeypatch.setattr(rabbit_mod, "get_connection_manager", lambda: DummyManager())

    payload = {"trace_id": "t1", "message_id": "m1"}
    await rabbit_mod.publish_to_queue("queue.name", payload)

    assert published["routing_key"] == "queue.name"
    assert json.loads(published["body"].decode()) == payload
