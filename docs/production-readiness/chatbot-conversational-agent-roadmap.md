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
3. [x] P2 (revised): strengthen `GroundednessGate.post_check` to a per-claim check; extend the
   existing `eval/baseline.py` release-gated eval rather than building a parallel harness. Landed
   `ff94d73` on `worktree-chatbot-conversational-agent` (isolated worktree).
   `GroundednessGate.claim_check` (`src/raku_rag/services/groundedness.py`) is a new unconditional
   second stage inside `post_check`, run after the existing whole-answer bag-of-words overlap
   check, not behind any rung/profile flag: every numeric(+unit) and identifier-shaped span in the
   answer text (regexes mirroring — not importing, to avoid a base-platform-depends-on-chatbot-layer
   inversion — `chatbot/envelope.py`'s `numeric_tokens`/`identifier_like_tokens`) must be present in
   the union of the evidence chunks' text; a span with no numeric/identifier content passes
   vacuously (this is not "cite every sentence"). Fixed two real normalization-mismatch bugs the
   first cut of this check surfaced (found by running the full suite, not by inspection): (1)
   `°C`→`℃` — the extractive provider's `_normalize_answer_spacing` rewrites the former to the
   latter in generated text but never touches evidence chunk text, so both are now canonicalized
   before comparison; (2) a digit glued to a Japanese particle by that same normalizer removing a
   space (e.g. `"17 が"` → `"17が"`) was being misread as the number's "unit", inventing a claim
   span absent from the (still-spaced) evidence — fixed by refusing to start a unit run with that
   exact particle set. Both are now regression-pinned in the new `tests/unit/test_groundedness.py`
   (8 tests; no dedicated unit test file existed for this shared, safety-critical gate before).
   `eval/runner.py` now scores a new `claim_groundedness` metric per item via the same
   `claim_check`, wired into `eval/baseline.py`'s `DEFAULT_MIN_METRICS` at `1.0` (a real,
   generically-enforced floor, not just available to opt into) and into the committed golden-corpus
   baseline (`tests/fixtures/eval/golden_baseline.json`) + its seeded-regression subTest loop
   (`tests/integration/test_golden_corpus.py`) — measured at `1.0` on that corpus, not assumed. New
   seeded-regression tests in `tests/unit/test_eval_baseline_gate.py` prove `evaluate_baseline_gate`
   blocks on a `claim_groundedness` regression that a `groundedness`-only gate would have missed.
   Point 3 (verify, don't assume, the chatbot's high-risk path reaches the manufacturing safety
   gate): traced `ChatbotService.submit_message` → `_run_rag_turn` → `AnswerEngine.answer` → the
   injected `rag_answerer` → `manufacturing_system.answer(...)`
   (`apps/answer-service/server.py:1479-1482`, unchanged) → `ManufacturingSystem.answer`
   (`manufacturing/app.py:821`) → `ManufacturingAnswerService.answer` → `RuleHighRiskClassifier` →
   `ManufacturingSafetyGate.evaluate` (`manufacturing/safety/gate.py`) end to end. The wiring was
   already correct — a high-risk query with no approved+effective citation correctly comes back
   `insufficient_evidence`/handoff through the chatbot, confirmed by a positive control (same query,
   approved+effective citation present, chatbot answers normally) — but NO test anywhere exercised
   this specific path before (every existing chatbot test wires a hand-written `rag_answerer` stub,
   bypassing `ManufacturingSystem` entirely); added
   `ChatbotManufacturingHighRiskCitationBlockTest` (2 tests) in `tests/unit/test_chatbot_service.py`
   to pin it directly. No gap found; this was a test-coverage gap, not a safety gap. Verified
   independently: `scripts/gate.sh all` 1172 tests GREEN (was 1160 + 12 new: 8 + 2 + 2), targeted
   verification command (`test_groundedness.py test_eval_baseline_gate.py test_ci_eval_gate.py
   tests/manufacturing/test_manufacturing_eval_gate.py test_chatbot_service.py
   test_chatbot_golden_scenarios.py`) 68 passed/3 subtests.
