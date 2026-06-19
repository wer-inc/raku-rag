"""T018 — TaskQueue. MVP: inline (synchronous) queue so ingestion is deterministic in tests.

Production swaps in the Arq adapter (DLQ + circuit breaker) behind TaskQueue (FR-030).
"""
from __future__ import annotations

from typing import Callable

from raku_rag.interfaces.base import TaskQueue


class InlineTaskQueue(TaskQueue):
    def enqueue(self, fn: Callable[..., object], *args, **kwargs) -> object:
        return fn(*args, **kwargs)
