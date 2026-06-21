# RAG Production-Readiness Audit — raku-rag

**Date:** 2026-06-21 · **Branch:** `002-manufacturing-field-knowledge-rag` · **Auditor:** Loop Engineer (multi-agent A–I audit, 10 agents, evidence-grounded)
**Method:** 9 per-dimension auditors (each required to cite `file:line` and verify mechanisms, not test names) + 1 adversarial critic (over-claim hunt + missed-gap cross-check + prioritization).
**Gate state at audit:** Tier A **GREEN**, independently re-run — `313 tests in 0.474s` (`scripts/gate.sh a`). Full suite reported ~607 tests. CI authority = `.github/workflows/gate.yml` (per `MEMORY.md`).

> This document is the SSOT for production-readiness. It **complements** (does not replace) the root `risk-register.md`, `poc-evaluation-plan.md`, and `specs/002-.../tasks.md §Gap Remediation Backlog`. The prioritized backlog below maps every gap to one of the 5 candidate features and a concrete Spec Kit action.

---

## TL;DR — the one finding that frames everything

**There are two systems in this repo and only one of them is deployed.**

- **Python core (`ManufacturingSystem`, in-memory):** rich, mechanism-tested safety/governance/audit logic — high-risk approved-citation gate, draft-only, no-train, hash-chain audit, obsolete/on-site warnings, ACL mapping. This is what the 313 green tests exercise.
- **Deployed path (`apps/answer-service` → `ProductionSystem.answer`):** **001 base controls only** (`apps/answer-service/server.py:1049-1053`). The 002 safety overlay has **no HTTP route** (GAP-F05) and is never invoked for real traffic.

Consequences the audit verified:
1. The high-risk approved-citation block, no-train guard, and mfg hash-chain audit **do not fire in production**.
2. The eval "security hard gates" (ACL/deletion/tenant) are a **no-op that always passes** outside two unit tests → **false assurance** against the project's named top risks. **(the only P0)**
3. The only prompt-injection/jailbreak filter (Bedrock Guardrails adapter) is **dead-wired DI with zero callers** (`apps/api/src/app.module.ts:49`); retrieved chunk text is concatenated into the prompt **undelimited** (`services/answer.py:137`). Safe today *only* because the deployed generator is the deterministic `ExtractiveLLMProvider`, not a real LLM.

The platform is **strong at the core/security-invariant layer and immature at the production boundary** (deployment, durability, telemetry export, eval depth).

---

## Verified strong (OK, evidence-backed — keep)

| Area | Evidence |
|---|---|
| Deny-by-default ACL pre-filter (mechanism pinned) | `core/security/acl.py:32-50`, pre-filter at `providers/vectorstores.py:46`, pinned via `last_prefiltered_count` in `tests/security/test_tenant_isolation.py:56-62` |
| Tenant isolation / no existence disclosure | `core/security/token.py:67-69`, `tests/security/test_acl_leak.py:33-48` |
| Deletion / tombstone (top risk) | `services/deletion.py:60-93`, `tests/security/test_deletion_reappearance.py:36-41` |
| Insufficient-evidence refusal (gate exists) | `services/groundedness.py:24-37`, `tests/integration/test_insufficient_evidence.py:25-31` |
| Human-in-the-loop: AI cannot self-approve (SC-MFG-007) | `manufacturing/drafts/review.py:88-119` (PermissionError) |
| No-train opt-in + block-not-degrade (SC-MFG-009) | `manufacturing/governance/no_train.py:130-194` |
| Redaction across logs/audit/eval/EXIF | `observability/redaction.py:13-79`, `tests/security/test_redaction.py:17-95` |
| Idempotent ingestion + diff-sync + reindex | `services/ingestion.py:103-110`, `services/sync.py:143-203`, `services/reindex.py:156-192` |
| CI as authority (gate + separation invariant) | `.github/workflows/gate.yml`, `scripts/gate.sh` (Tier A/B + §5 separation) |
| Migrations have paired down files + Tier B parity | `infra/db/migrations/postgres/0001..0006` + `.down.sql`, `scripts/postgres-migration-smoke.sh` |

---

## A–I dimension status

Legend: ✅ OK · 🟡 PARTIAL · 🔴 MISSING · ❓ UNKNOWN. "Deployed?" = does the control fire in the `apps/answer-service` → `ProductionSystem` request path.

