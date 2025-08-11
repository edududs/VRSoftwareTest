import uuid

from fastapi import APIRouter, HTTPException

from app.models.schemas import NotificationAccepted, NotificationIn, NotificationStatus
from app.services.rabbit import get_queue_names, publish_to_queue
from app.services.status_store import status_store

router = APIRouter()


@router.post("/notificar", response_model=NotificationAccepted, status_code=202)
async def notificar(payload: NotificationIn) -> NotificationAccepted:
    trace_id = str(uuid.uuid4())
    mensagem_id = payload.message_id or str(uuid.uuid4())

    # Persist initial state in memory
    status_store.create_initial(
        trace_id=trace_id,
        mensagem_id=mensagem_id,
        conteudo=payload.message_content,
        tipo=payload.notification_type,
    )

    # Publish to entrada queue
    queue_names = get_queue_names()
    await publish_to_queue(
        queue_names.entrada,
        {
            "trace_id": trace_id,
            "message_id": mensagem_id,
            "message_content": payload.message_content,
            "notification_type": payload.notification_type,
        },
    )

    return NotificationAccepted(message_id=mensagem_id, trace_id=trace_id)


@router.get("/notificacao/status/{trace_id}", response_model=NotificationStatus)
async def obter_status(trace_id: str) -> NotificationStatus:
    status = status_store.get(trace_id)
    if status is None:
        raise HTTPException(status_code=404, detail="trace_id não encontrado")
    return status
