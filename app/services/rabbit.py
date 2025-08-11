from __future__ import annotations

import asyncio
import json
import os
import secrets
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote

import aio_pika

from app.logging_config import get_logger
from app.services.status_store import (
    STATUS_ENVIADO_SUCESSO,
    STATUS_FALHA_ENVIO_FINAL,
    STATUS_FALHA_FINAL_REPROCESSAMENTO,
    STATUS_FALHA_PROCESSAMENTO_INICIAL,
    STATUS_PROCESSADO_INTERMEDIARIO,
    STATUS_REPROCESSADO_COM_SUCESSO,
    status_store,
)


@dataclass
class QueueNames:
    entrada: str
    retry: str
    validacao: str
    dlq: str


def get_queue_names() -> QueueNames:
    nome = os.getenv("QUEUE_NAMESPACE", "local")
    return QueueNames(
        entrada=f"fila.notificacao.entrada.{nome}",
        retry=f"fila.notificacao.retry.{nome}",
        validacao=f"fila.notificacao.validacao.{nome}",
        dlq=f"fila.notificacao.dlq.{nome}",
    )


class RabbitConnectionManager:
    def __init__(self) -> None:
        self._log = get_logger("vr.rabbit")
        self._url = os.getenv("RABBITMQ_URL")
        if not self._url:
            # Default to local Docker RabbitMQ
            user = os.getenv("RABBITMQ_USER", "guest")
            password = os.getenv("RABBITMQ_PASS", "guest")
            host = os.getenv("RABBITMQ_HOST", "localhost")
            port = os.getenv("RABBITMQ_PORT", "5672")
            vhost = os.getenv("RABBITMQ_VHOST", "/")
            vhost_enc = quote(vhost, safe="")
            self._url = f"amqp://{user}:{password}@{host}:{port}/{vhost_enc}"

        self._connection: Optional[aio_pika.RobustConnection] = None
        self._channel: Optional[aio_pika.RobustChannel] = None
        self._consumer_tasks: list[asyncio.Task] = []

    async def connect(self) -> None:
        self._log.info("Connecting to RabbitMQ %s", self._url)
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        await self._declare_queues()

    async def _declare_queues(self) -> None:
        assert self._channel is not None
        q = get_queue_names()
        # Using classic queues, non-durable is acceptable for this test
        await self._channel.declare_queue(q.entrada, durable=True)
        await self._channel.declare_queue(q.retry, durable=True)
        await self._channel.declare_queue(q.validacao, durable=True)
        await self._channel.declare_queue(q.dlq, durable=True)

    async def start_consumers(self) -> None:
        assert self._channel is not None
        q = get_queue_names()
        # Consumer 1: entry
        await self._channel.set_qos(prefetch_count=10)
        entrada_queue = await self._channel.declare_queue(q.entrada, durable=True)
        self._consumer_tasks.append(
            asyncio.create_task(entrada_queue.consume(_consume_entrada)),
        )

        # Consumer 2: retry
        retry_queue = await self._channel.declare_queue(q.retry, durable=True)
        self._consumer_tasks.append(
            asyncio.create_task(retry_queue.consume(_consume_retry)),
        )

        # Consumer 3: validation
        validacao_queue = await self._channel.declare_queue(q.validacao, durable=True)
        self._consumer_tasks.append(
            asyncio.create_task(validacao_queue.consume(_consume_validacao)),
        )

        # Consumer 4: DLQ
        dlq_queue = await self._channel.declare_queue(q.dlq, durable=True)
        self._consumer_tasks.append(
            asyncio.create_task(dlq_queue.consume(_consume_dlq)),
        )

    async def close(self) -> None:
        for task in self._consumer_tasks:
            task.cancel()
        if self._channel and not self._channel.is_closed:
            self._log.info("Closing channel")
            await self._channel.close()
        if self._connection and not self._connection.is_closed:
            self._log.info("Closing connection")
            await self._connection.close()


