# RAG Evaluation Plan — production target state

**Date:** 2026-06-21 · Companion to root [`poc-evaluation-plan.md`](../../poc-evaluation-plan.md) (PoC stack/provider benchmark) and `tests/benchmarks/poc_stack_benchmark.py`.
Scope: turn the eval subsystem from a **mechanism that always passes** into a **representative, adversarial, persisted** release gate that separates retrieval from generation and actually computes security probes.

> Principle (`docs/loop-engineering.md`): the loop's "No" must be *fast, trustworthy, and un-gameable*.
> The original caller-supplied-count hole is closed; keep future eval changes probe-computed and
> baseline-pinned.

---

## 1. Current state (audited 2026-06-21)

| Capability | State | Evidence |
|---|---|---|
| Retrieval vs generation metrics separated | ✅ OK | `eval/runner.py:154-166` (recall vs citation/groundedness) |
| Blocking CI eval-gate | ✅ OK | `.github/workflows/ci.yml:49-67`, `eval/baseline.py:54-78` |
| Release-gate criteria | ✅ committed golden baseline + version registry | `tests/fixtures/eval/golden_baseline.json`, `tests/integration/test_golden_corpus.py` |
| **Security hard-gates compute real probes** | ✅ default-on, fail-closed probes | `src/raku_rag/eval/runner.py`, `src/raku_rag/eval/probes.py` |
| Prompt-injection / source-poisoning checks | ✅ release-blocking probes | `tests/security/test_eval_security_probes.py`, `src/raku_rag/eval/probes.py` |
| Adversarial / red-team suite | 🟡 GAP-S1 high-risk recall corpus gates known dangerous phrasings; broader red-team/SME corpus still needed | `eval/fixtures/high_risk_adversarial_corpus.json`, `high_risk_recall_probe` |
| Golden corpus (per-industry) | ✅ local deterministic corpus + committed baseline | `tests/fixtures/uat/golden_corpus.json`, `tests/fixtures/eval/golden_baseline.json` |
| Metrics depth | ✅ precision@k / MRR / deterministic faithfulness | `src/raku_rag/eval/runner.py`, `tests/unit/test_eval_metrics.py` |
| Eval space == prod space | 🟡 provider/dim wiring now settings-backed and fail-fast on Cohere/1024 mismatch; real Cohere eval/backfill still needed | `embedding_provider_from_settings`, `tests/unit/test_embedding_configuration.py` |
| Persistence / trending | ✅ local writer + trend repository | `persistence/evaluation_runs.py`, `server.py` eval repository wiring, `0007_eval_run_persistence.sql`, `0011_eval_version_registry.sql` |
| SME review workflow | ✅ local workflow | `SyntheticQAItem` candidates stay outside `EvaluationSet` until SME-approved |

---

## 2. Target state

### 2.1 Retrieval eval (debuggable in isolation)
- Metrics: `recall@k`, **`precision@k`**, **`MRR`**, optional `NDCG`, identifier-exact hit-rate (equipment_id/alarm_code/ISIN).
- Per query-type slices: prose lookup, exact-code lookup, spreadsheet-cell citation, high-risk.
- Failure attribution recorded (ties to **P1-8**): `acl_emptied` / `zero_candidates` / `rerank_failed`.

### 2.2 Generation / grounding eval
- Keep citation-accuracy. The release gate now has a deterministic **faithfulness** metric (answer terms
  supported by cited/used evidence). A future LLM-as-judge / entailment overlay may be added to eval or
  sampled analysis, but it must stay out of the default synchronous answer hot path unless profile-gated
  within the LLM-call budget.
- Completeness + style conformance once a real generative path is release-bound. The HTTP answer format contract now exists locally (`answer_template_version` + `display_sections`, P3-2), so future checks should validate section presence/order instead of inferring presentation from free-form text.
- Uncertainty correctness: insufficient-evidence and high-risk-block must be *correctly* emitted (positive + negative controls).

