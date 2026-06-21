# Implementation Plan: Eval Security & Injection Probes

**Branch**: `011-eval-security-probes` (working on `002-manufacturing-field-knowledge-rag`) | **Date**: 2026-06-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/011-eval-security-probes/spec.md` (production-readiness P0-1 / risks PR-001, PR-002)

## Summary

Make the evaluation runner **compute** its security gate signal by executing real probes during a run, instead of reflecting a caller-supplied `security_check_counts` dict that production callers never populate. Probes cover ACL leakage, deletion reappearance, tenant isolation, prompt-injection, and source-poisoning; any observed leakage forces `gate_result="blocked"`. Caller-supplied counts remain honored as a **force-block override merged by max** (so the existing protected hard-gate test stays valid unmodified, while a probe-found leak can never be downgraded by a caller). Production eval entry points run the probes, and CI asserts probes actually executed — closing the false-assurance hole permanently.

**Technical approach (key decision → research.md):** probes run against a **dedicated, deterministic probe harness** (a fresh in-memory `MvpSystem` for ACL/deletion/tenant/injection; a `ManufacturingSystem` for the high-risk poisoning probe), not against the live `self.system`. Rationale: the production caller's `self.system` is a Postgres-backed `ProductionSystem` (`apps/answer-service/server.py:504,524`) — probing it in-place would write/delete probe data in the real store. The harness exercises the **same shared security code paths** (`AclPolicy`, registry tombstone, `RetrievalService`, `AnswerService`, `SafetyGate`) that the production system uses, so a regression in those mechanisms is caught, with zero pollution and Track-A speed. Instance-specific misconfig probing is a documented follow-up.

## Technical Context

**Language/Version**: Python 3.11/3.12, stdlib-only (Track A — keep the gate fast).

**Primary Dependencies**: none new. Reuses `raku_rag.eval` (runner/models/baseline), `core/security/acl.py`, `services/{retrieval,answer,deletion}.py`, `manufacturing/safety/gate.py`, `app.MvpSystem`, `manufacturing/app.ManufacturingSystem`, `observability/redaction.py`.

**Storage**: N/A for the probe path (in-memory harness). Persisting eval runs to Postgres is out of scope (separate item P2-9).

**Testing**: `unittest` (existing). New tests are **additive** in `tests/security/` + `tests/integration/`; the protected `tests/security/test_eval_hard_gate.py` is **not modified**.

**Target Platform**: Linux CI / server (the `gate.yml` + `ci.yml` eval-gate jobs).

**Project Type**: platform library (Python core `src/raku_rag/eval/`) + thin service wiring (`apps/answer-service`, `dagster/jobs/evaluation.py`).

**Performance Goals**: Tier A stays sub-second; the 5-probe deterministic suite adds a small fixed cost (target < ~50ms).

**Constraints**: no external service in the probe path; no modification of protected hard-gate test files; the probe-definition is a **gate-design change** → independently human-reviewed commit, separate from unrelated `src/` edits (`docs/loop-engineering.md §5`).

**Scale/Scope**: 5 probe categories + synthetic adversarial fixtures; 2 production callers wired; 1 anti-regression CI assertion.

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1.*

| Principle | Verdict | Note |
|---|---|---|
| I. Groundedness First | ✅ Reinforces | Injection/poisoning probes assert the system stays grounded / refuses, never obeys embedded instructions. |
| II. Traceability | ✅ Aligned | Each `ProbeResult` records name/executed/count/redacted-reason, surfaced in the `EvaluationRun`. |
| III. Security by Design | ✅ Strongly serves | This *is* security measurement made real rather than after-the-fact. |
| IV. Pluggable Architecture | ✅ Aligned | `SecurityProbe` is an interface; probes use existing component contracts; no concrete-impl coupling. |
| V. Evaluation-Gated Delivery | ✅ Strongly serves | Fixes a gate that always passed — the core of V ("回帰があればリリースしてはならない"). |
| VI. Observable by Default | ✅ Aligned | Probe outcomes are structured and attached to the run record. |
| VII. API First | ✅ Aligned | Production eval callers (service endpoint + orchestrated job) run probes; no new public API needed for MVP. |
| VIII. Data Lifecycle Complete | ✅ Aligned | Deletion/tombstone probe exercises the lifecycle; harness is ephemeral. |

**Result: PASS — no violations. Complexity Tracking: none.**

One **human-review gate** (not a constitution violation): the probe *definitions* and the probe-target decision are hard-gate design — always-human per `loop-engineering.md §0/§6`. This plan is the artifact for that review.

## Project Structure

### Documentation (this feature)

```text
specs/011-eval-security-probes/
├── plan.md              # this file
├── research.md          # Phase 0 — key design decisions
├── data-model.md        # Phase 1 — probe entities
├── quickstart.md        # Phase 1 — validation guide
├── contracts/
│   └── probe-interface.md   # SecurityProbe contract + merge/gate semantics
├── checklists/
│   └── requirements.md  # spec quality checklist (done)
└── tasks.md             # Phase 2 — /speckit-tasks (next)
```

### Source Code (repository root)

```text
src/raku_rag/eval/
├── runner.py            # MODIFY: compute counts via probe suite; merge caller counts by max
├── probes.py            # NEW: SecurityProbe protocol, ProbeResult, SecurityProbeSuite, 5 probes
├── models.py            # MODIFY (additive): EvaluationRun carries probe_results + probes_executed
└── (adversarial fixtures: tests/fixtures/eval/adversarial.json — synthetic injection/poisoning corpus)

apps/answer-service/server.py            # MODIFY: _EvalFeedbackStore.create_run runs the probe suite
src/raku_rag/dagster/jobs/evaluation.py  # MODIFY: execute_evaluation_job runs the probe suite

tests/security/
├── test_eval_security_probes.py     # NEW: per-category planted-leak → blocked; positive controls; merge semantics
└── test_eval_hard_gate.py           # UNCHANGED (protected) — still passes: caller count=1 still blocks

tests/integration/test_eval_probes_run.py  # NEW: a real eval run computes probes (probes_executed=true)
tests/unit/test_ci_eval_gate.py            # MODIFY (additive): assert anti-regression — probes must run
```

**Structure Decision**: single-project Python core (Option 1). The probe logic is a new `src/raku_rag/eval/probes.py` consumed by `runner.py`; wiring is two small caller edits; tests are additive (no protected-file edits).

## Phased delivery (maps to user stories)

- **Phase A (US1, P1) — MVP:** `probes.py` with ACL/deletion/tenant probes + positive controls; `runner.run()` computes counts via the suite and merges caller counts by max; `EvaluationRun` gains `probe_results`/`probes_executed`. New `tests/security/test_eval_security_probes.py`. Protected test stays green. → closes most of PR-001.
- **Phase B (US2, P2):** prompt-injection + source-poisoning probes + synthetic adversarial fixtures. → closes PR-002 eval side.
- **Phase C (US3, P2):** wire `answer-service` `create_run` + dagster `execute_evaluation_job` to run the suite; add the anti-regression CI assertion. → closes the "production callers never populate" gap permanently.

Each phase: implement → `scripts/gate.sh a` (+ targeted eval tests) → `scripts/gate.sh separation` → record in `docs/production-readiness/loop-state.md`. The gate-definition diff is presented for human review before it becomes authoritative.

## Complexity Tracking

No constitution violations — table intentionally empty.
