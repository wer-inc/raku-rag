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

### Correction (2026-07-01, discovered while starting P1): most of the generation/eval infra already exists

This roadmap originally assumed **no generative LLM existed anywhere in the answer path** and scoped
P1/P2/P4 as "build a chat-completion provider abstraction / faithfulness eval / cite-or-abstain
verifier from scratch." That assumption was wrong, and shaped a risk/effort estimate that was too
pessimistic. Investigation while starting P1 (before writing any P1 code) found a substantial,
already-tested body of work at the **base-platform layer**, currently off by default and simply not
yet wired to the chatbot's per-tenant authority ladder. It is tracked as the `P5-eval`/`P4-deploy`
workstreams in `specs/prod-readiness/ledger.json`, not under this roadmap's P-numbers (different plan,
same "P#" shorthand — don't confuse the two):

- **A real generative provider already works and is already reachable from the manufacturing/chatbot
  path.** `BedrockClaudeLLMProvider` (`src/raku_rag/providers/llms.py:285`, real Claude via Bedrock —
  `jp.anthropic.claude-sonnet-4-5-20250929-v1:0` by default) is selected by `llm_provider_from_settings`
  (`llms.py:355`, env `RAKU_LLM_PROVIDER=bedrock_claude`) and called end-to-end at
  `AnswerService.answer()` (`services/answer.py:350`, fail-closed on error). `ManufacturingSystem` (what
  the chatbot's `L0DeterministicAnswerEngine` wraps) gets its `llm` from a real `ProductionSystem` via
  `build_manufacturing_system_for_base` (`production.py:486,504-509`) — so this is not a separate
  base-platform-only code path, it is the same object the chatbot already calls through. **Turning on
  real generative prose for manufacturing/chatbot answers needs no new provider code — one env var.**
- **A cite-or-abstain-style system prompt already exists.** `build_grounded_prompt` /
  `GROUNDED_PROMPT_VERSION="grounded/v1"` (`llms.py:264-282`): answer only from evidence, refuse when
  unsupported, evidence wrapped as data/never-follow-instructions (prompt-injection defense). Pinned by
  6 green tests (`tests/unit/test_grounded_prompt.py`). This is most of what P1/P4 below called "the
  envelope"/"composition" prompt discipline.
- **An output guardrail seam already exists and is wired**, not just defined:
  `output_guardrail_provider=bedrock_guardrail` (`guardrails.py`) is called at
  `services/answer.py:443-450`, fail-closed on error/misconfiguration.
- **A release-gated eval suite already exists and already gates the pipeline.**
  `eval/baseline.py`'s `evaluate_baseline_gate` enforces `groundedness=1.0`, `citation_accuracy=1.0`,
  recall, faithfulness, latency, cost, security, and FAILS the gate on a seeded regression
  (`tests/unit/test_eval_baseline_gate.py`, `test_ci_eval_gate.py`). A **separate** safety-specific gate
  (`tests/manufacturing/test_manufacturing_eval_gate.py`) pins that a high-risk approved-citation
  violation forces `gate_result='blocked'` **regardless of the baseline score**. The bright line this
  roadmap calls non-negotiable is already a hard, tested gate — not something to build from zero.
- **The one genuinely weak link**: `GroundednessGate.post_check` (`services/groundedness.py:30-38`) is
  a *whole-answer* bag-of-words overlap check (`any(ans_terms & terms(chunk) for chunk in evidence)`) —
  fine for today's extractive text (which is built FROM the evidence, so overlap is guaranteed), but
  **not a real per-claim grounding check**: a fluent generated paragraph could share one term with a
  chunk while inventing an unsupported number elsewhere in the same answer, and this check would still
  pass it. Strengthening this (not replacing it with a brand-new parallel system) is the real P2 gap.
- **What's genuinely NOT done — and correctly so, per the project's own ledger** (`P5-3`, `P4-6`,
  `P4-7`, all `needs-human`): tuning JP-corpus thresholds against real Bedrock (billed spend, human
  gate), an actual rollback drill, and production promotion. These require real credentials and human
  sign-off; the ledger already says "the agent must not self-approve a production promotion" — this
  roadmap's own no-push/no-deploy boundary (see the autonomy scoping in the conversation this roadmap
  came from) is not a novel precaution, it matches an existing project convention.

