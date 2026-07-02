"""L4 (Agentic control / tool use) answer engine — P5 of
docs/production-readiness/chatbot-conversational-agent-roadmap.md, the roadmap's Full-A destination.

`L4AgenticAnswerEngine` wraps an inner `AnswerEngine` (in practice `L0DeterministicAnswerEngine`) with
a bounded tool-use LOOP: a `decision_maker` (in production, someday, an LLM-backed implementation of
the `AgentDecisionMaker` Protocol below; in every test and in the current default construction, a
mocked/deterministic stand-in — there is no real Bedrock access in this environment, matching every
phase before this one) decides, turn by turn, whether to retrieve with some query text it chooses, or
to stop. Each retrieval "hop" is a full, independent call to `inner.answer(...)` — the EXACT same call
every other rung makes — so ACL/tenant/source-policy enforcement, retrieval, the manufacturing
high-risk classifier, the safety gate, and audit logging are never reimplemented, bypassed, or run
with stale state; they simply run again, fresh, for every hop, because this module never has its own
retrieval/ACL/classification code to run instead.

`decision_maker=None` (no rung-appropriate decision-maker configured — the default, since no real one
exists yet) is a fully offline, zero-call passthrough to `inner.answer(query, ...)` with the ORIGINAL
turn query, unchanged — mirroring `L1EnvelopeAnswerEngine`'s/`L3CompositionAnswerEngine`'s own
"no provider configured" no-op stance.

## The central risk this module is built around

Two prior phases (P3 `chatbot/coreference.py`, P4 `chatbot/composition.py` — see both module
docstrings' "Finding" sections) independently discovered and reproduced the SAME vulnerability:
`InMemoryVectorStore.lexical_matches` gives ANY document sharing even one query term a flat
`LEXICAL_MATCH_BASE_SCORE` (0.70) baseline, so a query string that blends a hazardous topic with
unrelated terms can seat an unrelated, APPROVED document as "evidence" for a question that should
require its own, real (and possibly unapproved) document's approval. P4's enrichment attempt was
reverted entirely; P3's was real and shipped. (NOTE, 2026-07-02: P3's *own* fix was later moved to
the root cause — `DialogueContext.intent_query`, which binds the manufacturing high-risk
classification + approved-citation gate to the raw intent; see `coreference.py`'s "Finding". L4 does
NOT rewrite queries the way P3 does, so it cannot use that same intent/enriched split; it keeps the
`high_risk_query_signal` pre-check described below — a retrieval-independent, query-text-only check,
deliberately narrower than the classifier's own "ambiguous => high-risk" fail-safe — as ITS mechanism.
The two rungs now protect the same vulnerability by different, appropriate means.)

Agentic control is this same vulnerability at its widest scope: a decision-maker can choose ARBITRARY
query text, potentially more than once per turn, potentially informed by what an earlier hop returned.
This module's structural answer:

1. **Every proposed retrieval query, on every hop, is re-classified before it is allowed to run**
   (`high_risk_query_signal`, in production `ManufacturingSystem.is_high_risk_query_signal` — the
   SAME classifier instance the real safety gate consults, never a second, drifting one). This is not
   a one-time check on the first hop; a hazardous-looking rephrase two or three hops deep is exactly as
   dangerous as one on the first hop, and is checked identically.
2. **Any trip aborts the WHOLE agentic attempt for this turn, not just the offending hop.** Per the
   roadmap's own framing of the required fail-safe posture ("fall back to the safe, unenriched,
   deterministic path... for that turn, never silently proceed with a possibly-poisoned query"), a
   trip returns `inner.answer(principal, query, collection_id, context)` — the ORIGINAL, untouched turn
   query, run through the plain floor every other rung falls back to — discarding any earlier hop's
   result from this same turn. This is deliberately more conservative than "just skip this one hop and
   let the loop keep going": once the decision-maker has proposed a hazard-signalling query even once
   in this turn, this module no longer trusts any part of its own trajectory enough to keep exploring
   with its own freedom, and prefers the well-tested, always-available floor instead.
3. **The loop never merges citations across hops.** It always returns exactly ONE hop's own complete,
   self-consistent `inner.answer()` result — never a union of several hops' citations with a single
   hop's text. This is what "do not let an agentic loop accumulate or carry state across hops in a way
   that could smuggle an earlier hop's citations into a later, differently-scoped one" means in this
   module: there is no accumulation to smuggle from, because nothing is ever accumulated. Concretely,
   the loop keeps only the LAST hop's own result (see `answer()` below) — not "the first `ok` result"
   or "the best-looking result" — specifically because preferring an EARLIER, unrelated `ok` hop over a
   LATER hop that correctly, safely blocked (e.g. the decision-maker tries something benign first, then
   asks the real, hazardous question on hop 2, which correctly comes back `insufficient_evidence`)
   would let that earlier, irrelevant answer paper over a safety block the user's real (later-explored)
   question just correctly received. "Last hop wins" is the rule that never lets that happen: whatever
   the decision-maker most recently, deliberately chose to look up is authoritative, whether it
   succeeded or correctly failed.
4. **`collection_id` and `principal` are fixed, per-turn inputs this module receives once and forwards
   unchanged to every hop — it never constructs its own.** The loop's only freedom is QUERY TEXT.
   Combined with point 1 above, this means scope can never widen hop-to-hop: every hop is ACL/tenant/
   source-policy-checked exactly as strictly as the turn's own first call would have been, because it
   IS that same call, run again.
5. **Hop count is hard-capped** (`max_hops`, default `DEFAULT_MAX_HOPS`) via a bounded loop, not a
   `while True` — an adversarial or confused decision-maker that always asks for one more hop still
   only ever runs `max_hops` retrievals before this module stops asking it anything further and settles
   the turn.
6. **The decision-maker's own output is treated as untrusted, not obeyed blindly** ("output guard" for
   the controller itself, the new failure surface this rung introduces that no earlier rung had to
   consider): an exception raised by `decision_maker.decide(...)`, or a returned value that isn't a
   recognized `AgentAction`, immediately stops the loop (falling through to whatever the last real hop
   already found, or the safe floor if none) rather than propagating the exception or guessing at intent.

## What is genuinely NOT closed by the above — read this before trusting this module more than it
## claims to deserve

`high_risk_query_signal` is a LEXICAL (keyword/metadata) check, exactly like the real
`RuleHighRiskClassifier`'s own KEYWORD stage it reuses. A sufficiently novel rephrasing that avoids
every recognized hazard keyword while still functionally targeting a hazardous topic is NOT caught by
this pre-check, because catching it would require a SEMANTIC (not lexical) query classifier — explicitly
out of scope for this pass (no new ML-based classifier). This is a real, accepted residual gap, not an
oversight: closing it needs either a smarter classifier or a redesign of `InMemoryVectorStore.
lexical_matches` itself (out of scope, safety-critical, shared by every rung). What bounds the residual
risk: whatever query text a hop actually runs receives EXACTLY the same treatment `inner.answer()`
already gives any human-typed query with that same text — the classifier + safety gate still run for
real, unaffected, on whatever reaches them. The risk this module cannot structurally close is
specifically that an agentic decision-maker might choose DIFFERENT words than a human would have,
not that it can make the safety gate itself any weaker for the words it does choose.

## Deliberately scoped down from "full" agentic control

- **No distinct "ask a clarifying question" surface.** `_run_rag_turn` (`chatbot/service.py`) has no
  channel today for a custom clarifying message distinct from its one fixed handoff string — extending
  that shared, safety-relevant turn contract is a bigger, separately-reviewable change outside this
  phase's scope (mirrors composition.py's own reasoning for why thread-state query enrichment was
  deferred rather than half-built). `FinishAction` therefore covers BOTH "answer with what's already
  known" and "nothing usable, stop" — both cash out, via the existing contract, in outcomes every rung
  already produces (a real hop's own answer, or the standard insufficient_evidence/handoff flow).
- **No real (Bedrock-backed) `AgentDecisionMaker` implementation.** Only the Protocol/interface plus
  test-only mocks exist. Building a real one needs credentials this environment does not have, and
  would need its own prompt/verification work beyond this pass's scope.
- **Observations are reference-ID-only, never evidence text.** `AgentObservation` carries `status`,
  `answerable`, and `citation_ids` (reused from `envelope.citation_id_values`, the same reference-only
  surface `composition.py`'s defense-in-depth check already trusts) — never the underlying chunk or
  answer TEXT. This mirrors `providers/llms.py::build_grounded_prompt`'s "evidence wrapped as data,
  never as instructions" property for the base generation path, but goes one step further: there is no
  free text in an observation at all for a future real decision-maker to misinterpret as an instruction,
  because retrieved content never reaches this loop as text in the first place. (`context: DialogueContext`
  IS still passed through unchanged to `decide(...)`, exactly as every earlier rung already receives it
  — including `context.previous_answer`, which does carry prior-turn prose; that channel is pre-existing
  from P0, not new to this phase, and is unchanged here.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from raku_rag.chatbot.answer_engine import AnswerEngine, DialogueContext
from raku_rag.chatbot.coreference import HighRiskQuerySignal
from raku_rag.chatbot.envelope import citation_id_values
from raku_rag.domain.models import IdentityClaims

DEFAULT_MAX_HOPS = 3


@dataclass(frozen=True)
class RetrieveAction:
    """Ask the loop to run one retrieval-bound hop with this exact query text."""

    query: str


@dataclass(frozen=True)
class FinishAction:
    """Stop the loop now. See the module docstring's "Deliberately scoped down" section for why this
    single action covers both "answer with what's already known" and "ask a clarifying question"."""


AgentAction = RetrieveAction | FinishAction


@dataclass(frozen=True)
class AgentObservation:
    """What a completed hop tells the decision-maker before its next call — reference-ID-only, never
    evidence/answer text (module docstring). `query` is the decision-maker's OWN prior proposal being
    echoed back (not new untrusted content, so echoing it carries no injection risk)."""

    query: str
    status: str
    answerable: bool
    citation_ids: tuple[str, ...]


class AgentDecisionMaker(Protocol):
    def decide(
        self,
        query: str,
        context: DialogueContext,
        observations: tuple[AgentObservation, ...],
    ) -> AgentAction: ...


def _observation_from(hop_query: str, answer: dict) -> AgentObservation:
    citations = list(answer.get("citations") or [])
    status = str(answer.get("status") or "")
    return AgentObservation(
        query=hop_query,
        status=status,
        answerable=status == "ok" and bool(citations),
        citation_ids=tuple(sorted(citation_id_values(citations))),
    )


class L4AgenticAnswerEngine:
    """Wraps `inner` with a bounded, decision-maker-driven retrieval loop. See the module docstring
    for the full safety design, including why a high-risk signal trip aborts the whole turn and why
    the loop never merges citations across hops.
    """

    def __init__(
        self,
        inner: AnswerEngine,
        decision_maker: AgentDecisionMaker | None = None,
        high_risk_query_signal: HighRiskQuerySignal | None = None,
        max_hops: int = DEFAULT_MAX_HOPS,
    ) -> None:
        if max_hops < 1:
            raise ValueError("max_hops must be >= 1")
        self._inner = inner
        self._decision_maker = decision_maker
        self._high_risk_query_signal = high_risk_query_signal
        self._max_hops = max_hops

    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None,
        context: DialogueContext,
    ) -> dict:
        if self._decision_maker is None:
            return self._inner.answer(principal, query, collection_id, context)

        observations: list[AgentObservation] = []
        last_answer: dict | None = None
        for _ in range(self._max_hops):
            try:
                action = self._decision_maker.decide(query, context, tuple(observations))
            except Exception:
                break
            if not isinstance(action, RetrieveAction):
                break
            hop_query = action.query
            if self._high_risk_query_signal is not None and self._high_risk_query_signal(
                hop_query
            ):
                # Module docstring point 2: never let a hazard-signalling proposed query touch
                # retrieval -- abandon the whole agentic attempt for this turn (not just this hop,
                # and discarding any earlier hop's `last_answer` from this same turn) and answer the
                # ORIGINAL, untouched turn query through the plain inner floor instead.
                return self._inner.answer(principal, query, collection_id, context)
            last_answer = self._inner.answer(principal, hop_query, collection_id, context)
            observations.append(_observation_from(hop_query, last_answer))

        if last_answer is not None:
            return last_answer
        return self._inner.answer(principal, query, collection_id, context)