_manager_singleton: Optional[RabbitConnectionManager] = None


def get_connection_manager() -> RabbitConnectionManager:
    global _manager_singleton
    if _manager_singleton is None:
        _manager_singleton = RabbitConnectionManager()
    return _manager_singleton


async def publish_to_queue(queue_name: str, message: Dict[str, Any]) -> None:
    manager = get_connection_manager()
    channel = getattr(manager, "_channel", None)
    if channel is None or getattr(channel, "is_closed", False):
        await manager.connect()
    body = json.dumps(message).encode()
    await manager._channel.default_exchange.publish(
        aio_pika.Message(body=body, content_type="application/json"),
        routing_key=queue_name,
    )


# ------------- Secure randomness helpers -------------


def random_chance(threshold: float) -> bool:
    """Return True with probability equal to threshold (0.0 <= threshold <= 1.0).

    Uses secrets for cryptographically secure randomness to satisfy linters.
    """
    if threshold <= 0:
        return False
    if threshold >= 1:
        return True
    # Use 10_000 discrete steps to approximate a float in [0, 1)
    return secrets.randbelow(10_000) < int(threshold * 10_000)


def random_between(min_seconds: float, max_seconds: float) -> float:
    """Return a float in [min_seconds, max_seconds], using secrets."""
    if max_seconds <= min_seconds:
        return float(min_seconds)
    # Work in milliseconds to avoid float bias
    min_ms = int(min_seconds * 1000)
    max_ms = int(max_seconds * 1000)
    span = max_ms - min_ms + 1
    return (min_ms + secrets.randbelow(span)) / 1000.0


# ------------- Consumers implementation -------------


async def _consume_entrada(message: aio_pika.IncomingMessage) -> None:
    async with message.process():
        data = json.loads(message.body)
        trace_id = data["trace_id"]
        # 10-15% random failure
        if random_chance(0.13):
            await status_store.update_status(
                trace_id,
                STATUS_FALHA_PROCESSAMENTO_INICIAL,
            )
            await publish_to_queue(get_queue_names().retry, data)
            return

        # simulate processing 1.0 - 1.5s
        await asyncio.sleep(random_between(1.0, 1.5))
        await status_store.update_status(trace_id, STATUS_PROCESSADO_INTERMEDIARIO)
        await publish_to_queue(get_queue_names().validacao, data)


async def _consume_retry(message: aio_pika.IncomingMessage) -> None:
    async with message.process():
        data = json.loads(message.body)
        trace_id = data["trace_id"]
        await asyncio.sleep(3)
        # 20% failure on retry
        if random_chance(0.2):
            await status_store.update_status(
                trace_id,
                STATUS_FALHA_FINAL_REPROCESSAMENTO,
            )
            await publish_to_queue(get_queue_names().dlq, data)
            return
        await status_store.update_status(trace_id, STATUS_REPROCESSADO_COM_SUCESSO)
        await publish_to_queue(get_queue_names().validacao, data)


async def _consume_validacao(message: aio_pika.IncomingMessage) -> None:
    async with message.process():
        data = json.loads(message.body)
        trace_id = data["trace_id"]
        # simulate sending by type
        await asyncio.sleep(random_between(0.5, 1.0))
        # 5% send failure
        if random_chance(0.05):
            await status_store.update_status(trace_id, STATUS_FALHA_ENVIO_FINAL)
            await publish_to_queue(get_queue_names().dlq, data)
            return
        await status_store.update_status(trace_id, STATUS_ENVIADO_SUCESSO)


async def _consume_dlq(message: aio_pika.IncomingMessage) -> None:
    async with message.process():
        data = json.loads(message.body)
        trace_id = data.get("trace_id")
        # DLQ: just log
        get_logger("vr.dlq").warning(
            "Message routed to DLQ. trace_id=%s payload=%s",
            trace_id,
            data,
        )