**What this changes below**: P1, P2, and P4 are re-scoped from "build X" to "wire the chatbot's
per-tenant authority ladder to the existing X, and fix the one real gap (per-claim groundedness)".
**What does NOT change**: the conversational/multi-turn layer — coreference, thread state, envelope
phrasing carried across turns — has no existing solution anywhere in the codebase. That gap (the
original complaint: turns not connecting) is still 100% this roadmap's real, novel contribution; P0
and P3 below are unaffected by this correction.

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

### P1 — Envelope LLM (L1), demo tenant (revised — see Correction above)

Goal: the visible "chatbot感" win, with the safety contract untouched.

- **No new provider code.** Reuse `llm_provider_from_settings` / `BedrockClaudeLLMProvider`
  (`providers/llms.py`) exactly as-is; it is already unit-tested offline with an injected mock invoker
  (`tests/unit/test_bedrock_claude_llm.py`) and already reachable from the manufacturing/chatbot answer
  path (see Correction). Do not build a parallel chat-completion abstraction.
- New chatbot-layer work is narrow: an `L1EnvelopeAnswerEngine` (registered in `ChatbotService`'s
  engine map alongside L0, per the P0 seam) that gets the deterministic answer + citations from L0,
  then optionally uses the existing LLM provider ONLY for acknowledgment/connective/clarification/
  next-step phrasing wrapped around it — never for facts.
- **Mechanical guard**: every numeric token and citation id in the LLM output must be a subset of
  the deterministic answer's; on violation, render the deterministic answer verbatim.
- Gate the real Bedrock call behind BOTH the chatbot's `chatbot_authority_level=L1` for a specific
  demo tenant (P0) AND `RAKU_LLM_PROVIDER=bedrock_claude` being set. In this sandbox that env var stays
  unset (no Bedrock credentials — matches the ledger's `blocked-needs-infra` status for the live half);
  build and unit-test entirely with the existing deterministic-mock-invoker pattern. Do not attempt a
  live call without real credentials, and do not add new spend-incurring config as a default.

Gate / exit: demo shows connected, acknowledging conversation (offline, mocked-invoker path); numeric/
citation-preservation guard passes in CI; per-turn cost + latency instrumented and within budget.

### P2 — Strengthen groundedness to per-claim; reuse the existing eval gate (revised — see Correction above)

Goal: fix the one real gap identified above — a per-claim grounding check — and extend the EXISTING
release-gated eval suite rather than building a parallel one. No user-facing change required.

- **Strengthen `GroundednessGate.post_check`** (`services/groundedness.py:30`): today it's a
  whole-answer bag-of-words overlap check. Add a stricter mode (selected when the active
  `AnswerEngine` rung is L2+, i.e. genuinely generative) that verifies each numeric/identifier span in
  the answer individually against the cited chunks, not just "any term overlaps anywhere". This IS the
  "cite-or-abstain verifier" — it augments the existing gate's call site
  (`services/answer.py:421-441`), it is not a new parallel system.
  - **Faithfulness / attribution presence checks**: for each scenario assert required safety facts are
  present by *presence*, not exact string (e.g. `1.5MPa` / `30分`, cf. issue 0063). Extend
  `eval/baseline.py`'s existing `evaluate_baseline_gate` (already enforces `groundedness=1.0`,
  `citation_accuracy=1.0`, recall, latency, cost, security — see Correction) rather than
  `docs/production-readiness/eval-plan.md`'s exact-match suite, which stays as the L0-floor guard.
- The safety-specific hard block already exists (`tests/manufacturing/test_manufacturing_eval_gate.py`
  forces `gate_result='blocked'` on a high-risk approved-citation violation regardless of baseline
  score) — confirm the chatbot's `high_risk` intent path routes through this existing gate rather than
  bypassing it, don't rebuild it.

Gate / exit: strengthened per-claim check runs in CI gate on the existing eval harness; a seeded
ungrounded-claim regression fails the gate exactly like today's seeded baseline regression does.

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

### P4 — Generative composition (L3) (revised — see Correction above)

