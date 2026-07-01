"""The pluggable answer-generation seam and its P0 (floor) implementation.

`RagAnswerer` (`Callable[[IdentityClaims, str, str | None], dict]`) was the original seam: it only
ever sees the bare query, never conversation state. `AnswerEngine` widens that seam with a
`DialogueContext` parameter so a future rung (see the authority ladder in
docs/production-readiness/chatbot-conversational-agent-roadmap.md) can use thread state without
another signature change. `L0DeterministicAnswerEngine` wraps a `RagAnswerer` unchanged — it is the
permanent safe floor every other rung falls back to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from raku_rag.domain.models import IdentityClaims

RagAnswerer = Callable[[IdentityClaims, str, str | None], dict]


@dataclass(frozen=True)
class DialogueContext:
    """Structured thread state for the current turn (built by `DialogueManager`)."""

    collection_id: str | None = None
    previous_question: str | None = None
    previous_answer: str | None = None
    previous_citations: tuple[dict, ...] = ()
    previous_document_ids: tuple[str, ...] = ()
    source_policy_ids: tuple[str, ...] = ()


class AnswerEngine(Protocol):
    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None,
        context: DialogueContext,
    ) -> dict: ...


class L0DeterministicAnswerEngine:
    """The deterministic floor: forwards to the original `RagAnswerer` unchanged.

    `context` is accepted (to satisfy `AnswerEngine`) but intentionally unused — L0 has no thread
    awareness by definition, which is what makes it the safe, always-available fallback.
    """

    def __init__(self, rag_answerer: RagAnswerer) -> None:
        self._rag_answerer = rag_answerer

    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None,
        context: DialogueContext,
    ) -> dict:
        return self._rag_answerer(principal, query, collection_id)
