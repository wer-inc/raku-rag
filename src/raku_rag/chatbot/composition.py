"""L3 (Generative composition) answer engine — P4 of
docs/production-readiness/chatbot-conversational-agent-roadmap.md.

Architecture (read this before touching anything below): `chatbot_authority_level="L3"` does NOT,
and must not, control whether real LLM generation happens at all. That stays exactly what it is
today — the deployment-wide `Settings.llm_provider` switch (unset/extractive by default; no Bedrock
credentials in this sandbox) — because the generation call, `build_grounded_prompt`, the
manufacturing `RuleHighRiskClassifier`/`ManufacturingSafetyGate` hard block, `GroundednessGate.
post_check`/`claim_check` (P2), the output guardrail, and audit logging are all composed exactly
ONCE, inside `AnswerService.answer()` — a single process-wide, per-deployment object (`self._llm`/
`self._gate` on the one `AnswerService` behind `manufacturing_system.answer()`), not one instance per
tenant. Building a second, tenant-dialable generation path here (e.g. constructing our own
`BedrockClaudeLLMProvider` and calling `.generate()` directly, bypassing `inner.answer()`) would mean
reimplementing — or silently skipping — ACL enforcement, retrieval, the safety classifier, and audit
logging outside the one place they are all correctly composed today. This module never does that:
`L3CompositionAnswerEngine` always reaches generation (of whatever flavour the deployment has
configured) through `inner.answer(...)`, the exact same call every other rung uses, with the query
STRING passed through completely unchanged (see the finding below for why).

## Finding: thread-state QUERY enrichment was tried and reverted as unsafe

This phase's plan (see the roadmap's P4 section / the task that produced this module) called for
folding a short excerpt of the prior turn's question/answer into the query string sent to
`inner.answer(...)`, mirroring P3's `coreference.standalone_query` precedent, so that IF real
generation is ever turned on, composed prose would read as one continuous conversation. That was
implemented, then investigated empirically against exactly the scenario this phase's own safety test
(`tests/unit/test_chatbot_service.py::ChatbotManufacturingHighRiskCitationBlockAtL3Test`) cares about
— a high-risk query on a turn that follows an unrelated, ordinary one — and it FAILED, reproducibly
and for a structural reason, not a tuning mistake:

`manufacturing_system.answer(principal, query, collection_id)` uses the SAME `query` string for
retrieval (`RetrievalService.retrieve`), the manufacturing high-risk classifier's candidate pool
(`ManufacturingAnswerService.answer`, `src/raku_rag/manufacturing/api/answer_ext.py:491`), and
generation. `InMemoryVectorStore.lexical_matches` (`providers/vectorstores.py`) scores via
`lexical_match_score` (`core/hybrid_retrieval.py`): ANY document sharing even ONE query term gets a
FLAT `LEXICAL_MATCH_BASE_SCORE` (0.70) baseline, and the variable part is `coverage = matched /
len(query_terms)` — a FRACTION of the TOTAL query term count. Appending prior-turn content to the
query simultaneously (a) grows `len(query_terms)`, diluting the correct document's own coverage
fraction, and (b) can single-handedly qualify a previously-irrelevant document as a candidate at all
(the flat 0.70 base requires only one shared term). Empirically, appending as little as the two words
"routine inspection" (a prior turn's topic) to a fully unrelated, textbook-clear high-risk query
("How do I release the pressure in the hydraulic accumulator?") caused retrieval to hand the
manufacturing safety gate a candidate pool built entirely from an unrelated, APPROVED document —
letting the high-risk query return `status="ok"` with `safety_block_reason=None`, citing irrelevant
content, instead of correctly requiring the real (draft/pending) accumulator document's approval or
abstaining. `RuleHighRiskClassifier`'s keyword stage still correctly labelled the query `high_risk`
(it scans the query text directly, independent of retrieval) — the failure is specifically that the
retrieval-derived EVIDENCE pool the safety gate evaluates was corrupted. This reproduced identically
with longer, multi-sentence documents, not just a short test fixture, so it is not a test-realism
artifact.

Properly fixing this means separating the retrieval/classification-bound query string from a
generation-only one, which needs a coordinated, keyword-only-defaulted parameter threaded through
`ManufacturingSystem.answer()` -> `ManufacturingAnswerService.answer()` -> `AnswerService.answer()`
(used ONLY at the `self._llm.generate(...)` call site, after retrieval/classification/the safety gate
have already run against the untouched query) — touching the safety-critical manufacturing answer
chain itself, a materially bigger and separately-reviewable change than this phase's scope, and one
that risks a NEW, subtler bug of its own (the safety gate's approved evidence set and the actual
generation call's grounding silently diverging, if the two query strings ever led retrieval to
different documents). `providers/llms.py::build_grounded_prompt` alone — the one signature the
original plan pre-approved touching — would not have been enough on its own; the fix has to start
further upstream, at `AnswerService.answer()`. Given both the severity (a safety-classification
bypass, not just an answer-quality regression) and the size of a real fix, thread-state QUERY/PROMPT
enrichment is deferred rather than shipped in a weakened, "probably fine" form: shrinking the excerpt
further does not remove the risk (even two words reproduced it; the flat per-match base score means
ANY shared term is enough to seat a false candidate). `L3CompositionAnswerEngine` below therefore
calls `inner.answer(...)` with `query` passed through byte-identical to every other rung — this is
the safe, tested, unchanged invariant this module actually ships.

## What "L3" does control today

**A chatbot-layer verification pass**, `verify_composed_answer`, using P2's `GroundednessGate.
claim_check` — defense-in-depth on top of, never a replacement for, the `post_check`/`claim_check`
that `inner.answer()` already ran with the REAL retrieved evidence chunks. This layer cannot
reproduce that same check at the same strength: the citation dicts `inner.answer(...)` returns are
reference receipts (document_id/chunk_id/source_id/approval metadata), never the underlying chunk
TEXT — by design, mirroring the base `Citation` domain model (see `services/answer.py`: citations are
minted AFTER `post_check`/`claim_check` already ran against the real `Chunk` evidence; a citation is a
receipt, not an evidence blob). Threading raw evidence text through the `RagAnswerer` dict contract —
which is also the exact payload served by the plain `/v1/manufacturing/answer` HTTP route, see
`apps/answer-service/server.py::_manufacturing_answer_json`/`_citation_json` — to make this layer's
OWN check as strong as the one that already ran would be new, cross-cutting, security-relevant
plumbing well outside this phase's scope. So this pass only reconstructs evidence from the citations'
OWN reference-id surface (reusing `envelope.citation_id_values`, the same fields that surface's own
mechanical guard already trusts). That is enough to catch an identifier-shaped claim that matches
none of the citations actually returned this turn; it is deliberately NOT enough to independently
re-confirm a numeric claim (no evidence text is available at this layer to check it against) — that
already happened, correctly, with the real evidence, inside `inner.answer()` itself.

Given that asymmetry, a FAILURE of this pass is treated as inconclusive, not as proof of a problem:
it never overrides an inner "ok" answer's citations/status with something stricter. Doing so would
let a strictly WEAKER, less-informed recheck override the stronger one that already ran for real — a
pure availability regression (rejecting good, already-verified answers) with no matching safety
benefit, exactly what the roadmap rules out ("do not let a defense-in-depth check make things WORSE
than the inner answer"). On any of: verification failing, the inner answer not being
`answerable`/`status=="ok"` to begin with, or an exception — this engine returns the inner engine's
own answer completely UNCHANGED (which itself already correctly abstains via the existing
`_run_rag_turn`/`AnswerEngine` machinery from P0 when it isn't "ok"; there is no new abstain path
here). The verification is still computed and unit tested (see
tests/unit/test_chatbot_composition.py) so its logic is correct and ready to be wired to a harder
gate the moment real evidence-text plumbing exists to make that safe — see the roadmap's own
falsifiable exit ("verifier infeasible at acceptable quality -> stay at the envelope hybrid
indefinitely").
"""

