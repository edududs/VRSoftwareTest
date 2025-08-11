from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Iterator

import pytest


class FakeIncomingMessage:
    def __init__(self, body: bytes) -> None:
        self.body = body

    class _Proc:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def process(self):
        return self._Proc()


@pytest.mark.asyncio
async def test_full_pipeline_success(monkeypatch):
    # Arrange
    from app.services import rabbit as rabbit_mod
    from app.services.status_store import (
        STATUS_ENVIADO_SUCESSO,
        status_store,
    )

    trace_id = "t-success"
    mensagem_id = "m-success"
    payload: Dict[str, Any] = {
        "trace_id": trace_id,
        "message_id": mensagem_id,
        "message_content": "hello",
        "notification_type": "EMAIL",
    }
    status_store.create_initial(trace_id, mensagem_id, "hello", "EMAIL")

    # Make sleeps instant
    async def no_sleep(_: float):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    # Force random path using secure helpers: entrada success, validacao success
    seq: Iterator[bool] = iter([False, False])  # False => no failure
    monkeypatch.setattr(rabbit_mod, "random_chance", lambda _: next(seq))

    # Route publish to the next consumer
    async def route_publish(queue: str, message: Dict[str, Any]) -> None:
        body = json.dumps(message).encode()
        if queue == rabbit_mod.get_queue_names().validacao:
            await rabbit_mod._consume_validacao(FakeIncomingMessage(body))
        elif queue == rabbit_mod.get_queue_names().retry:
            await rabbit_mod._consume_retry(FakeIncomingMessage(body))
        elif queue == rabbit_mod.get_queue_names().dlq:
            await rabbit_mod._consume_dlq(FakeIncomingMessage(body))

    monkeypatch.setattr(rabbit_mod, "publish_to_queue", route_publish)

    # Act: start at entrada
    await rabbit_mod._consume_entrada(FakeIncomingMessage(json.dumps(payload).encode()))

    # Assert
    status = status_store.get(trace_id)
    assert status is not None
    assert status.status == STATUS_ENVIADO_SUCESSO


@pytest.mark.asyncio
async def test_full_pipeline_to_dlq(monkeypatch):
    # Arrange
    from app.services import rabbit as rabbit_mod
    from app.services.status_store import (
        STATUS_FALHA_FINAL_REPROCESSAMENTO,
        status_store,
    )

    trace_id = "t-dlq"
    mensagem_id = "m-dlq"
    payload: Dict[str, Any] = {
        "trace_id": trace_id,
        "message_id": mensagem_id,
        "message_content": "bye",
        "notification_type": "SMS",
    }
    status_store.create_initial(trace_id, mensagem_id, "bye", "SMS")

    # Make sleeps instant
    async def no_sleep(_: float):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    # Force random path using secure helpers: entrada fail, retry fail
    seq: Iterator[bool] = iter([True, True])  # True => failure
    monkeypatch.setattr(rabbit_mod, "random_chance", lambda _: next(seq))

    # Route publish to next consumer
    async def route_publish(queue: str, message: Dict[str, Any]) -> None:
        body = json.dumps(message).encode()
        if queue == rabbit_mod.get_queue_names().validacao:
            await rabbit_mod._consume_validacao(FakeIncomingMessage(body))
        elif queue == rabbit_mod.get_queue_names().retry:
            await rabbit_mod._consume_retry(FakeIncomingMessage(body))
        elif queue == rabbit_mod.get_queue_names().dlq:
            await rabbit_mod._consume_dlq(FakeIncomingMessage(body))

    monkeypatch.setattr(rabbit_mod, "publish_to_queue", route_publish)

    # Act: start at entrada
    await rabbit_mod._consume_entrada(FakeIncomingMessage(json.dumps(payload).encode()))

    # Assert
    status = status_store.get(trace_id)
    assert status is not None
    assert status.status == STATUS_FALHA_FINAL_REPROCESSAMENTO
