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

**The fix**: an optional `high_risk_query_signal` callback, checked immediately before the rewrite
branch (not the reuse-previous-citations branch — see below for why that one is untouched). When
supplied and it returns `True` for the RAW, un-rewritten follow-up text, this engine skips the
append/rewrite and passes the RAW query straight to `inner.answer(...)` instead — the same
byte-identical passthrough a self-contained query already gets today. Worst case this is an honest
`insufficient_evidence`/handoff (the retrieval-recall problem P3 exists to fix, reintroduced only for
this one turn); it can never be a corrupted `status="ok"`, because retrieval never sees the
poisoning terms in the first place. This engine takes NO position on what "high risk" means — the
callback is a plain `Callable[[str], bool] | None`, injected by the composition root (in practice
`ManufacturingSystem.is_high_risk_query_signal`, wired in `apps/answer-service/server.py`) exactly
like `llm_provider` already is; a deployment with no such concept (or that simply doesn't wire one)
gets `None`, and this engine's behavior is then BYTE-IDENTICAL to before this fix — no regression,
no new manufacturing-specific import in this module.

Why not gate the reuse-previous-citations branch (`answer_from_previous_turn`) the same way: that
branch only ever fires when `has_own_topic(query)` is False — a bare "tell me more" naming nothing
beyond the reference itself — so a high-risk-classified RAW follow-up (which by construction names a
concrete hazard topic, e.g. "圧力"/pressure) can never reach it; the two conditions are mutually
exclusive on the same message in practice, and if they somehow coincided, reusing turn 1's answer
verbatim would be even less safe (it returns `status="ok"` unconditionally, with NO retrieval,
classification, or safety-gate re-evaluation at all) than the rewrite branch this fix actually
targets.

Why the callback is intentionally NARROWER than "the classifier says high_risk": a naive
`RuleHighRiskClassifier.classify(query, ()).is_high_risk` would ALSO fire for nearly every short
Japanese follow-up, including P3's own benign flagship case ("その締付トルクは?") — confirmed
empirically, not assumed: Japanese text has no spaces, so `core.text.content_tokens` cannot
word-segment it, collapsing a whole short sentence into one "token" and tripping the classifier's
stage-3 "ambiguous, too terse to rule danger out" fail-safe regardless of actual content. That
fail-safe is exactly correct for the FINAL "may this answer assert" decision (never assert on an
ambiguous safety-relevant query without approved evidence) but is NOT itself a signal that THIS
query's text is a concrete hazard statement — treating it as one here would starve the coreference
rewrite of nearly every short Japanese follow-up with no safety benefit (the real classifier and gate
still run for real, unaffected, on whatever text this decision lets through to `inner.answer(...)`).
`ManufacturingAnswerService.classify_query_signal` — what
`ManufacturingSystem.is_high_risk_query_signal` delegates to — encodes this distinction so this
module does not have to know about `ClassificationSource`, or anything else manufacturing-specific,
at all.
"""

from __future__ import annotations

import re
from typing import Callable

from raku_rag.chatbot.answer_engine import AnswerEngine, DialogueContext
from raku_rag.core.query_planner import AMBIGUOUS_REFERENTS, plan_query
from raku_rag.domain.models import IdentityClaims

# A domain-agnostic seam (this module has zero manufacturing-specific knowledge, by design — see the
# module docstring's Finding): `True` means "do not enrich this query's outgoing text", `False`/`None`
# preserves this engine's original, pre-fix behavior exactly.
HighRiskQuerySignal = Callable[[str], bool]

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

    See the module docstring for the full decision flow, including the "Finding" section on why the
    rewrite branch is gated by `high_risk_query_signal`. `context` (source_policy_ids, previous
    citations) is read but never used to widen scope — that stays entirely the job of the existing
    `ChatbotService._filter_chatbot_citations`/`_pre_rag_source_policy_ids` gate, which runs on
    whatever this engine returns exactly like it runs on any other engine's output.
    """

    def __init__(
        self,
        inner: AnswerEngine,
        high_risk_query_signal: HighRiskQuerySignal | None = None,
    ) -> None:
        self._inner = inner
        self._high_risk_query_signal = high_risk_query_signal

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

        # Module docstring's Finding: appending prior-turn context can corrupt retrieval's candidate
        # pool for a query that is independently, concretely high-risk. When the caller has wired a
        # signal (in practice `ManufacturingSystem.is_high_risk_query_signal`) and it fires on the
        # RAW, un-rewritten text, skip the enrichment entirely and fall through to the same
        # byte-identical passthrough a self-contained query already gets — never a rewritten query,
        # even if that means an honest insufficient_evidence/handoff instead of a resolved answer.
        if self._high_risk_query_signal is not None and self._high_risk_query_signal(query):
            return self._inner.answer(principal, query, collection_id, context)

        rewritten_query = standalone_query(query, context)
        return self._inner.answer(principal, rewritten_query, collection_id, context)