Goal: fluency jump — the LLM composes prose, not just wraps. The generation call, grounded prompt,
and release-gated eval already exist at the base-platform layer (P5-1/P5-2 in the ledger); the new
work is wiring, not building.

- `L3CompositionAnswerEngine` calls the existing `BedrockClaudeLLMProvider` (via
  `llm_provider_from_settings`) through `AnswerService.answer()` for real composed prose, using the
  existing `build_grounded_prompt`; **every factual span passes the strengthened P2 per-claim check**;
  ungrounded → abstain.
- `high_risk` category enforced mechanically via the existing `test_manufacturing_eval_gate.py`-style
  hard block (approved+effective citation or abstain); output stays `draft`.
- Deterministic floor (L0) is the fallback on verifier failure / low confidence / budget breach —
  same fallback mechanism as P1, one rung up.
- New chatbot-specific work: thread state (`DialogueContext` from P0) informs the prompt so
  composition is coherent across turns, and the release-gated eval gets multi-turn scenarios (single-
  turn faithfulness eval already exists per the Correction).

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

1. [x] P0: land the `DialogueManager` / `AnswerEngine` seam + per-tenant `chatbot_authority_level`
   (no behavior change; gate stays green). Landed `51f5a96` on `worktree-chatbot-conversational-agent`
   (isolated worktree). `AnswerEngine`/`DialogueContext`/`L0DeterministicAnswerEngine` in
   `src/raku_rag/chatbot/answer_engine.py`, `DialogueManager` in `dialogue_manager.py`,
   `ChatbotAuthorityRepository`/`InMemoryChatbotAuthorityRepository` (default `"L0"`) in
   `authority.py`. Verified independently: gate.sh all 1135 tests GREEN (was 1128 + 7 new), targeted
   chatbot suite 56 passed/3 subtests. Per-tenant authority is in-memory only for now (documented in
   `authority.py`: a Postgres-backed repository mirroring migration 0016 is deferred until a second
   rung exists to make persistence meaningful).
2. [x] P1 (revised): `L1EnvelopeAnswerEngine` landed `0ca9e1a` on `worktree-chatbot-conversational-agent`.
   New `src/raku_rag/chatbot/envelope.py`: wraps `L0DeterministicAnswerEngine`'s answer dict
   unchanged and, only when a real `LLMProvider` is configured, calls it for envelope-only text
   (acknowledgment + next-step) via `build_envelope_prompt` — a narrow prompt kept separate from
   `build_grounded_prompt`, with no retrieval context (the deterministic answer is embedded in the
   prompt itself, not passed as evidence). The mechanical guard (`is_envelope_grounded`) renders the
   wrapped text only if every numeric token and citation-id-shaped token in it is already present in
   the deterministic answer's own text/citations; guard violation, parse failure, or provider
   exception all fall back to the deterministic answer verbatim (no new provider code — reuses
   `BedrockClaudeLLMProvider`/`llm_provider_from_settings` exactly as-is). `ChatbotService` now
   registers `"L1"` in `_answer_engines` unconditionally (safe: with no LLM configured, or the
   default `ExtractiveLLMProvider`, it is a provable no-op passthrough — see tests) and accepts an
   optional `llm_provider`/`settings` plus an `enable_demo_tenant_l1` flag (default OFF) that dials
   the demo tenant's `chatbot_authority_level` to `"L1"`; `apps/answer-service/server.py` wires this
   from `system.llm` (reusing the manufacturing path's already-built provider, not a second instance)
   and a new `RAKU_CHATBOT_DEMO_TENANT_L1` env flag, still unset by default. `RAKU_LLM_PROVIDER`
   stays unset too, so this is fully offline/mocked-invoker-only in this sandbox, exactly like
   `tests/unit/test_bedrock_claude_llm.py`. Verified independently: `gate.sh all` 1160 tests GREEN
   (was 1135 + 25 new), targeted chatbot suite (service + golden scenarios + answer_engine +
   envelope) 81 passed/3 subtests (was 56 + 25).
3. [ ] P2 (revised): strengthen `GroundednessGate.post_check` to a per-claim check; extend the
   existing `eval/baseline.py` release-gated eval rather than building a parallel harness.
