"""Task queue adapters.

``InlineTaskQueue`` keeps the old callable-based MVP path deterministic. ``InMemoryMessageQueue``
models the message/ack/fail/DLQ semantics the SQS ingestion worker uses, without requiring
LocalStack in the fast test suite.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable

from raku_rag.interfaces.base import TaskQueue


class InlineTaskQueue(TaskQueue):
    def enqueue(self, fn: Callable[..., object], *args, **kwargs) -> object:
        return fn(*args, **kwargs)


@dataclass(frozen=True)
class QueueEnvelope:
    message_id: str
    receipt_handle: str
    body: dict
    receive_count: int = 1


@dataclass
class _QueuedMessage:
    message_id: str
    body: dict
    receive_count: int = 0
    last_error: str = ""


@dataclass
class InMemoryMessageQueue:
    """Small SQS-like queue for Tier C contract tests.

    Messages are explicitly acked. ``fail`` either requeues the message or moves it to the DLQ once
    ``max_receive_count`` is reached, mirroring the operational contract of SQS redrive policies.
    """

    max_receive_count: int = 3
    _seq: itertools.count = field(default_factory=lambda: itertools.count(1), init=False)
    _available: list[_QueuedMessage] = field(default_factory=list, init=False)
    _inflight: dict[str, _QueuedMessage] = field(default_factory=dict, init=False)
    _dlq: list[_QueuedMessage] = field(default_factory=list, init=False)

    def enqueue_message(self, body: dict) -> str:
        message_id = f"msg_{next(self._seq)}"
        self._available.append(_QueuedMessage(message_id=message_id, body=dict(body)))
        return message_id

    def receive(self, max_messages: int = 1) -> list[QueueEnvelope]:
        envelopes: list[QueueEnvelope] = []
        for _ in range(max_messages):
            if not self._available:
                break
            queued = self._available.pop(0)
            queued.receive_count += 1
            receipt = f"rh_{queued.message_id}_{queued.receive_count}"
            self._inflight[receipt] = queued
            envelopes.append(
                QueueEnvelope(
                    message_id=queued.message_id,
                    receipt_handle=receipt,
                    body=dict(queued.body),
                    receive_count=queued.receive_count,
                )
            )
        return envelopes

    def ack(self, envelope: QueueEnvelope) -> None:
        self._inflight.pop(envelope.receipt_handle, None)

    def fail(self, envelope: QueueEnvelope, reason: str) -> bool:
        queued = self._inflight.pop(envelope.receipt_handle, None)
        if queued is None:
            return False
        queued.last_error = reason
        if queued.receive_count >= self.max_receive_count:
            self._dlq.append(queued)
            return True
        else:
            self._available.append(queued)
            return False

    def retry_later(
        self, envelope: QueueEnvelope, *, delay_seconds: int = 5, reason: str = ""
    ) -> None:
        queued = self._inflight.pop(envelope.receipt_handle, None)
        if queued is None:
            return
        queued.last_error = reason
        self._available.append(queued)

    @property
    def available_count(self) -> int:
        return len(self._available)

    @property
    def inflight_count(self) -> int:
        return len(self._inflight)

    @property
    def dlq_count(self) -> int:
        return len(self._dlq)

    @property
    def dlq_messages(self) -> tuple[dict, ...]:
        return tuple(dict(m.body) for m in self._dlq)