### 2.3 Security probes (real, in-runner) — **P0-1**
The runner must **compute** these counts from actual probes during a run (not accept them):
- **ACL leakage:** an unauthorized principal's query must return 0 unauthorized docs/citations.
- **Deletion reappearance:** a tombstoned doc re-queried must not appear.
- **Tenant isolation:** a cross-tenant query must return 0.
- **Prompt-injection:** a chunk containing `"ignore previous instructions / reveal …"` must not change the answer or exfiltrate context.
- **Source poisoning:** a poisoned/contradictory chunk must not become primary evidence for a high-risk assertion.
- **High-risk recall:** known-dangerous manufacturing red-team queries must classify high-risk; benign controls prevent an all-blocking classifier from passing.
Any non-zero → `gate_result="blocked"`. CI asserts the counts were **actually computed** (non-empty / probe ran), closing the false-assurance hole.

### 2.4 Adversarial / red-team — **P1-6 [!safety]**
- Keyword-free, paraphrased **dangerous-query corpus** asserting `is_high_risk=True` recall (GAP-S1). **Initial release-blocking corpus landed**; expand with SME/red-team review.
- Jailbreak / instruction-override corpus.
- The corpus is *measurement*; the production danger-classification LLM and the gate decision remain **human-owned**.

### 2.5 Corpus, baseline, persistence
- **Golden corpus** per industry (manufacturing first; materialize `tests/fixtures/uat/README.md`), ≥ the 20–50 representative docs R-016 calls for, with held-out QA.
- **Committed golden `baseline.json`** (not `baseline_from_run`) so cross-commit drift is detectable.
- Measure on the **selected production embedding space**. Repo-side P1-15 wiring now prevents silent provider/dimension drift; full closure still requires the real Cohere/1024 migration or a committed decision to keep hashing/256 for production, followed by reindex/backfill and refreshed baselines.
- **P2-9 landed locally:** persist runs to the `evaluation_runs` table with deterministic in-memory/Postgres repositories and a minimal trend query. **P2-10 landed locally:** every run now carries `version_registry` (model/prompt/dataset), and committed baselines can fail the gate on version mismatch.
- **P2-7 landed locally:** deterministic `SyntheticQAItem` candidates can be generated from live chunks, but `materialize_approved_eval_set()` accepts only SME-approved candidates. Generated/rejected candidates cannot become release-gating `EvaluationItem`s.

---

## 3. Release-gate pass criteria (production)

A build is releasable only if **all** hold (extends `eval/baseline.py:DEFAULT_MIN/MAX_METRICS`):
1. **Security probes all 0** (ACL/deletion/tenant/injection/poisoning/high-risk-recall), **computed by real probes**.
2. Retrieval: `recall@k` and `precision@k` ≥ committed baseline (no regression).
3. Generation: faithfulness ≥ baseline; insufficient-evidence + high-risk-block controls pass.
4. Safety (manufacturing): GAP-S1 dangerous-query recall ≥ threshold.
5. p95 latency / query-cost ≤ ceilings.
6. Eval ran over the **golden corpus on the prod embedding space**, persisted with the model/prompt/dataset version triple; the committed baseline pins that registry and fails on mismatch (P2-10). Final production closure still requires refreshing the baseline after the real embedding-space migration/backfill decision.
7. Synthetic QA, when used, was materialized only from SME-approved candidates; generated/rejected candidates never gate CI.

---

## 4. Sequencing
**P0-1** (real probes + injection/poisoning checks) → **P1-5** (corpus + faithfulness/precision/MRR) → **P1-6** (red-team/GAP-S1) → **P1-15** (eval == prod space) → **P2-9** (persistence/trending, landed locally). P2-7 synthetic QA + SME approval is now local-ready.
Each lands as a small loop: implement → `scripts/gate.sh a` + targeted eval → record in `loop-state.md`. Gate/probe-definition changes are **independently human-reviewed** (separation invariant §5).
