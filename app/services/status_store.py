from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional

from app.models.schemas import NotificationStatus, NotificationType

INITIAL_STATUS = "RECEBIDO"
STATUS_PROCESSADO_INTERMEDIARIO = "PROCESSADO_INTERMEDIARIO"
STATUS_FALHA_PROCESSAMENTO_INICIAL = "FALHA_PROCESSAMENTO_INICIAL"
STATUS_REPROCESSADO_COM_SUCESSO = "REPROCESSADO_COM_SUCESSO"
STATUS_FALHA_FINAL_REPROCESSAMENTO = "FALHA_FINAL_REPROCESSAMENTO"
STATUS_FALHA_ENVIO_FINAL = "FALHA_ENVIO_FINAL"
STATUS_ENVIADO_SUCESSO = "ENVIADO_SUCESSO"


@dataclass
class NotificationRecord:
    trace_id: str
    mensagem_id: str
    conteudo: str
    tipo: NotificationType
    status: str


class InMemoryStatusStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._store: Dict[str, NotificationRecord] = {}

    async def _set(self, record: NotificationRecord) -> None:
        async with self._lock:
            self._store[record.trace_id] = record

    def create_initial(
        self,
        trace_id: str,
        mensagem_id: str,
        conteudo: str,
        tipo: NotificationType,
    ) -> None:
        # sync path for API fast write; protected by GIL for dict set
        self._store[trace_id] = NotificationRecord(
            trace_id=trace_id,
            mensagem_id=mensagem_id,
            conteudo=conteudo,
            tipo=tipo,
            status=INITIAL_STATUS,
        )

    async def update_status(self, trace_id: str, new_status: str) -> None:
        async with self._lock:
            record = self._store.get(trace_id)
            if record is None:
                return
            record.status = new_status
            self._store[trace_id] = record

    def get(self, trace_id: str) -> Optional[NotificationStatus]:
        record = self._store.get(trace_id)
        if record is None:
            return None
        return NotificationStatus(
            trace_id=record.trace_id,
            message_id=record.mensagem_id,
            message_content=record.conteudo,
            notification_type=record.tipo,
            status=record.status,
        )


status_store = InMemoryStatusStore()
