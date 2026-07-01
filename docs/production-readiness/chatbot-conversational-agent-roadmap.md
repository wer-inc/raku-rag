# ChatBot Conversational Agent Roadmap (Full-A)

Status: Draft for implementation planning
Date: 2026-07-01
Owner: production-readiness / chatbot conversational UX

## Purpose

Goal: a chatbot that *feels* like a chatbot — turns connect, it acknowledges, it remembers the
thread, it asks targeted follow-ups, it discloses progressively — reached as a **full agentic**
assistant. The user set the destination as "full".

We adopt **Full-A**, not Full-B:

- **Full-A (agentic control, cited facts)** — the LLM runs the conversation loop (decides when to
  retrieve, rewrites queries, multi-hop, clarifies, composes fluent prose, manages thread state) but
  every factual claim / number / procedure in the answer is constrained to an approved+cited chunk
  (cite-or-abstain, verified). **This is the destination.**
- **Full-B (generated facts)** — the LLM answers from context + parametric knowledge with no hard
  cite-or-abstain. **Rejected**: in a manufacturing safety context this converts the product's only
  moat (safe / auditable / no unsupported assertion) into its largest liability.

### Relationship to existing plans (no duplication)

This roadmap is the **conversation & agency axis**. It sits *on top of* the existing
**answer-quality axis** and reuses its seams:

- `docs/production-readiness/chatbot-sellable-quality-plan.md` — single-turn answer quality
  (query planner, hybrid retrieval, reranker, structured composer, profiles). We **reuse** its
  profile seam (`stg-smoke` / `demo-quality` / `production-quality`, human-approved promotion) and
  quality gates. We **do not** re-plan retrieval/ranking here.
- `specs/023-rag-chatbot-agent/` — the formal chatbot spec (contracts, data model).
- Issues `0052`, `0054`, `0057`, `0061`, `0063` — symptoms of the missing conversation layer
  (quick replies feeling same-y, context lost across turns, generic clarification). This roadmap
  fixes the *layer*, which retires the *class*.

## The one architectural invariant

> **Do not replace the deterministic engine. Layer the agentic LLM on top of it as a
> progressively-enabled upgrade. The deterministic + cited path (`stg-smoke` / existing composer)
> stays as the permanent safe floor and the fallback.**

Consequences (these are why the whole plan is shaped this way):

- **Never worse than today.** Worst case at any rung is current behavior.
- **Reversible + dialable.** The LLM's authority is a per-tenant dial (see ladder). Any tenant can
  be returned to L0 instantly; a verifier failure / low confidence / cost-budget breach auto-falls
  back to the deterministic floor.
- **Blast radius bounded** on a live, billing, multi-tenant, safety-critical system operated with
  thin (~1–2h/day) supervision.

### The bright line (non-negotiable)

> The model never emits an un-cited factual / safety assertion. `high_risk` answers require an
> approved + effective citation or they abstain → human handoff. AI output stays `draft`
> (CLAUDE.md hard rules; the safety boundary is always human).

## Authority ladder (the backbone)

Each rung grants the LLM one more unit of authority and is defended by the gate named in its phase.
The rung is a per-tenant setting (default L0). L0 is always present as floor + fallback.

| Rung | LLM authority | Facts | Scope/ACL | Defended by |
|------|---------------|-------|-----------|-------------|
| **L0** Deterministic floor (today) | none | extractive | pre-filter | exact-match golden gate |
| **L1** Envelope | phrasing only (ack / connectives / clarification wording / next-step) | unchanged deterministic answer | unchanged | mechanical guard: numeric tokens + citation ids in output ⊆ deterministic answer, else fall back |
| **L2** Query understanding | + coreference / standalone-question rewrite feeding existing retrieval | extractive | may NOT widen prior turn's approved source scope | source-scope-carry check + faithfulness eval |
| **L3** Composition | + composes answer prose | every factual span grounded in a cited chunk | pre-filter | **cite-or-abstain verifier** (hard) + faithfulness eval |
| **L4** Agency (Full-A) | + decides when/what to retrieve, multi-hop, clarifying questions, thread mgmt | grounded | enforced structurally *below* the LLM, never by prompt | verifier + injection/isolation guard + cost cap |

