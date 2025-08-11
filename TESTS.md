# Test Suite Documentation

This document explains what our automated tests cover, how they are structured, and how they validate the business requirements of the practical test.

## How to run

```
uv pip install -e .[dev]
uv run pytest
```

The suite runs without a live RabbitMQ server. All messaging I/O is mocked.

## Test architecture and strategy

- We use three layers of tests:
  - Unit test for the publisher function that integrates with RabbitMQ.
  - Endpoint tests for the HTTP API (POST and GET), validating FastAPI validation and in-memory state behavior.
  - Integration-like tests for the asynchronous pipeline (input → retry or validation → final send → success or DLQ) with deterministic randomness and no real sleeps.
- Determinism:
  - Randomness is forced via monkeypatch to hit specific branches.
  - `asyncio.sleep` is monkeypatched to no-op in integration tests to keep the test fast and reproducible.
- Isolation:
  - RabbitMQ connection and publishing are stubbed/mocked to avoid network usage during tests.
  - The app’s lifespan startup is neutralized in endpoint tests by stubbing the connection manager.

## Mapping to business requirements

The practical test requires:

1. HTTP endpoint to accept notifications and enqueue them.
2. In-memory state with `trace_id`, `message_id`, `message_content`, `notification_type`, and status transitions.
3. Asynchronous pipeline with four queues: entrada, retry, validacao, dlq.
4. Random failure rates: entrada (10–15%), retry (20%), final send (5%).
5. DLQ for final failures.
6. GET endpoint for status by `trace_id`.
7. Unit test for publishing logic using mocks.

Our tests cover all of the above, as detailed below.

## Test files and covered scenarios

### 1. Unit: Publisher to RabbitMQ

File: `tests/test_publisher.py`

- Scenario: Publisher serializes payload to JSON and publishes to the correct routing key (queue name).
- Mechanism:
  - `get_connection_manager` is monkeypatched to return a `DummyManager` exposing a `DummyChannel` with a `default_exchange.publish` coroutine.
  - `publish_to_queue("queue.name", payload)` is invoked.
  - Assertions:
    - The captured `routing_key` equals `"queue.name"`.
    - The captured body, when decoded and deserialized, equals the original payload.
- Why this matters:
  - Validates the correctness of the publisher’s contract with RabbitMQ without using a real broker. This is exactly what the test instructions ask for (unit test with mocked messaging library).

### 2. Endpoints: API behavior and in-memory state

File: `tests/test_api_endpoints.py`

- Fixture `client`:

  - Stubs `app.main.get_connection_manager` to avoid starting real RabbitMQ consumers on app startup.
  - Stubs `app.services.rabbit.publish_to_queue` to a no-op to avoid I/O.

- Scenario A: POST `/api/notificar` returns 202 and creates initial state

  - Input: JSON with `message_content` and `notification_type` (no `message_id` on purpose to validate auto-generation).
  - Assertions:
    - HTTP 202 Accepted.
    - Response includes both `message_id` and `trace_id`.
    - In-memory store contains a record for the `trace_id` with:
      - `status == "RECEBIDO"`
      - `notification_type` as provided (e.g., `EMAIL`)
      - `message_content` as provided

- Scenario B: GET `/api/notificacao/status/{trace_id}` for a missing ID returns 404

  - Assertions:
    - HTTP 404 Not Found when `trace_id` does not exist in memory.

- Why this matters:
  - Validates request validation (via Pydantic), ID generation, and that the system initializes the in-memory state exactly as required by the test.

### 3. Integration-like: Full pipeline (success and DLQ)

File: `tests/test_integration_pipeline.py`

- Shared Test Utilities:

  - `FakeIncomingMessage`: Mimics `aio_pika.IncomingMessage` with a `process()` async context manager like the real one.
  - `asyncio.sleep` is monkeypatched to no-op.
  - `publish_to_queue` is monkeypatched to synchronously route messages to the next consumer function, emulating the broker’s routing.

- Scenario C: Full success path ends in `ENVIADO_SUCESSO`

  - Setup:
    - Create initial state in memory for a fixed `trace_id` and `message_id`.
    - Force `random_chance` to return `[False, False]`:
      - entrada → no failure (threshold not met).
      - final send → no failure (threshold not met).
    - Intercept `publish_to_queue` to call `_consume_validacao` when `validacao` queue is the target.
  - Action:
    - Call `_consume_entrada` with the initial message.
  - Assertions:
    - Final in-memory status equals `ENVIADO_SUCESSO` for the `trace_id`.

- Scenario D: Failure path ends in DLQ with `FALHA_FINAL_REPROCESSAMENTO`

  - Setup:
    - Create initial state in memory for a fixed `trace_id` and `message_id`.
    - Force `random_chance` to return `[True, True]`:
      - entrada → failure (within 10–15%) → message goes to `retry`.
      - retry → failure (20%) → message goes to `dlq`.
    - Intercept `publish_to_queue` to call `_consume_retry` for `retry` and `_consume_dlq` for `dlq`.
  - Action:
    - Call `_consume_entrada` with the initial message.
  - Assertions:
    - Final in-memory status equals `FALHA_FINAL_REPROCESSAMENTO` for the `trace_id`.

- Why this matters:
  - Demonstrates the message lifecycle through all required stages without external dependencies, while accurately reflecting the branching logic and status transitions mandated by the test.

## What is intentionally not covered (yet)

- 422 validation errors (e.g., invalid `notification_type`, missing fields). These are handled by FastAPI/Pydantic and can be added if needed.
- DLQ path specifically caused by final send failure (5%), rather than retry failure. The current DLQ test covers the retry-fail path; a send-fail path test can be added.
- Status checks for intermediate states (e.g., `PROCESSADO_INTERMEDIARIO`, `REPROCESSADO_COM_SUCESSO`) via GET. The pipeline tests do pass through those states, but we assert only final states.
- PUSH notification type is not explicitly asserted (EMAIL and SMS are exercised via payloads), but the logic is symmetric across types.

## Principles and best practices

- Tests are small, focused, and isolated (KISS, SRP from SOLID).
- Reuse common stubbing patterns (DRY) and keep deterministic control over time and randomness.
- Avoid side effects and network dependencies in tests to keep them fast and reliable.
- Validate both contract (publisher) and behavior (endpoints, status, pipeline).

## Summary

The suite validates the full set of requirements from the assignment: endpoints, in-memory state tracking, message publishing, multi-stage asynchronous processing with retries and DLQ, and the mandated unit test around publishing using mocks. It is deterministic, fast, and runs completely offline.