### A. Product / Domain Fit — mostly OK, deployment-gated
- ✅ Target industry/users/usecases (`spec.md:9,87-193`); ✅ allowed-vs-disallowed scope **(critic: PARTIAL in deployment — enforcement is in `ManufacturingSystem`, not the deployed path)**.
- 🟡 Domain taxonomy strong (`manufacturing/domain/entities.py:67-303`) but **no concrete regulation grounding** (no JIS/ISO/労働安全衛生法 mapping). → **P2-5**
- 🟡 Role/permission search scoping real + hard-gated (`acl_mapping.py:99-183`) but **in-memory only, no API** (GAP-F05). → **P1-1**
- 🟡 Freshness/citation-granularity well-defined; **accuracy residual = GAP-S1** (novel-phrasing danger recall needs a production LLM). → **P1-6**

### B. Knowledge Base / Ingestion — robust core, broken prod edges
- ✅ Idempotent **(critic: concurrent-redelivery race — `persistence/postgres.py:485-532` plain INSERT, raises instead of degrading)** → **P2-3**; ✅ incremental/deletion/reindex; ✅ exclude old/dup/unapproved.
- 🟡 Metadata: mfg taxonomy/approval/owner **in-memory only**; `manufacturing_models.py` declares tables, zero writers. → **P1-3**
- 🟡 PII: redactor **not applied to indexed text bodies** (`services/ingestion.py` no redact call); DataUsePolicy in-memory (GAP-F08). → **P2-8 / P1-3**
- 🟡 DLQ: `workers/queue/sqs.py:68-75` `fail()` **always returns False** → DEAD_LETTER projection never fires in prod; CDK runs worker `--drain` (crash-loop). → **P1-9**

### C. Chunking / Embedding / Indexing — interface-clean, wiring-inconsistent
- ✅ Embedding model selection rationale (`research.md:248-266`, `bedrock_cohere.py:52-98`).
- 🟡 Chunking: prod uses char-based `SentenceChunker(max_chars=400)`, **not** the token-budget chunker; `table_chunks` summarizer has **no prod caller**; **zero overlap** in either. → **P2-2**
- 🟡 **Index supports metadata filtering but retrieval doesn't use it** (`persistence/postgres.py:301-316` vector-only; hot-path indexes unused). → **P1-7**
- 🟡 **Dimension inconsistency:** live app = `HashingEmbeddingProvider` 256-dim, `chunks.embedding`=vector(256), but Cohere=1024-dim & `embeddings` table=vector(1024). A real swap has no path; **all CI/eval quality is measured on the hash embedder** — a different space than prod. → **P1-15**

### D. Retrieval — strong refusal, shallow ranking + blind ops
- ✅ "no relevant doc → refuse" **(critic: PARTIAL — only proven for the no-op extractive generator)**.
- 🟡 No true keyword/lexical (tsvector/BM25) leg, no recency-boost; real Cohere reranker + candidate-union "hybrid" live **only in the un-deployed NestJS facade**; core reranker is a no-op re-sort. → **P1-7**
- 🟡 Quality measured by `recall_at_k` only (binary hit-rate) over 1–2 item fixtures; no precision@k/MRR/NDCG. → **P1-5**
- 🔴 **No retrieval-failure root-cause logging:** only `status='ok'` recorded; rerank failures swallowed (`retrieval.py:86-87`); `last_prefiltered_count` never exported → can't tell "ACL emptied" from "zero matches". → **P1-8**

### E. Generation / Grounding — verified at core, undelivered at edge
- ✅ Citation tied to chunk/document/source (`services/answer.py:204-234`).
- 🟡 Deployed generator = `ExtractiveLLMProvider` (not a real LLM); real `BedrockClaudeService` has **no grounding/anti-fabrication prompt and no caller**. → **P1-2**
- 🟡 Unsupported-claim suppression = bag-of-words overlap, not faithfulness; no entailment check. → **P1-5**
- 🟡 Uncertainty signals (`safety_block_reason`, `obsolete_warning`, on-site `notice`) **not serialized over HTTP** (GAP-M02/F05). → **P1-1**
- 🔴 (missed gap) **Citation→live-chunk integrity** not re-validated at serve time. → **P1-14**

