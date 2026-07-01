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
"""

from __future__ import annotations

import re

from raku_rag.chatbot.answer_engine import AnswerEngine, DialogueContext
from raku_rag.core.query_planner import AMBIGUOUS_REFERENTS, plan_query
from raku_rag.domain.models import IdentityClaims

# `query_planner.AMBIGUOUS_REFERENTS` only covers pronominal forms ("それ"/"これ"/"あれ"). Japanese
# follow-ups just as often use adnominal/anaphoric forms that name a noun directly — "その締付トルク
# は?" — rather than standing alone — "それは?". Both need the prior turn's identifier merged in, so
# this list is a superset built ON the shared one (reusing its pronoun list), not a rival list.
_ADDITIONAL_REFERENTIAL_MARKERS = (
    "その",
    "この",
    "あの",
    "上記",
    "同じ",
    "先程",
    "先ほど",
    "前述",
    "そちら",
    "こちら",
)
REFERENTIAL_MARKERS = tuple(dict.fromkeys(AMBIGUOUS_REFERENTS + _ADDITIONAL_REFERENTIAL_MARKERS))

# A follow-up longer than this is treated as its own self-contained question even if it happens to
# contain a referential marker somewhere (e.g. a troubleshooting narrative that uses "それ" to refer
# to something named earlier in the SAME sentence, not in a prior turn). Rewriting a long, otherwise
# independent question with a stale prior-turn identifier would do real harm, so length is a
# deliberate, conservative gate, not an incidental one.
_MAX_REFERENTIAL_FOLLOWUP_LENGTH = 40

# Generic elaboration/politeness glue that carries no topic of its own ("それについてもう少し詳しく
# 教えてください" == "tell me more about that"). Stripping these (and the referential markers above)
# is how the engine decides whether the follow-up asks for a NEW fact (needs a fresh search) or
# nothing beyond what was already answered (reuse it) — see `has_own_topic`.
_GENERIC_FOLLOWUP_GLUE = (
    "もう少し",
    "詳しく",
    "教えて",
    "ください",
    "下さい",
    "について",
    "お願いします",
    "でしょうか",
    "ですか",
    "説明して",
    "続けて",
    "もっと",
    "他には",
    "ほかには",
)
_TRAILING_PUNCTUATION_RE = re.compile(r"[\s。、！?？!,.:：]+$")
_TRAILING_PARTICLE_RE = re.compile(r"(?:は|を|が|の|に|で|も|と|へ|や)+$")
_LEADING_PARTICLE_RE = re.compile(r"^(?:は|を|が|の|に|で|も|と|へ|や)+")


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def is_referential_followup(query: str, context: DialogueContext) -> bool:
    """The detector: a short message with a demonstrative/anaphoric reference and no identifier of
    its own, asked when there is a prior turn to resolve it against.

    Reuses `query_planner.plan_query`'s identifier extraction rather than a second implementation —
    a message that already names its own identifier (e.g. "P-101の締付トルクは?") is self-contained
    and must never be rewritten, even if it also happens to contain a referential marker.
    """
    if not context.previous_question:
        return False
    normalized = _normalize(query)
    if not normalized or len(normalized) > _MAX_REFERENTIAL_FOLLOWUP_LENGTH:
        return False
    if not any(marker in normalized for marker in REFERENTIAL_MARKERS):
        return False
    return not plan_query(query).identifiers


def residual_topic(query: str) -> str:
    """What remains of `query` after stripping referential markers and generic elaboration glue.

    Deliberately NOT a text-overlap comparison against the previous answer: the CJK-bigram retrieval
    tokenizer (`hybrid_retrieval.lexical_query_terms`) makes a robust "is this already covered by the
    old answer" check impractical for short queries (marker/particle boundary bigrams rarely match
    verbatim evidence text either way, in both false directions). An empty residual means the
    follow-up names nothing beyond the reference itself, so reusing the prior answer is both safe and
    the only sensible option; any residual content names something the prior answer is not known to
    cover, so a fresh, properly-scoped search is the conservative, always-safe choice.
    """
    residual = query
    for marker in REFERENTIAL_MARKERS:
        residual = residual.replace(marker, "")
    for glue in _GENERIC_FOLLOWUP_GLUE:
        residual = residual.replace(glue, "")
    while True:
        stripped = _TRAILING_PUNCTUATION_RE.sub("", residual)
        stripped = _TRAILING_PARTICLE_RE.sub("", stripped)
        stripped = _LEADING_PARTICLE_RE.sub("", stripped)
        if stripped == residual:
            return residual.strip()
        residual = stripped


def has_own_topic(query: str) -> bool:
    return len(residual_topic(query)) >= 2


def _previous_query_signal(context: DialogueContext) -> tuple[str, ...]:
    """Identifiers/key terms to carry over from the prior turn: prefer what the prior QUESTION named
    explicitly, then the prior turn's own cited document ids (which still anchor retrieval even when
    the question itself never spelled out a code), then generic content terms as a last resort so a
    rewrite is still attempted even for a vague prior question.
    """
    plan = plan_query(context.previous_question or "")
    if plan.identifiers:
        return plan.identifiers
    if context.previous_document_ids:
        return context.previous_document_ids
    return plan.lexical_terms[:4]


def standalone_query(query: str, context: DialogueContext) -> str:
    """Merge the prior turn's identifiers/key terms into `query`, deterministically. No LLM
    involved: plain string concatenation is enough to restore the missing signal for retrieval's own
    identifier/lexical matching (see `core/hybrid_retrieval.py`) to pick back up.
    """
    lowered = query.casefold()
    # `plan_query` returns identifiers in both a hyphenated and a separator-less compact form (e.g.
    # "p-101" and "p101"); compare on the compact form too so carrying one form never duplicates the
    # other when the query already spells out the identifier in a different, but equivalent, shape.
    compact_lowered = lowered.replace("-", "").replace("_", "")
    carry = [
        term
        for term in _previous_query_signal(context)
        if term not in lowered and term.replace("-", "").replace("_", "") not in compact_lowered
    ]
    if not carry:
        return query
    return f"{query} {' '.join(carry)}"


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

    See the module docstring for the full decision flow. `context` (source_policy_ids, previous
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
        return self._inner.answer(principal, rewritten_query, collection_id, context)
