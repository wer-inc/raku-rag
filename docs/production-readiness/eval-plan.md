# RAG Evaluation Plan — production target state

**Date:** 2026-06-21 · Companion to root [`poc-evaluation-plan.md`](../../poc-evaluation-plan.md) (PoC stack/provider benchmark) and `tests/benchmarks/poc_stack_benchmark.py`.
Scope: turn the eval subsystem from a **mechanism that always passes** into a **representative, adversarial, persisted** release gate that separates retrieval from generation and actually computes security probes.

> Principle (`docs/loop-engineering.md`): the loop's "No" must be *fast, trustworthy, and un-gameable*. Today the eval "No" is gameable — it reports whatever count the caller injects. Fixing that is **P0-1**.

---

## 1. Current state (audited 2026-06-21)

| Capability | State | Evidence |
|---|---|---|
| Retrieval vs generation metrics separated | ✅ OK | `eval/runner.py:154-166` (recall vs citation/groundedness) |
| Blocking CI eval-gate | ✅ OK | `.github/workflows/ci.yml:49-67`, `eval/baseline.py:54-78` |
| Release-gate criteria | 🟡 self-derived baseline over 2-item fixture | `tests/fixtures/eval/{eval_set,baseline}.json` |
| **Security hard-gates compute real probes** | 🔴 **no-op — caller-supplied counts** | `eval/runner.py:293-298`; prod callers `server.py:524`, `dagster/jobs/evaluation.py:54` never set them |
| Prompt-injection / source-poisoning checks | 🔴 none anywhere | grep empty in `eval/` |
| Adversarial / red-team suite | 🔴 none (incl. GAP-S1) | grep `adversar\|red.?team\|jailbreak` → none in eval |
| Golden corpus (per-industry) | 🔴 2-item smoke fixture | `eval_set.json` |
| Metrics depth | 🟡 `recall_at_k` only (binary hit-rate) | no precision@k / MRR / NDCG / faithfulness |
| Eval space == prod space | 🔴 measured on `HashingEmbeddingProvider` (256-dim), prod = Cohere (1024-dim) | `providers/embeddings.py:17` vs `bedrock_cohere.py` |
| Persistence / trending | 🟡 in-memory dict; `evaluation_runs` table unused | `server.py:507`, `0002_*.sql:273-282` (no writer) |
| SME review workflow | 🔴 none | no reviewer/approval fields on `EvaluationSet` |

---

## 2. Target state

### 2.1 Retrieval eval (debuggable in isolation)
- Metrics: `recall@k`, **`precision@k`**, **`MRR`**, optional `NDCG`, identifier-exact hit-rate (equipment_id/alarm_code/ISIN).
- Per query-type slices: prose lookup, exact-code lookup, spreadsheet-cell citation, high-risk.
- Failure attribution recorded (ties to **P1-8**): `acl_emptied` / `zero_candidates` / `rerank_failed`.

### 2.2 Generation / grounding eval
- Keep citation-accuracy. Replace bag-of-words "groundedness" with an **entailment-based faithfulness** metric (claim ⊆ cited evidence) — LLM-as-judge, with a deterministic fallback for CI.
- Completeness + format/style conformance (once the generative path + HTTP route ship, P1-1/P3-2).
- Uncertainty correctness: insufficient-evidence and high-risk-block must be *correctly* emitted (positive + negative controls).

### 2.3 Security probes (real, in-runner) — **P0-1**
The runner must **compute** these counts from actual probes during a run (not accept them):
- **ACL leakage:** an unauthorized principal's query must return 0 unauthorized docs/citations.
- **Deletion reappearance:** a tombstoned doc re-queried must not appear.
- **Tenant isolation:** a cross-tenant query must return 0.
- **Prompt-injection:** a chunk containing `"ignore previous instructions / reveal …"` must not change the answer or exfiltrate context.
- **Source poisoning:** a poisoned/contradictory chunk must not become primary evidence for a high-risk assertion.
Any non-zero → `gate_result="blocked"`. CI asserts the counts were **actually computed** (non-empty / probe ran), closing the false-assurance hole.

### 2.4 Adversarial / red-team — **P1-6 [!safety]**
- Keyword-free, paraphrased **dangerous-query corpus** asserting `is_high_risk=True` recall (GAP-S1).
- Jailbreak / instruction-override corpus.
- The corpus is *measurement*; the production danger-classification LLM and the gate decision remain **human-owned**.

### 2.5 Corpus, baseline, persistence
- **Golden corpus** per industry (manufacturing first; materialize `tests/fixtures/uat/README.md`), ≥ the 20–50 representative docs R-016 calls for, with held-out QA.
- **Committed golden `baseline.json`** (not `baseline_from_run`) so cross-commit drift is detectable.
- Measure on the **production embedding space** (resolve P1-15) so the gate is representative.
- Persist runs to the `evaluation_runs` table (P2-9) + minimal trend view; later add synthetic QA gen + **SME review/approval** before an item gates CI (P2-7).

---

## 3. Release-gate pass criteria (production)

A build is releasable only if **all** hold (extends `eval/baseline.py:DEFAULT_MIN/MAX_METRICS`):
1. **Security probes all 0** (ACL/deletion/tenant/injection/poisoning), **computed by real probes**.
2. Retrieval: `recall@k` and `precision@k` ≥ committed baseline (no regression).
3. Generation: faithfulness ≥ baseline; insufficient-evidence + high-risk-block controls pass.
4. Safety (manufacturing): GAP-S1 dangerous-query recall ≥ threshold.
5. p95 latency / query-cost ≤ ceilings.
6. Eval ran over the **golden corpus on the prod embedding space**, persisted with the model/prompt/dataset version triple (P2-10).

---

## 4. Sequencing
**P0-1** (real probes + injection/poisoning checks) → **P1-5** (corpus + faithfulness/precision/MRR) → **P1-6** (red-team/GAP-S1) → **P1-15** (eval == prod space) → **P2-7/P2-9** (synthetic QA, SME review, persistence/trending).
Each lands as a small loop: implement → `scripts/gate.sh a` + targeted eval → record in `loop-state.md`. Gate/probe-definition changes are **independently human-reviewed** (separation invariant §5).