4. [x] P3: `L2QueryUnderstandingAnswerEngine` (coreference / query understanding) landed `a585148`
   on `worktree-chatbot-conversational-agent` (isolated worktree). New
   `src/raku_rag/chatbot/coreference.py` wraps an inner `AnswerEngine` (in practice
   `L0DeterministicAnswerEngine`) and fixes the literal original complaint — "その締付トルクは?"
   after a question naming "P-101" losing the identifier entirely — with a fully deterministic,
   offline mechanism (no LLM dependency at all, per the roadmap's own framing that this problem has a
   good deterministic solution, unlike P1's envelope). Detector (`is_referential_followup`): fires
   only when there is a prior turn (`context.previous_question`), the new message is short
   (≤40 chars), contains a demonstrative/anaphoric marker, and has no identifier of its own (reuses
   `query_planner.plan_query`'s identifier extraction, not a second implementation). The marker list
   (`REFERENTIAL_MARKERS`) is built ON TOP of `query_planner.AMBIGUOUS_REFERENTS` (only pronominal
   forms — それ/これ/あれ) by adding the adnominal/anaphoric forms the roadmap's own example needs —
   その/この/あの/上記/同じ/etc. — a real gap in the shared list surfaced while implementing this
   (confirmed empirically: "その締付トルクは?" was NOT flagged ambiguous by `AMBIGUOUS_REFERENTS`
   alone). When the detector fires, `has_own_topic`/`residual_topic` decide reformat-vs-rewrite: what
   remains of the message after stripping the marker and generic elaboration glue ("もう少し詳しく
   教えて" etc.) — empty means a bare "tell me more" (reuse `context.previous_citations`/
   `previous_source_answer_text` via `answer_from_previous_turn`, generalizing
   `_previous_reformat_turn`'s mechanism to free text, no new retrieval), non-empty means the
   follow-up names a fact the prior answer is not known to cover (deterministically rewrite into a
   standalone query via `standalone_query` — merges `context.previous_question`'s identifiers, else
   its cited document ids, else its lexical terms — then calls the inner engine with THAT query).
   Deliberately NOT a text-overlap match against the previous answer: the CJK-bigram retrieval
   tokenizer makes that unreliable for short queries. `DialogueContext` gained one new field,
   `previous_source_answer_text` (the raw pre-`_format_chatbot_answer` text), needed so the reuse
   path doesn't double-wrap section headers; `DialogueManager.build_context` populates it from the
   same `source_answer_text` metadata `_previous_reformat_turn` already reads. `ChatbotService`
   registers `"L2"` as `L1EnvelopeAnswerEngine(L2QueryUnderstandingAnswerEngine(l0_engine),
   llm_provider)` — cumulative per the ladder's "+" framing (coreference first, then L1's envelope on
   top; with no LLM configured this is a provable no-op reduction to pure L2 behavior, so "L2" stays
   exactly as offline-safe as "L1") — and a new, independent `enable_demo_tenant_l2`/
   `RAKU_CHATBOT_DEMO_TENANT_L2` flag (default off) dials the demo tenant to "L2" without touching the
   existing `enable_demo_tenant_l1` flag, so an existing L1 pilot is never silently upgraded.
   Source-scope-carry: verified, not assumed — added tests proving a referential follow-up cannot
   answer using a DIFFERENT collection with no active policy (blocked before the engine is even
   resolved) and cannot survive a policy revoked between turns, using the EXISTING
   `_pre_rag_source_policy_ids`/`_filter_chatbot_citations` gate exactly as-is (no new, parallel scope
   check was added inside L2). Golden scenarios: added a coreference regression scenario to both
   `scripts/demo/chatbot_golden_scenarios.json` and `chatbot_quality_v2_scenarios.json` (turn 1 names
   "モータ M8"; turn 2 is a bare "その基礎ボルトの締付トルクは?" asserting the SAME
   `eq-motor-m8-torque` document) plus a scope-carry adversarial scenario in the v2 set, using a small
   additive extension to `scripts/demo/chatbot_golden_scenarios.py`'s `run_quick_reply_check` (an
   optional per-check `collection_id` override, defaulting to the run's own — backward compatible,
   proven by a new runner unit test) so a follow-up can target a deliberately unconfigured collection
   within one scenario run. These JSON scenarios are structurally validated here (schema + the
   runner's pure-function tests, all green) but — like every other scenario in both files — their
   actual live pass/fail requires a deployed stack, which this sandbox does not have; that is
   unchanged by this phase. Verified independently: `scripts/gate.sh all` 1211 tests GREEN (was 1172 +
   39 new), targeted verification command (`test_chatbot_service.py test_chatbot_golden_scenarios.py
   test_chatbot_answer_engine.py test_chatbot_envelope.py test_chatbot_coreference.py`) 122
   passed/3 subtests (the same 4 files pre-P3 were 83 passed/3 subtests — new
   `test_chatbot_coreference.py` added 30, the other 4 files gained 9 between them: +6
   `test_chatbot_service.py`, +2 `test_chatbot_answer_engine.py`, +1 `test_chatbot_golden_scenarios.py`
   contract test for the new per-check `collection_id` override). Deferred to a later phase: an optional
   `LLMProvider`-refined rewrite (P1 already demonstrates the safe-fallback pattern once; re-proving
   it for L2 wasn't needed to close this phase's gate, and the deterministic mechanism is what
   actually ships).
5. [x] P4 (revised — see the architectural finding below): `L3CompositionAnswerEngine` landed
   `be29cc5` on `worktree-chatbot-conversational-agent` (isolated worktree). New
   `src/raku_rag/chatbot/composition.py` wraps an inner `AnswerEngine` (in practice
   `L0DeterministicAnswerEngine`) with a chatbot-layer defense-in-depth verification pass over the
   composed answer, using P2's `GroundednessGate.claim_check` (`verify_composed_answer`) against
   synthetic evidence built from the returned citations' OWN reference-id fields
   (`envelope.citation_id_values` — document_id/chunk_id/source_id), never the underlying chunk text
   (citations are receipts, not evidence blobs, at every layer of this codebase — confirmed by
   reading the code, not assumed). The architectural question (does `"L3"` control whether real
   generation fires at all): resolved per the roadmap's own invariant — it does NOT; that stays the
   deployment-wide `Settings.llm_provider` switch (unchanged, unset by default, no Bedrock credentials
   in this sandbox). `"L3"` only adds a safety net on top of whatever `inner.answer()` (==
   `manufacturing_system.answer()`, the same call every rung uses) already returned — no second,
   tenant-dialable generation/ACL/retrieval/safety-classifier path was built. A verification failure
   is deliberately NOT wired to override an inner `"ok"` answer: it is strictly weaker/less-informed
   than the base pipeline's OWN `post_check`/`claim_check`, which already ran with the REAL evidence
   chunks before this code ever sees the answer, so downgrading on it would reject good,
   already-verified answers with no matching safety benefit — exactly what the roadmap rules out ("do
   not let a defense-in-depth check make things WORSE than the inner answer"). The check is fully
   computed and unit-tested (proven to distinguish pass/fail/vacuous-pass correctly) so it is ready to
   be wired to real enforcement once either real evidence-text plumbing exists or an explicit decision
   accepts that trade-off — not silently assumed done.

   **A significant scope change from the original plan, found by testing, not assumed**: thread-state
   QUERY enrichment (folding the prior turn's Q&A into the outgoing query string, mirroring P3's
   `coreference.standalone_query` precedent) was implemented, then investigated against exactly the
   scenario this phase's own safety test cares about (a high-risk query on a turn following an
   unrelated one) — and reproducibly broke it. `InMemoryVectorStore.lexical_matches`
   (`providers/vectorstores.py`) scores via a flat per-match base score
   (`LEXICAL_MATCH_BASE_SCORE=0.70`) plus a query-term-COVERAGE fraction (`core/hybrid_retrieval.py`),
   so appending even two words of prior-turn content ("routine inspection") to a textbook-clear,
   unrelated high-risk query ("How do I release the pressure in the hydraulic accumulator?") caused
   retrieval to hand `ManufacturingAnswerService`'s safety-gate candidate pool an unrelated, approved
   document instead of the real (draft) one — turning a query that must block into one answering
   `status="ok"`/`safety_block_reason=None` with irrelevant content. Reproduced with realistic,
   multi-sentence documents too, not just a short fixture. Properly fixing this needs to separate the
   retrieval/classification-bound query from a generation-only one across
   `ManufacturingSystem.answer()` → `ManufacturingAnswerService.answer()` → `AnswerService.answer()` —
   a materially bigger, separately-reviewable change to the safety-critical answer chain than this
   phase's scope, and one that risks a new divergence bug of its own (the safety gate approving one
   evidence set while generation grounds in a different one). Given the severity (a
   safety-classification bypass, not just a quality regression), thread-state query/prompt enrichment
   is DEFERRED rather than shipped in a shrunk, "probably fine" form — shrinking the excerpt further
   does not remove the risk (two words already reproduced it). `L3CompositionAnswerEngine` therefore
   passes `query` through to `inner.answer(...)` byte-identical to every other rung; pinned by
   `test_chatbot_composition.py::L3CompositionAnswerEngineTest::
   test_query_reaches_inner_byte_identical_regardless_of_thread_state`. Full reasoning:
   `chatbot/composition.py`'s module docstring.

   `ChatbotService` registers `"L3"` as `L1EnvelopeAnswerEngine(L2QueryUnderstandingAnswerEngine(
   L3CompositionAnswerEngine(l0_engine)), llm_provider)` — cumulative per the ladder's "+" framing
   (coreference resolution runs first, then L3's verification pass, then L1's envelope wraps the
   outermost result) — plus a new, independent `enable_demo_tenant_l3`/`RAKU_CHATBOT_DEMO_TENANT_L3`
   flag (default off), mirroring L1/L2's own opt-in dial exactly.

   Point 4 (verify, not assume, that the high-risk safety block reaches L3 specifically): added
   `ChatbotManufacturingHighRiskCitationBlockAtL3Test` (4 tests) to
   `tests/unit/test_chatbot_service.py` — a tenant explicitly dialed to `"L3"` via
   `InMemoryChatbotAuthorityRepository`, wired to a real in-memory `ManufacturingSystem` exactly like
   P2's own L0-level proof. Beyond mirroring P2's single-turn positive/negative control, this adds a
   genuine MULTI-TURN variant (an unrelated first turn establishing real thread state, THEN the
   high-risk query, in the SAME session) — the exact shape that caught the query-enrichment bug above;
   with the reverted (pass-through) design, both the negative control (draft citation → blocked,
   `status=insufficient_evidence`) and the positive control (approved citation → answered) hold on
   both a fresh session and a later turn in an ongoing one. Confirmed by direct code trace (not just
   tests) that every path from `ChatbotService.submit_message` through `L1EnvelopeAnswerEngine →
   L2QueryUnderstandingAnswerEngine → L3CompositionAnswerEngine → L0DeterministicAnswerEngine` ends at
   the SAME injected `rag_answerer` (`manufacturing_system.answer(...)` in production) with no
   alternative code path — `composition.py` never constructs an answer independent of
   `inner.answer()`'s own return value.

   Eval: added a multi-turn scenario (`composition-motor-m8-multiturn-followup` /
   `v2-composition-motor-m8-multiturn-followup`, tagged `["composition","multi_turn","l3"]` in the v2
   set) to `scripts/demo/chatbot_golden_scenarios.json` and `chatbot_quality_v2_scenarios.json`,
   reusing the already-seeded `eq-motor-m8-torque` equipment (not inventing unverifiable new document
   content) with a follow-up naming a NEW fact on the same equipment (insulation resistance /
   retightening interval) so it exercises a fresh search through the full L3 stack, not the
   bare-pronoun reuse P3's own scenario already covers. `eval/baseline.py`/`eval/runner.py` (P2's own
   extension point) were NOT touched again: those are single-turn, base-platform constructs with no
   notion of a conversation, so — consistent with P3 also choosing the chatbot-specific golden-scenario
   JSON files, not `eval/baseline.py`, for its OWN multi-turn work — a multi-turn scenario belongs in
   the same place P3's did. Like every other scenario in both files, live pass/fail requires a deployed
   stack this sandbox does not have; structurally validated here (schema + `--validate-only` + the
   runner's pure-function tests, all green).

   Verified independently: `scripts/gate.sh all` 1231 tests GREEN (was 1211 + 20 new: 16 in the new
   `test_chatbot_composition.py` + 4 in `test_chatbot_service.py`'s new class), targeted verification
   command (`test_groundedness.py test_eval_baseline_gate.py test_ci_eval_gate.py
   tests/manufacturing/test_manufacturing_eval_gate.py test_chatbot_service.py
   test_chatbot_golden_scenarios.py test_chatbot_answer_engine.py test_chatbot_envelope.py
   test_chatbot_coreference.py test_chatbot_composition.py`) 159 passed/3 subtests. One pre-existing
   test (`test_chatbot_answer_engine.py`'s
   `test_resolve_answer_engine_falls_back_to_l0_for_unregistered_level`) used `"L3"` as its example of
   an unregistered authority level (stale now that this phase registers it for real) — updated to
   `"L4"` (P5, still unregistered); a one-line fix, not a design change. Deferred to P5 (agentic
   control / tool use — a large remaining piece, not accidentally solved here): the LLM deciding
   when/what to retrieve, multi-hop, autonomous clarifying questions; and, as a narrower, explicitly
   scoped follow-on to THIS phase specifically: a properly separated retrieval-bound/generation-bound
   query channel through the manufacturing answer chain, IF thread-state prompt enrichment for
   composed prose is wanted badly enough to justify that bigger, separately-reviewed change.
6. [x] Safety audit (2026-07-01): does P3's `coreference.standalone_query` rewrite have the SAME
   query-enrichment bug P4 found and reverted for L3 (item 5's "Finding")? **Yes — reproduced
   empirically, then fixed (not reverted), since P3's rewrite is real and shipped, unlike L3's
   never-shipped attempt.** Full reasoning lives in `chatbot/coreference.py`'s module docstring
   "Finding" (mirroring `composition.py`'s own docstring rigor); this entry is the short version.
   - **Reproduction**: turn 1 = an ordinary English query answered citing an APPROVED, unrelated
     document (same fixture shape as item 5's `ChatbotManufacturingHighRiskCitationBlockAtL3Test`).
     Turn 2 = a short, Japanese, referential-marker-bearing follow-up with no identifier of its own
     ("その圧力の抜き方を教えて") whose RAW text independently classifies `high_risk` via
     `RuleHighRiskClassifier`'s KEYWORD stage ("圧力"/pressure) — confirmed directly, not assumed. The
     real, on-topic document was ingested `PENDING_REVIEW` (unapproved). Because
     `L2QueryUnderstandingAnswerEngine` takes the REWRITE branch here (`has_own_topic` is true — this
     is not the bare "tell me more" reuse branch), `standalone_query` appended turn 1's carried
     signal to the outgoing query text; the corrupted retrieval candidate pool then handed the
     manufacturing safety gate turn 1's unrelated APPROVED document, flipping the answer from the
     correct `insufficient_evidence`/`approved_citation_missing` to `status="ok"`, citing the wrong
     content — reproduced identically at BOTH `"L2"` and `"L3"` authority (L2 wraps L3 in
     `service.py`'s own engine map, so L3-dialed tenants were exposed to the identical risk; a stale
     inline comment there claiming otherwise — "L3 does NOT enrich the query... so this ordering is
     not load-bearing for safety" — was corrected in the same edit).
   - **Fix**: a new, optional `high_risk_query_signal: Callable[[str], bool] | None` seam on
     `L2QueryUnderstandingAnswerEngine`/`ChatbotService` (default `None` = byte-identical to
     pre-fix behavior — no regression for any deployment that doesn't wire it). When wired and it
     fires on the RAW follow-up text, the rewrite branch is skipped and the RAW query passes straight
     through to `inner.answer(...)` instead — the same passthrough a self-contained query already
     gets, never the reuse-previous-citations branch (which would serve turn 1's unrelated content
     unconditionally, with no classifier/gate re-evaluation at all — less safe, not more). The
     production wiring (`apps/answer-service/server.py`) injects
     `ManufacturingSystem.is_high_risk_query_signal` → `ManufacturingAnswerService.
     classify_query_signal`, which reuses the SAME classifier instance the real safety gate consults
     (never a second, drifting one), called with empty candidate metadata (retrieval hasn't run yet)
     so only the query-text-driven METADATA/KEYWORD stages can ever fire.
   - **The one non-obvious design point, verified empirically before shipping**: a naive
     "skip whenever the classifier says `is_high_risk`" would ALSO fire for nearly every short
     Japanese follow-up, INCLUDING P3's own benign flagship case ("その締付トルクは?") — confirmed
     directly: Japanese text has no spaces, so `core.text.content_tokens` cannot word-segment it,
     collapsing a whole short sentence into one "token" and tripping the classifier's stage-3
     "ambiguous, too terse to rule danger out" fail-safe regardless of actual content. That fail-safe
     is correct for the FINAL "may this answer assert" decision but is not itself a concrete danger
     signal, so `classify_query_signal` deliberately excludes it (only a `METADATA`/`KEYWORD`
     `classification_source` counts) — otherwise this fix would have silently gutted P3's actual
     value for its primary (Japanese) audience with no safety benefit. Proven with a dedicated
     regression test (`tests/manufacturing/test_safety_gate.py::TestHighRiskQuerySignal
     ::test_short_ambiguous_japanese_query_is_not_flagged_despite_the_classifier_failing_safe`) and
     an end-to-end one through the full chatbot+manufacturing stack
     (`ChatbotL2CoreferenceHighRiskSafetyTest
     ::test_benign_referential_followup_is_still_rewritten_and_answered_with_the_fix_wired`).
   - New tests (15): `tests/manufacturing/test_safety_gate.py::TestHighRiskQuerySignal` (3, classifier
     boundary), `tests/unit/test_chatbot_coreference.py::HighRiskQuerySignalGateTest` (6, engine
     decision logic against a fake signal), `tests/unit/test_chatbot_service.py::
     ChatbotL2CoreferenceHighRiskSafetyTest` (6: raw-classification premise, unmitigated repro
     [permanent regression pin], mitigated negative control at L2 AND L3, positive control, P3-value-
     preserved control) — same positive/negative-control discipline as item 5's own high-risk tests,
     using a real `ManufacturingSystem` + `ChatbotService`, not a stub.
   - Verified independently: `scripts/gate.sh all` 1246 tests GREEN (was 1231 + 15 new); targeted
     verification command (item 5's list plus `tests/manufacturing/test_safety_gate.py`) 182
     passed/3 subtests (was 159 + 15 + 8 pre-existing in that file newly included = 182). No existing
     test weakened; the pre-fix behavior stays reachable (and is itself pinned, unmitigated, by the
     "permanent regression pin" test above) for any caller that does not opt into
     `high_risk_query_signal`.
