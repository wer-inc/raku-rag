# Feature Specification: Eval Quality Depth (precision/MRR, faithfulness, golden corpus)

**Feature Branch**: `012-eval-quality-depth`

**Created**: 2026-06-21

**Status**: Draft (US1 precision/MRR done; US2 faithfulness in progress; US3 golden corpus pending)

**Input**: Production-readiness audit 2026-06-21 **P1-5** + critique (PR-008). The blocking eval-gate measures retrieval with only `recall_at_k` (a binary set-overlap hit-rate), scores generation with a shallow structural `groundedness` proxy (status==ok AND has-citations AND has-used-chunks — it cannot catch a plausibly-worded unsupported answer), runs over a 1–2 item fixture, and compares each run to a baseline derived from *itself* (`baseline_from_run`). So the gate proves the mechanism, not answer quality, and cannot detect ranking or faithfulness regressions.

## Overview

Deepen the evaluation harness so the release gate measures real retrieval ranking quality and real answer faithfulness over a representative corpus with a committed baseline — turning the gate from a mechanism check into a quality-regression detector. Builds on `011-eval-security-probes` (same `eval/` area). Stdlib-first (Track A): all metrics deterministic and fast; LLM-as-judge faithfulness is an optional future overlay, not required for the gate.

Enforces Constitution **Principle V (Evaluation-Gated Delivery)** — "評価指標（recall/precision、回答の正確性…）はベースラインに対して測定されなければならない".

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Real retrieval ranking metrics (Priority: P1) — DONE

Retrieval quality is reported with **precision@k** and **MRR** (rank-sensitive), not only `recall_at_k`.

**Independent Test**: an eval run reports `precision_at_k` and `mrr`; for a fixture whose only relevant doc is retrieved at rank 1, both are 1.0.

**Acceptance Scenarios**:
1. **Given** an eval set with expected evidence, **When** the runner runs, **Then** `metrics` includes `precision_at_k` and `mrr` graded over items that carry expected evidence.

### User Story 2 - Deterministic faithfulness metric (Priority: P1)

Generation is scored by **how much of the asserted answer is actually supported by the cited evidence**, not merely whether a citation exists — a deterministic claim-support metric (answer terms covered by used-evidence terms), with an optional LLM-judge overlay later.

**Why this priority**: closes the "plausible-but-unsupported answer scores 1.0" hole (audit dimension E + critique). Deterministic so it runs in the gate.

**Independent Test**: an answer whose asserted text is fully contained in its cited evidence scores `faithfulness==1.0`; an answer asserting terms absent from the evidence scores `<1.0`; an answer with no overlap scores `0.0`.

**Acceptance Scenarios**:
1. **Given** an `ok` answer with `used_chunks`, **When** the runner runs, **Then** `metrics["faithfulness"]` = mean over asserted answers of (answer terms ∩ used-evidence terms) / (answer terms).
2. **Given** an answer that asserts content not present in its cited evidence, **When** scored, **Then** `faithfulness < 1.0` (the metric catches the unsupported assertion).
3. **Given** the existing `groundedness` metric, **When** faithfulness is added, **Then** `groundedness` is unchanged (faithfulness is additive; existing gates not weakened).

### User Story 3 - Representative golden corpus + committed baseline (Priority: P1) — PENDING

A per-industry golden eval corpus (materialize `tests/fixtures/uat/`) and a **committed** `baseline.json` replace the self-derived `baseline_from_run`, so cross-commit quality drift is detectable.

**Why this priority**: without a representative corpus + fixed baseline, precision/MRR/faithfulness over 1–2 items still can't detect regressions (critique PR-008).

**Independent Test**: the CI eval-gate compares a run to a committed golden baseline; a seeded quality drop (lowered retrieval/faithfulness) fails the gate.

**Acceptance Scenarios**:
1. **Given** a committed golden baseline, **When** a run regresses precision/MRR/faithfulness below it, **Then** the baseline gate fails.

### Edge Cases
- Item with no expected evidence → excluded from precision/MRR denominator (recall_at_k stays a per-item hit-rate for continuity).
- Answer with no asserted text (insufficient_evidence) → excluded from the faithfulness denominator (not applicable), never scored 0 punitively.
- Empty corpus → metrics are 0.0, not a divide-by-zero.

## Requirements *(mandatory)*

- **FR-001**: The runner MUST report `precision_at_k` and `mrr` graded over items carrying expected evidence. *(done)*
- **FR-002**: The runner MUST report a deterministic `faithfulness` metric = mean over `ok` answers with `used_chunks` of (answer content-terms supported by used-evidence content-terms).
- **FR-003**: `faithfulness` MUST be additive — `groundedness` and all existing metrics/gates keep their current semantics and thresholds.
- **FR-004**: The faithfulness computation MUST be deterministic and stdlib-only (Track A); any LLM-as-judge overlay is optional and out of the gate path.
- **FR-005**: A representative per-industry golden corpus and a committed baseline MUST replace the self-derived baseline for the gate, and a seeded quality drop MUST fail the gate. *(US3, pending)*
- **FR-006**: New metrics become release-blocking thresholds only against the committed golden baseline (not the 1–2 item smoke fixture), to avoid over-fitting the gate to a smoke set.

### Key Entities
- **EvaluationRun.metrics** (existing): gains `precision_at_k`, `mrr`, `faithfulness` (additive).
- **GoldenCorpus** (US3): per-industry `EvaluationSet` materialized from `tests/fixtures/uat/`.
- **Committed baseline** (US3): `tests/fixtures/eval/baseline.json` with fixed metric thresholds.

## Success Criteria *(mandatory)*

- **SC-001**: Retrieval is reported with precision@k and MRR in addition to recall@k. *(met)*
- **SC-002**: An unsupported assertion scores `faithfulness < 1.0` while a fully-supported answer scores 1.0 (the metric discriminates).
- **SC-003**: Adding faithfulness leaves every existing eval test green (additive, no weakening).
- **SC-004**: A seeded quality regression against the committed golden baseline fails the CI eval-gate. *(US3)*
- **SC-005**: Tier A stays GREEN and sub-second.

## Assumptions
- Term-extraction reuses `raku_rag.core.text.content_terms` (the same basis the groundedness post-check uses), so faithfulness is consistent with the existing grounding notion but graded (fractional) rather than boolean.
- The deployed generator is currently the deterministic `ExtractiveLLMProvider` (faithful by construction ⇒ faithfulness ≈ 1.0); the metric's value is regression detection when a real LLM ships (and it is unit-tested on partial/zero-support cases via the pure helper).
- Golden corpus (US3) is synthetic (no real PII/secrets); materialization is a separate slice.
