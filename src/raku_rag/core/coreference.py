"""Deterministic coreference primitives shared by the chatbot L2 rung and the answer endpoint.

Extracted VERBATIM from ``raku_rag.chatbot.coreference`` (P3 of the chatbot conversational-agent
roadmap) so the manufacturing ANSWER path (U19 — 追い質問の文脈維持 on the Answers screen) can reuse
the exact same referential-follow-up detection and standalone-query rewrite without importing the
chatbot layer into the answer path. The chatbot module now delegates here, adapting its
``DialogueContext`` to these context-free signatures — its behavior is byte-identical (pinned by
tests/unit/test_chatbot_coreference.py and test_chatbot_service.py, which were not modified).

Everything here is plain string/regex logic over the shared ``core.query_planner`` — offline, no LLM,
no manufacturing- or chatbot-specific knowledge. The safety contract that makes the rewrite safe to
apply (carry the RAW query as the intent the high-risk classification and approved-citation gate
judge, never the enriched one) is documented at length in ``chatbot/coreference.py``'s module
docstring ("Finding") and enforced in ``manufacturing/api/answer_ext.py``; both consumers of this
module thread that raw intent through the ``intent_query`` channel.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

from raku_rag.core.query_planner import AMBIGUOUS_REFERENTS, plan_query

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
# is how a caller decides whether the follow-up asks for a NEW fact (needs a fresh search) or
# nothing beyond what was already answered — see `has_own_topic`.
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

# Server-side cap on how many prior turns an answer-endpoint caller may supply (U19): only the most
# recent turns can plausibly anchor a referential follow-up, and an unbounded client-supplied list
# must not become a resource-/signal-injection vector.
MAX_HISTORY_TURNS = 5


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def is_referential_followup(query: str, *, previous_question: str | None) -> bool:
    """The detector: a short message with a demonstrative/anaphoric reference and no identifier of
    its own, asked when there is a prior turn to resolve it against.

    Reuses `query_planner.plan_query`'s identifier extraction rather than a second implementation —
    a message that already names its own identifier (e.g. "P-101の締付トルクは?") is self-contained
    and must never be rewritten, even if it also happens to contain a referential marker.
    """
    if not previous_question:
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


def previous_turn_signal(
    previous_question: str | None, previous_document_ids: Sequence[str]
) -> tuple[str, ...]:
    """Identifiers/key terms to carry over from the prior turn: prefer what the prior QUESTION named
    explicitly, then the prior turn's own cited document ids (which still anchor retrieval even when
    the question itself never spelled out a code), then generic content terms as a last resort so a
    rewrite is still attempted even for a vague prior question.
    """
    plan = plan_query(previous_question or "")
    if plan.identifiers:
        return plan.identifiers
    if previous_document_ids:
        return tuple(previous_document_ids)
    return plan.lexical_terms[:4]


def standalone_query(
    query: str,
    *,
    previous_question: str | None,
    previous_document_ids: Sequence[str] = (),
) -> str:
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
        for term in previous_turn_signal(previous_question, previous_document_ids)
        if term not in lowered and term.replace("-", "").replace("_", "") not in compact_lowered
    ]
    if not carry:
        return query
    return f"{query} {' '.join(carry)}"


def followup_from_history(
    query: str, history: Sequence[Mapping[str, object]] | None
) -> tuple[str, str | None]:
    """U19: resolve a referential follow-up against client-supplied prior turns (answer endpoint).

    ``history`` is the thread so far as ``[{"question": str, "cited_document_ids": [str, ...]?}]``,
    most recent last (the Answers screen sends its last ≤5 turns). Mirrors the chatbot L2 semantics
    exactly: only the immediately-preceding usable turn anchors the reference (never a whole-thread
    merge), detection and rewrite are the SAME shared functions the chatbot uses, and the caller MUST
    thread the returned raw intent through the ``intent_query`` channel so the manufacturing
    high-risk classification + approved-citation gate judge what the user actually asked, never the
    enriched retrieval text (see chatbot/coreference.py's "Finding").

    Returns ``(retrieval_query, intent_query)``:
    - no usable history, a non-referential/self-contained query, or a rewrite that adds nothing
      => ``(query, None)`` — the caller's behavior must then be byte-identical to today;
    - a rewritten referential follow-up => ``(enriched_query, raw_query)``.
    """
    turns = [turn for turn in (history or ()) if isinstance(turn, Mapping)]
    previous_question: str | None = None
    previous_document_ids: tuple[str, ...] = ()
    for turn in reversed(turns[-MAX_HISTORY_TURNS:]):
        question = str(turn.get("question") or "").strip()
        if not question:
            continue
        previous_question = question
        raw_ids = turn.get("cited_document_ids")
        if isinstance(raw_ids, (list, tuple)):
            previous_document_ids = tuple(
                str(doc_id).strip() for doc_id in raw_ids if str(doc_id or "").strip()
            )
        break
    if previous_question is None:
        return query, None
    if not is_referential_followup(query, previous_question=previous_question):
        return query, None
    rewritten = standalone_query(
        query,
        previous_question=previous_question,
        previous_document_ids=previous_document_ids,
    )
    if rewritten == query:
        return query, None
    return rewritten, query
