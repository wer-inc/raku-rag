"""L2 (Query understanding / coreference) answer engine — P3 of
docs/production-readiness/chatbot-conversational-agent-roadmap.md.

The original complaint this phase fixes: a natural follow-up such as "その締付トルクは?" after a
question naming equipment "P-101" was sent to retrieval verbatim, losing "P-101" entirely, so it
either hit the wrong document or came back `insufficient_evidence`. `L2QueryUnderstandingAnswerEngine`
wraps an inner `AnswerEngine` (in practice `L0DeterministicAnswerEngine`) and, only when the new
message looks like a referential follow-up that cannot stand on its own, either:

- answers directly from the prior turn's citations (no new retrieval) when the follow-up names
  nothing beyond the reference itself — a plain "tell me more"; or
- deterministically rewrites the message into a standalone query by carrying over the prior turn's
  identifiers/key terms, then calls the inner engine with THAT query instead of the raw follow-up.

Facts stay exactly as extractive/cited as they are today — this phase only changes what string
retrieval receives, never how answers are composed. Both branches are plain string/regex logic,
offline, with zero dependency on any LLM provider ever being configured: per the roadmap, this
deterministic mechanism is what every tenant actually runs, not an optional LLM feature.

If the message does not look like a referential follow-up — self-contained, or already carries its
own identifier — it is passed through byte-identical to `inner.answer(...)`, same as L0 today.

Source-scope-carry: this engine never touches source-policy/collection scope itself. Whatever
citations it returns (reused from `context.previous_citations`, or freshly retrieved via the inner
engine) flow back through `ChatbotService._run_rag_turn`'s existing `_filter_chatbot_citations`/
`_pre_rag_source_policy_ids` gate exactly like any other engine's output — see the scope-carry tests
in tests/unit/test_chatbot_service.py, which prove this rather than assume it.

## Finding: the standalone-query rewrite can corrupt the manufacturing high-risk safety gate

`standalone_query` appends the prior turn's identifiers/document-ids/lexical terms to the raw
follow-up text, then the REWRITTEN string — not the original — is what reaches `inner.answer(...)`
and, for a manufacturing-backed deployment, `manufacturing_system.answer(principal, query,
collection_id)`. That call uses the SAME `query` string for retrieval AND for the high-risk
classifier's candidate pool (see `chatbot/composition.py`'s module docstring "Finding", which found
and reverted the structurally identical bug for L3's — since-abandoned — query-enrichment attempt):
`InMemoryVectorStore.lexical_matches` gives ANY document sharing even one query term a flat
`LEXICAL_MATCH_BASE_SCORE` (0.70) baseline. Empirically reproduced here too: a short, referential,
high-risk follow-up ("その圧力の抜き方を教えて" — no identifier of its own, so it takes this
module's REWRITE branch) after an unrelated ordinary turn that cited an APPROVED document —
appending that prior turn's carried terms/document-id let the corrupted retrieval hand the
manufacturing safety gate a candidate pool built from the unrelated APPROVED document, flipping a
query that must block (the real, on-topic content was draft/pending) into `status="ok"`, citing the
wrong content. `RuleHighRiskClassifier` still correctly labels the RAW follow-up text `high_risk`
(it scans query text directly, independent of retrieval) — the corruption is specifically in what
retrieval hands the safety gate, exactly composition.py's finding. Unlike L3, this engine's rewrite
is real and shipped (P3), so this could not be resolved by "pass the query through unchanged" (that
would silently drop this phase's actual fix); see `tests/unit/test_chatbot_service.py`'s
`ChatbotL2CoreferenceHighRiskSafetyTest` for the reproduction and the fix proven below.

**The fix (root-cause)**: retrieval genuinely benefits from the enriched query (that recall boost is
this whole phase's point), so this engine still rewrites — but it now carries the RAW follow-up as
`context.intent_query` (see `chatbot/answer_engine.py::DialogueContext`).
`L0DeterministicAnswerEngine` forwards that raw intent to any `RagAnswerer` that accepts
`intent_query=` — in practice the manufacturing answer chain
(`manufacturing/api/answer_ext.py::ManufacturingAnswerService.answer`), wired in
`apps/answer-service/server.py`. That chain binds BOTH safety-critical decisions to the raw intent,
never the enriched query:

1. the high-risk CLASSIFICATION runs on the raw intent, so appending prior-turn terms can no longer
   push a terse hazard follow-up past the classifier's "ambiguous, too terse to rule danger out"
   fail-safe and launder it into a non-high-risk query; and
2. for a high-risk intent, an approved+effective citation may satisfy the gate ONLY if it is
   RESPONSIVE to the raw intent (shares a lexical term with it) — so a document seated purely by the
   carried prior-turn terms (the flat `LEXICAL_MATCH_BASE_SCORE` admits any one-term match) can never
   supply the approval that unblocks the answer. If none is responsive, the chain blocks
   APPROVED_CITATION_MISSING, exactly as if no approved citation existed at all.

Net effect: retrieval still gets the enriched query (so P3 resolves the reference and finds the RIGHT
document even for a high-risk follow-up), while the safety gate is judged on what the user actually
asked. When the rewrite adds nothing (`standalone_query` returns the query unchanged), no intent_query
is set and the call is byte-identical to L0. A deployment whose `RagAnswerer` does not accept
`intent_query=` (a non-manufacturing one, or a test stub) simply receives the enriched query with no
intent split — the same behavior as before this module existed; this module itself takes NO position
on what "high risk" means and imports nothing manufacturing-specific.

This REPLACED an earlier, incomplete fix (an optional `high_risk_query_signal` callback that skipped
enrichment for keyword-classified follow-ups). That guard was keyword-only: a high-risk follow-up
phrased with ordinary equipment nouns instead of a listed hazard keyword classified via the
"ambiguous" fail-safe, evaded the signal, and was still rewritten — reproducibly bypassing the gate
(`status="ok"` citing an unrelated approved document). Widening that signal to treat every ambiguous
classification as high-risk would instead have starved the rewrite of nearly every short Japanese
follow-up (Japanese has no spaces, so `core.text.content_tokens` cannot segment a short sentence,
tripping the fail-safe on benign cases like P3's flagship "その締付トルクは?"). The root-cause fix
above keeps the rewrite working for those benign cases while making it safe for the dangerous ones.

The reuse-previous-citations branch (`answer_from_previous_turn`) is untouched and needs no
intent_query: it fires only when `has_own_topic(query)` is False — a bare "tell me more" naming
nothing beyond the reference — so it never runs retrieval or the safety gate at all; it just returns
the prior turn's already-gated answer.

NOTE (U19): the pure text primitives (referential-marker detection, residual-topic stripping, the
standalone-query rewrite) now live in `raku_rag.core.coreference` so the manufacturing ANSWER
endpoint (`/internal/manufacturing/answer` `history` support — 追い質問の文脈維持 on the Answers
screen) can reuse them without importing this chatbot module. The functions below delegate there,
adapting `DialogueContext` to the shared context-free signatures — behavior is byte-identical
(pinned by tests/unit/test_chatbot_coreference.py and test_chatbot_service.py, unmodified).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from raku_rag.chatbot.answer_engine import AnswerEngine, DialogueContext
from raku_rag.core import coreference as _shared
from raku_rag.core.coreference import (  # noqa: F401 — re-exported public API (see NOTE above)
    REFERENTIAL_MARKERS,
    has_own_topic,
    residual_topic,
)
from raku_rag.domain.models import IdentityClaims

# A domain-agnostic seam (this module has zero manufacturing-specific knowledge, by design — see the
# module docstring's Finding): `True` means "do not enrich this query's outgoing text", `False`/`None`
# preserves this engine's original, pre-fix behavior exactly.
HighRiskQuerySignal = Callable[[str], bool]


def is_referential_followup(query: str, context: DialogueContext) -> bool:
    """The detector: a short message with a demonstrative/anaphoric reference and no identifier of
    its own, asked when there is a prior turn to resolve it against. Delegates to the shared
    `core.coreference.is_referential_followup` (see the module docstring NOTE).
    """
    return _shared.is_referential_followup(query, previous_question=context.previous_question)


def standalone_query(query: str, context: DialogueContext) -> str:
    """Merge the prior turn's identifiers/key terms into `query`, deterministically. Delegates to
    the shared `core.coreference.standalone_query` (see the module docstring NOTE).
    """
    return _shared.standalone_query(
        query,
        previous_question=context.previous_question,
        previous_document_ids=context.previous_document_ids,
    )


def answer_from_previous_turn(context: DialogueContext) -> dict | None:
    """Generalizes `ChatbotService._previous_reformat_turn`'s mechanism (answer from the last turn's
    citations without a new search) to organic free text. Returns `None` when there is nothing usable
    to reuse, so the caller can fall through to a fresh, rewritten search instead.
    """
    if not context.previous_citations:
        return None
    source_text = (context.previous_source_answer_text or context.previous_answer or "").strip()
    if not source_text:
        return None
    return {
        "status": "ok",
        "text": source_text,
        "citations": [dict(citation) for citation in context.previous_citations],
        "confidence": None,
        "correlation_id": None,
    }


class L2QueryUnderstandingAnswerEngine:
    """Wraps `inner` with deterministic coreference resolution for organic follow-ups.

    See the module docstring for the full decision flow, including the "Finding" section on why the
    rewrite branch is gated by `high_risk_query_signal`. `context` (source_policy_ids, previous
    citations) is read but never used to widen scope — that stays entirely the job of the existing
    `ChatbotService._filter_chatbot_citations`/`_pre_rag_source_policy_ids` gate, which runs on
    whatever this engine returns exactly like it runs on any other engine's output.
    """

    def __init__(self, inner: AnswerEngine) -> None:
        self._inner = inner

    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None,
        context: DialogueContext,
    ) -> dict:
        if not is_referential_followup(query, context):
            return self._inner.answer(principal, query, collection_id, context)

        if not has_own_topic(query):
            reused = answer_from_previous_turn(context)
            if reused is not None:
                return reused

        rewritten_query = standalone_query(query, context)
        if rewritten_query == query:
            # Nothing to carry (no new signal beyond what the query already names) — byte-identical
            # passthrough, so there is no enriched/raw distinction to protect.
            return self._inner.answer(principal, query, collection_id, context)

        # Module docstring's Finding: retrieval benefits from the enriched query, but the RAW
        # follow-up is what the manufacturing high-risk classification and approved-citation gate must
        # judge — so carry it as `context.intent_query`. `L0DeterministicAnswerEngine` forwards it to
        # a `RagAnswerer` that accepts `intent_query=` (in practice the manufacturing answer chain),
        # which binds those safety decisions to the raw intent while retrieving with `rewritten_query`.
        # This is the root-cause fix that replaced the earlier, incomplete `high_risk_query_signal`
        # skip-enrichment guard (see the Finding for why keyword-only gating was insufficient).
        return self._inner.answer(
            principal, rewritten_query, collection_id, replace(context, intent_query=query)
        )