## Phased plan

Each phase enables one rung. Rollout of any user-facing change: **dark → demo tenant → friendly
pilot → GA**, per-tenant authority dial, human-approved promotion (per the quality plan).

### P0 — Cut the seam (no behavior change)

Goal: separate conversation management from answer generation so authority is swappable.

- Extract a **`DialogueManager`** (conversation controller) that owns thread state (topic, entities,
  last citations, active source scope) + turn routing, and calls a pluggable **`AnswerEngine`**.
- Introduce the `AnswerEngine` interface; widen the current `RagAnswerer` seam
  (`Callable[[IdentityClaims, str, str|None], dict]`, `src/raku_rag/chatbot/service.py:25`) so an
  engine can receive conversation context, not just a bare query string.
- The existing deterministic answerer becomes `AnswerEngine`'s L0 implementation (the floor).
- Add **per-tenant `chatbot_authority_level`** config (default `L0`) — the reversibility mechanism.
- Refactor `submit_message` (`service.py:438`) / `_run_rag_turn` (`:1024`) to delegate; reuse
  `_last_answer_context` (`:1523`) as the thread-state reader.

Gate / exit: pure refactor — **all existing golden scenarios still pass exact-match, `scripts/gate.sh`
green, CI gate green**. Safe to land unattended; fully reversible.

### P1 — Envelope LLM (L1), demo tenant

Goal: the visible "chatbot感" win, with the safety contract untouched.

- Wire a **chat-completion provider** behind a provider abstraction (mirror the opt-in embedding
  provider pattern in `src/raku_rag/providers/embeddings.py:67` + the `RAKU_RUNTIME_PROFILE` seam).
  Include a **deterministic mock** so the gate stays offline/fast.
- LLM does **only**: acknowledgment/reflection, connective phrasing, clarification wording,
  next-step suggestion. It receives the deterministic answer + citations and *wraps* them.
- **Mechanical guard**: every numeric token and citation id in the LLM output must be a subset of
  the deterministic answer's; on violation, render the deterministic answer verbatim.
- Ship at authority **L1 to the demo tenant only**, flag-gated. All other tenants stay L0.

Gate / exit: demo shows connected, acknowledging conversation; numeric/citation-preservation guard
passes in CI; per-turn cost + latency instrumented and within budget.

### P2 — The enabling gate: faithfulness eval + cite-or-abstain verifier (infra)

Goal: replace the measurement that generation invalidates, *before* handing the model fact
authority. No user-facing change required.

- **Faithfulness / attribution eval harness**: for each scenario assert (a) every factual claim is
  supported by a cited chunk, (b) no un-cited safety assertion, (c) required safety facts present
  (checked by *presence*, not exact string — e.g. `1.5MPa` / `30分`, cf. issue 0063). Coexists with
  the exact-match suite (which continues to guard the L0 floor). Extend
  `docs/production-readiness/eval-plan.md` and the scorecard.
- **cite-or-abstain verifier**: given a candidate answer + retrieved chunks, verify each factual span
  is grounded; ungrounded span → strip or abstain → handoff. `high_risk` → approved+effective
  citation or abstain. This is the hard enforcement that makes L3 possible.

Gate / exit: faithfulness eval runs in CI gate; verifier callable and wired so a failing generative
answer auto-abstains to the floor.

### P3 — Coreference / query understanding (L2)

Goal: turns connect at the retrieval level — this is the fix for the original complaint
("前回の会話と次の質問が繋がらない").

- LLM rewrites the follow-up into a **standalone query** using thread state (proper replacement for
  the fragile string-concat heuristic; gate on the existing `AMBIGUOUS_REFERENTS` + identifier
  signal in `src/raku_rag/core/query_planner.py`). Feeds the existing deterministic retrieval; facts
  stay extractive + cited.