### F. Evaluation — real gate mechanism, hollow content
- ✅ retrieval-vs-generation metrics separated; ✅ blocking CI eval-gate exists; ✅ release-gate criteria defined **(critic: PARTIAL — self-derived baseline over a 2-item fixture)**.
- 🔴 **Eval security hard-gates do not run real probes** — `runner._security_checks` (`runner.py:293-298`) reflects caller-supplied counts; prod callers (`server.py:524`, `dagster/jobs/evaluation.py:54`) never populate them → **always passes**. **No prompt-injection/poisoning checks anywhere.** → **P0-1**
- 🔴 No adversarial/red-team suite (incl. GAP-S1). → **P1-6**
- 🔴 No synthetic QA gen; 🔴 no SME review workflow. → **P2-7**
- 🟡 Eval runs in-memory only; `evaluation_runs` table exists with RLS, **no writer**. → **P2-9**

### G. Security / Governance — strong invariants, dead-wired defenses
- ✅ RBAC/tenant isolation **(critic: PARTIAL — admin/governance mutations have no role gate, `app.py:815`)** → **P2-1**; ✅ PII output suppression (regex); ✅ human-in-the-loop (deployment-gated).
- 🟡 **Prompt-injection defense dead-wired** (Guardrails adapter, no caller); retrieved context undelimited. → **P1-2**
- 🟡 Audit hash-chain **in-memory** + on the non-deployed path (SC-MFG-010 not written for real traffic). → **P1-10**
- 🔴 **No rate-limiting / abuse / WAF** — only a coarse per-tenant cost budget. → **P1-11**
- 🟡 No enforced model/prompt/dataset version registry. → **P2-10**

### H. Observability / Operations — scaffolding present, nothing shipped
- 🟡 Trace covers query/retrieval/generation; **no rerank/citation/eval spans**; tracer is in-memory.
- 🟡 **No production telemetry path:** OTel collector → `debug` only; NestJS `LangfuseExporter` has no prod caller; CloudWatch dashboard shows infra only. → **P1-4**
- 🟡 **Alerts are a static catalog** — no `cloudwatch.Alarm`; tests never fire an expression. → **P1-4**
- 🔴 **No SLO/SLA draft**; 🟡 no standalone incident runbook; 🟡 no model/prompt rollback (reindex is solid). → **P1-4 / P2-4**

### I. CI/CD / Deployment — strong CI, no deploy story
- ✅ unit/integration/security tests in CI; ✅ Docker/secrets-management (CDK KMS + Secrets Manager).
- 🟡 eval-gate is a mechanism check (self-derived baseline). → **P1-5**
- 🟡 **`ci.yml` "Migration runner smoke" applies 0 migrations** (points at `infra/db/migrations`; all `.sql` are in `postgres/` subdir; `runner.discover()` non-recursive) — silent false-positive. → **P1-12**
- 🔴 **No release checklist, no CD pipeline, no Dockerfiles** (CDK images are placeholders); CDK never `synth`/tested in CI. → **P1-12**
- 🟡 **No secret-scanning in CI** (only a bypassable local pre-commit hook). → **P1-13**

---

## Prioritized remediation backlog

Safety-boundary items (always human per `docs/loop-engineering.md §6`) are flagged **[!safety]**. The Spec Kit action for each is the concrete next artifact.

### P0 — false assurance / security blindness (do first)
| ID | Title | Feature | Spec Kit action |
|---|---|---|---|
| **P0-1** | Eval security hard-gates compute **real probes** (ACL/deletion/tenant) inside the runner + add **prompt-injection & source-poisoning** eval checks; wire answer-service + dagster callers; CI asserts counts are non-empty | Eval Harness + Prompt-Injection Defense | Spec `011-eval-security-probes` (spec+plan+impl) |

> **P0-1 status (2026-06-21): largely delivered** (`specs/011-eval-security-probes/`; Loops 2–3 in `loop-state.md`). The runner now COMPUTES the gate signal from real default-on probes — `acl_leakage`, `deleted_reappearance`, `tenant_isolation`, `prompt_injection` (all verified). Caller counts merge by `max` so the protected `test_eval_hard_gate.py` is unchanged; `probes_executed` provenance closes the no-op hole; production callers get real counts automatically. **The 5th probe `source_poisoning` reproduced a real high-risk safety vulnerability (→ PR-016) and is held out of the release-blocking suite pending the human-owned safety fix.** Full suite GREEN (621), Tier A GREEN, separation OK.

