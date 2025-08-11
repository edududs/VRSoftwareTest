VRSoftwareTest — Asynchronous Notification System (FastAPI + RabbitMQ)

Description
This project implements an asynchronous notification backend using FastAPI. It accepts notification requests, publishes them to RabbitMQ, and processes them through multiple steps (entry → retry → validation/send → success/DLQ). State is kept in-memory and there is a status endpoint for tracking.

Stack

- FastAPI, Uvicorn
- RabbitMQ (CloudAMQP)
- aio-pika (async client)
- Pydantic v2
- pytest (unit/integration tests)

Architecture

- `app/main.py`: FastAPI app and startup/shutdown
- `app/api/routes.py`: HTTP routes
- `app/models/schemas.py`: Pydantic models (request/response)
- `app/services/status_store.py`: in-memory status storage
- `app/services/rabbit.py`: RabbitMQ connection, publishing and consumers
- `tests/`: pytest suites with aio-pika mocks

Queues

- `fila.notificacao.entrada.[SEU-NOME]`
- `fila.notificacao.retry.[SEU-NOME]`
- `fila.notificacao.validacao.[SEU-NOME]`
- `fila.notificacao.dlq.[SEU-NOME]`

Configuration
Create a `.env` file at project root with RabbitMQ credentials (local Docker by default):

```
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
QUEUE_NAMESPACE=local
```

How to run (with uv)

1. Install dependencies (Python 3.10+)

```
uv pip install -e .[dev]
```

2. Start the API (consumers start on app startup)

```
uv run uvicorn app.main:app --reload
```

Endpoints

- POST `/api/notificar`
- GET `/api/notificacao/status/{trace_id}`

Tests

```
uv run pytest
```

Test coverage details

- See [TESTS.md](./TESTS.md) for a detailed description of all scenarios covered by the automated tests.

Notes

- State persists only in memory
- All consumers reuse a single RabbitMQ connection/channel (singleton)