- **Source-scope-carry check**: the rewrite must stay within the prior turn's approved source policy
  / collection and never widen it (`_pre_rag_source_policy_ids`, `_filter_chatbot_citations`).
- Try **reformat-from-last-citations first** (generalize `_previous_reformat_turn` to free text);
  only fall through to a new retrieval when new info is genuinely needed.

Gate / exit: new **multi-turn coreference** golden scenarios pass under faithfulness eval; scope-carry
proven not to widen; ship L2 demo → pilot.

### P4 — Generative composition (L3)

Goal: fluency jump — the LLM composes prose, not just wraps.

- LLM composes the answer; **every factual span passes the P2 verifier**; ungrounded → abstain.
- `high_risk` category enforced mechanically (approved+effective citation or abstain); output stays
  `draft`.
- Deterministic floor is the fallback on verifier failure / low confidence / budget breach.

Gate / exit: attribution ≥ threshold on the eval set; **zero un-cited safety assertions** in an
adversarial test; cost within budget; ship L3 demo → pilot, authority-dialed.

### P5 — Agentic control / tool use (L4) = Full-A destination

Goal: the LLM runs the loop — when/what to retrieve, multi-hop, autonomous clarifying questions,
thread management.

- Scope / ACL / tenant / source-policy enforced **structurally below the LLM** in context assembly —
  never by prompt. The LLM cannot widen scope.
- Prompt-injection hardening matured: evolve `_is_security_refusal_request` (`service.py:1837`) into
  a proper input/output guard; tenant isolation asserted in context assembly and re-asserted on
  every citation.
- Per-tenant / per-risk / per-cost authority dial governs how much of the loop the model owns.

Gate / exit: ongoing faithfulness + cost monitoring; ship demo → pilot → GA with human-approved
promotion.

## Cross-cutting tracks (run continuously, not sequentially)

- **Safety / verifier** — the bright line; matures across phases; hard gate for L3+.
- **Eval** — exact-match (L0 floor) + faithfulness/attribution (generative) coexist; adversarial
  safety set for L3+.
- **Cost / latency** — instrument from P1; per-tenant cost caps; auto-fallback to floor on breach.
  (Existing plan budget: p95 < 8s synthesis, < 2s smoke.)
- **Security** — prompt-injection + tenant-isolation hardening scales with authority; enforced below
  the LLM.
- **Rollout** — authority flag: dark → demo → friendly pilot → GA, human-approved (per quality plan).

## Quality gates (extends the quality plan's gates)

- L0 exact-match golden suite stays green at all times (the floor never regresses).
- No rung ships past L1 without the P2 faithfulness eval + verifier in CI.
- L3+ requires: attribution ≥ threshold, zero un-cited safety assertions on the adversarial set,
  cost within per-tenant budget, human-approved promotion beyond the demo tenant.

## Risks

- **Cost/latency blow-up per turn** → instrument early, per-tenant caps, deterministic fallback.
- **Prompt injection → scope/ACL/PII bypass** → enforce scope structurally below the LLM; guard
  in/out; re-assert ACL on every citation.
- **Non-determinism hides regressions** → keep the deterministic floor + exact-match suite; add
  faithfulness + adversarial sets.
- **Verifier infeasible at acceptable quality** → then Full-A itself is in question; stay at the
  envelope hybrid (L1/L2) indefinitely. This is the roadmap's explicit falsifiable exit.

## Immediate next tasks

1. [ ] P0: land the `DialogueManager` / `AnswerEngine` seam + per-tenant `chatbot_authority_level`
   (no behavior change; gate stays green).
2. [ ] P1: wire the chat-completion provider abstraction + deterministic mock; envelope prompt +
   numeric/citation preservation guard; ship L1 to the demo tenant behind a flag.
3. [ ] P2: stand up the faithfulness/attribution eval harness + cite-or-abstain verifier.