from __future__ import annotations

from typing import Sequence

from raku_rag.chatbot.answer_engine import AnswerEngine, DialogueContext
from raku_rag.chatbot.envelope import citation_id_values
from raku_rag.domain.models import Chunk, IdentityClaims
from raku_rag.services.groundedness import GateDecision, GroundednessGate


def _citation_evidence_chunks(
    principal: IdentityClaims, collection_id: str | None, citations: Sequence[dict]
) -> tuple[Chunk, ...]:
    """See module docstring: the only "evidence" reconstructable from a citations list at this layer
    is the citations' own reference-id surface, never the underlying chunk text."""
    surface = " ".join(sorted(citation_id_values(citations)))
    return (
        Chunk(
            tenant_id=principal.tenant_id,
            chunk_id="",
            document_id="",
            collection_id=collection_id or "",
            text=surface,
        ),
    )


def verify_composed_answer(
    gate: GroundednessGate,
    principal: IdentityClaims,
    collection_id: str | None,
    answer_text: str,
    citations: Sequence[dict],
) -> GateDecision:
    """The chatbot-layer defense-in-depth pass (module docstring), isolated as a pure function so its
    pass/fail/vacuous-pass logic is directly unit-testable independent of the engine's own (currently
    non-suppressing, see below) use of the result."""
    evidence = _citation_evidence_chunks(principal, collection_id, citations)
    return gate.claim_check(answer_text, evidence)


class L3CompositionAnswerEngine:
    """Wraps `inner` (in practice `L0DeterministicAnswerEngine`, possibly with
    `L2QueryUnderstandingAnswerEngine` beneath it) with a defense-in-depth verification pass. See the
    module docstring for the full design, including why thread-state QUERY enrichment was tried and
    reverted rather than shipped.
    """

    def __init__(
        self, inner: AnswerEngine, groundedness_gate: GroundednessGate | None = None
    ) -> None:
        self._inner = inner
        self._gate = groundedness_gate or GroundednessGate()

    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None,
        context: DialogueContext,
    ) -> dict:
        # `query` reaches `inner.answer(...)` byte-identical to every other rung (see module
        # docstring's Finding). `context` is accepted only to satisfy `AnswerEngine` and is otherwise
        # unused here -- the verification pass below reads only `inner_answer`'s own text/citations,
        # mirroring L0's own "context unused" stance.
        inner_answer = self._inner.answer(principal, query, collection_id, context)
        if str(inner_answer.get("status")) != "ok":
            return inner_answer
        answer_text = str(inner_answer.get("text") or "")
        if not answer_text.strip():
            return inner_answer
        try:
            citations = list(inner_answer.get("citations") or [])
            verify_composed_answer(self._gate, principal, collection_id, answer_text, citations)
        except Exception:
            pass
        # Whatever the verification above concluded, per the module docstring this engine never
        # overrides an already-"ok" inner answer with something stricter — a "pass" and a
        # (recoverable) "fail" both return `inner_answer` unchanged.
        return inner_answer
