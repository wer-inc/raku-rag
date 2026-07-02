"""The pluggable answer-generation seam and its P0 (floor) implementation.

`RagAnswerer` (`Callable[[IdentityClaims, str, str | None], dict]`) was the original seam: it only
ever sees the bare query, never conversation state. `AnswerEngine` widens that seam with a
`DialogueContext` parameter so a future rung (see the authority ladder in
docs/production-readiness/chatbot-conversational-agent-roadmap.md) can use thread state without
another signature change. `L0DeterministicAnswerEngine` wraps a `RagAnswerer` unchanged — it is the
permanent safe floor every other rung falls back to.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Callable, Protocol

from raku_rag.domain.models import IdentityClaims

# The original 3-arg seam. A `RagAnswerer` MAY additionally accept a keyword-only `intent_query`
# (the raw, pre-enrichment user query) — see `DialogueContext.intent_query` and
# `_answerer_accepts_intent` below; those that don't are called with exactly the original 3 args, so
# every existing implementation keeps working unchanged.
RagAnswerer = Callable[..., dict]


@dataclass(frozen=True)
class DialogueContext:
    """Structured thread state for the current turn (built by `DialogueManager`)."""

    collection_id: str | None = None
    previous_question: str | None = None
    previous_answer: str | None = None
    previous_citations: tuple[dict, ...] = ()
    previous_document_ids: tuple[str, ...] = ()
    source_policy_ids: tuple[str, ...] = ()
    # The raw, pre-`_format_chatbot_answer` extractive text behind `previous_answer` (which is the
    # already section-formatted display string). A rung that reuses the prior turn's facts without a
    # new search (see chatbot/coreference.py) needs this raw form so `_run_rag_turn` can format it
    # once, not twice — mirrors `_previous_reformat_turn`'s own `source_answer_text` field.
    previous_source_answer_text: str | None = None
    # The raw, UN-enriched user query, set by a rung that rewrites the outgoing retrieval query (only
    # `chatbot/coreference.py`'s L2 today). When set and different from the enriched `query`, L0
    # forwards it to a `RagAnswerer` that accepts `intent_query=` so the manufacturing chain can keep
    # its high-risk CLASSIFICATION and approved-citation gate bound to the user's ACTUAL intent, while
    # RETRIEVAL still benefits from the enriched query (see coreference.py's Finding and
    # manufacturing/api/answer_ext.py). `None` (the default, every non-rewriting turn) => the query IS
    # the intent => byte-identical to before this field existed.
    intent_query: str | None = None


class AnswerEngine(Protocol):
    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None,
        context: DialogueContext,
    ) -> dict: ...


def _answerer_accepts_intent(rag_answerer: RagAnswerer) -> bool:
    """True iff `rag_answerer` can be called with a keyword-only `intent_query=` (explicit param or
    **kwargs). Detected ONCE at construction so the hot path stays a plain call; any answerer that
    cannot accept it (every legacy 3-arg implementation and test mock) is called with the original 3
    positional args, unchanged."""
    try:
        params = inspect.signature(rag_answerer).parameters
    except (ValueError, TypeError):
        return False
    if "intent_query" in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


class L0DeterministicAnswerEngine:
    """The deterministic floor: forwards to the original `RagAnswerer`.

    `context` is accepted (to satisfy `AnswerEngine`) and, apart from mechanically forwarding
    `context.intent_query` to a `RagAnswerer` that accepts it (see below), is otherwise unused — L0
    makes no decision from thread state, which is what keeps it the safe, always-available fallback.
    It forwards the intent query only when an upstream rung actually rewrote the outgoing query
    (`intent_query` is set AND differs from `query`) AND the answerer accepts the keyword; otherwise
    it is a byte-identical 3-arg passthrough, exactly as before.
    """

    def __init__(self, rag_answerer: RagAnswerer) -> None:
        self._rag_answerer = rag_answerer
        self._accepts_intent = _answerer_accepts_intent(rag_answerer)

    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None,
        context: DialogueContext,
    ) -> dict:
        intent = context.intent_query
        if self._accepts_intent and intent is not None and intent != query:
            return self._rag_answerer(principal, query, collection_id, intent_query=intent)
        return self._rag_answerer(principal, query, collection_id)