### P1 — production readiness (ordered)
| ID | Title | Feature | Notes |
|---|---|---|---|
| P1-1 **[!safety]** | Wire mfg safety/governance overlay onto the deployed answer path (GAP-F05/M02) — NestJS `ManufacturingController` + `/internal/manufacturing`; serialize high-risk block + obsolete warning | Citation Contract + Secure Retrieval | "single biggest production gap" (critic) |
| P1-2 **[!safety-adjacent]** | Invoke prompt-injection defense in the live generate path + delimit untrusted retrieved context + grounding/anti-fabrication system prompt | Prompt-Injection Defense | New spec `009-prompt-injection-defense` |
| P1-3 **[!safety]** | Persist mfg metadata/approval/audit/no-train + DataUsePolicy to Postgres+RLS (GAP-F08); Tier-B survive-restart test | Secure Retrieval + Observability | new migration 0007 |
| P1-4 | Production telemetry: export app spans/metrics + safety-boundary counters; deploy alerts as real `cloudwatch.Alarm` + a test that fires | Observability Runbook | |
| P1-5 | Representative per-industry **golden corpus** + committed baseline; add **precision@k/MRR + faithfulness** metric | Eval Harness | |
| P1-6 **[!safety]** | Adversarial/red-team suite incl. **novel-phrasing dangerous queries for GAP-S1**; gate on is_high_risk recall | Eval Harness + Prompt-Injection Defense | corpus is measurement; danger-LLM + gate decision stay human |
| P1-7 | Implement R13 **hybrid retrieval** (metadata exact + identifier/code match + vector + rerank) + a pgvector query adapter | Secure Retrieval | |
| P1-8 | Retrieval-stage failure/root-cause logging (export `last_prefiltered_count`; reasons: acl_emptied/zero_candidates/rerank_failed) | Observability Runbook | |
| P1-9 | Fix prod DLQ status/audit (`SqsTaskQueue.fail()`) + long-running consumer + scheduled retry sensor | Observability Runbook | |
| P1-10 **[!safety]** | Persist audit hash-chain to Postgres+RLS and write it from the deployed path (SC-MFG-010) | Observability + Secure Retrieval | depends on P1-1/P1-3 |
| P1-11 | Request rate-limiting / abuse protection (per-token/IP) + WAF at the edge | Secure Retrieval | |
| P1-12 | Deployment story: Dockerfiles + `cdk synth/diff` CI job + release checklist/rollback runbook + fix migration smoke | Observability Runbook | |
| P1-13 | Secret-scanning in CI (gitleaks/detect-secrets) | Secure Retrieval | |
| P1-14 | Citation→live-chunk integrity: invalidate citations to tombstoned/ACL-revoked chunks at serve time | Citation Contract | same failure-class as deletion-reappearance |
| P1-15 | Resolve embedding dimension/wiring inconsistency + validate model-version-change quality end-to-end | Eval Harness | |

### P2 / P3
P2-1 role-gate admin mutations **[!safety]** · P2-2 per-doc-type chunking + overlap · P2-3 concurrent-idempotency hardening · P2-4 incident runbook + SLO/SLA + prompt/model rollback · P2-5 regulation taxonomy · P2-6 vector DR runbook + recency-boost · P2-7 synthetic QA + SME review · P2-8 PII NER + pre-index redaction · P2-9 persist+trend eval runs · P2-10 model/prompt/dataset version registry · **P3-1** 0006 enum CHECKs (GAP-M04) **[!safety backstop]** · **P3-2** answer-style/format template.

---

## Mapping to the 5 candidate features (prompt §3)

| Feature | Covered by | First slice |
|---|---|---|
| **1. RAG Evaluation Harness** | P0-1, P1-5, P1-6, P1-15, P2-7, P2-9 | P0-1 |
| **2. Secure Retrieval & Authorization** | P1-1, P1-3, P1-7, P1-11, P1-13, P2-1 | P1-7 / P1-11 |
| **3. Prompt-Injection & Poisoned-Context Defense** | P0-1 (eval side), P1-2, P1-6 | P0-1 then P1-2 |
| **4. Source Citation & Grounded Answer Contract** | P1-1, P1-14, P3-2 | P1-14 |
| **5. RAG Observability & Production Runbook** | P1-4, P1-8, P1-9, P1-10, P1-12, P2-4 | P1-8 |

---

## Recommended first loop

**P0-1** — it is the only P0, it is **non-safety-boundary** (detection/measurement, automatable), it strengthens the loop's own "No" (the eval gate), it serves Features 1 **and** 3, and it is self-contained (no new infra). Strengthening what the gate *means* is itself a gate-design change → **human review of the probe design** per `loop-engineering.md §3/§5`.

See `loop-state.md` for the live loop record and `eval-plan.md` for the eval target state.
