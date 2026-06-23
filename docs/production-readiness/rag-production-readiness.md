# RAG Production-Readiness Audit — raku-rag

**Date:** 2026-06-21 · **Branch:** `002-manufacturing-field-knowledge-rag` · **Auditor:** Loop Engineer (multi-agent A–I audit, 10 agents, evidence-grounded)
**Method:** 9 per-dimension auditors (each required to cite `file:line` and verify mechanisms, not test names) + 1 adversarial critic (over-claim hunt + missed-gap cross-check + prioritization).
**Gate state at audit:** Tier A **GREEN**, independently re-run — `313 tests in 0.474s` (`scripts/gate.sh a`). Full suite reported ~607 tests. CI authority = `.github/workflows/gate.yml` (per `MEMORY.md`).

> This document is the SSOT for production-readiness. It **complements** (does not replace) the root `risk-register.md`, `poc-evaluation-plan.md`, and `specs/002-.../tasks.md §Gap Remediation Backlog`. The prioritized backlog below maps every gap to one of the 5 candidate features and a concrete Spec Kit action.

---

## TL;DR — the one finding that frames everything

**Original audit finding: there were two systems in this repo and only one of them was deployed.**

- **Python core (`ManufacturingSystem`, in-memory):** rich, mechanism-tested safety/governance/audit logic — high-risk approved-citation gate, draft-only, no-train, hash-chain audit, obsolete/on-site warnings, ACL mapping. This is what the 313 green tests exercise.
- **Original deployed path (`apps/answer-service` → `ProductionSystem.answer`):** was **001 base controls only**. Current local state now exposes the manufacturing answer overlay and the broader `/v1/manufacturing/*` contract through NestJS plus answer-service internal routing; real release still needs deployed-environment smoke over AWS/RDS/SQS.

Current local state after the hardening loops:
1. The manufacturing answer overlay, safety fields, data-use/governance/audit endpoints, and the remaining `/v1/manufacturing/*` contract route families now have a NestJS facade and answer-service `/internal/manufacturing/*` routing. → **GAP-F05/GAP-M02 closed locally**
2. Eval security hard gates now compute real default-on probes, including source poisoning and high-risk recall; eval run persistence/trending is wired locally.
3. Prompt-injection defense is invoked in the live answer flow as deterministic defense-in-depth. A future real generative LLM still needs grounding/instruction-hierarchy prompt and Guardrails integration.

The platform is **strong at the core/security-invariant and local release-gate layer**. The remaining
release risk is now concentrated in real-environment deployment/operations: AWS wiring, real
Postgres/pgvector scale evidence, load numbers, rollback/backup drills, and human safety review.

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
| Redaction across logs/audit/eval/EXIF/indexed text/visual metadata | `observability/redaction.py:13-79`, `services/ingestion.py`, `workers/ingestion.py`, `tests/security/test_redaction.py` |
| Idempotent ingestion + diff-sync + reindex | `services/ingestion.py:103-110`, `services/sync.py:143-203`, `services/reindex.py:156-192` |
| CI as authority (gate + separation invariant) | `.github/workflows/gate.yml`, `scripts/gate.sh` (Tier A/B + §5 separation) |
| Migrations have paired down files + Tier B parity | `infra/db/migrations/postgres/0001..0006` + `.down.sql`, `scripts/postgres-migration-smoke.sh` |

---

## A–I dimension status

Legend: ✅ OK · 🟡 PARTIAL · 🔴 MISSING · ❓ UNKNOWN. "Deployed?" = does the control fire in the `apps/answer-service` → `ProductionSystem` request path.

### A. Product / Domain Fit — mostly OK, deployment-gated
- ✅ Target industry/users/usecases (`spec.md:9,87-193`); ✅ allowed-vs-disallowed scope **(critic: PARTIAL in deployment — enforcement is in `ManufacturingSystem`, not the deployed path)**.
- ✅ Domain taxonomy now includes concrete regulation / standard anchors (`manufacturing/domain/regulations.py`) for ISO 9001/45001/12100/13849-1, JIS B 9700 / B 9960-1, and Japanese Industrial Safety and Health references; `ManufacturingDocumentMetadata.regulation_refs` round-trips through metadata. → **P2-5 closed locally**
- ✅ Manufacturing contract route families now have HTTP facade coverage through NestJS and answer-service internal routing; route-level tenant identity comes from the signed principal. → **GAP-F05 closed locally**
- 🟡 Freshness/citation-granularity well-defined; **accuracy residual = GAP-S1** is now release-measured for an expanded synthetic dangerous-query corpus with benign false-positive controls, but truly novel danger phrasing still needs SME review plus a production danger-classification LLM / guardrail. → **P1-6**

### B. Knowledge Base / Ingestion — robust core, broken prod edges
- ✅ Idempotent; Postgres ingestion run creation now uses `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING`, and duplicate redelivery returns the existing run without re-projecting queued state → **P2-3 closed locally**; ✅ incremental/deletion/reindex; ✅ exclude old/dup/unapproved.
- 🟡 Metadata/governance durability is repo-side mitigating: approval state, DataUsePolicy, and audit payload writers exist and route through durable paths locally; remaining closure is real Postgres survive-restart/deployed-env verification. → **P1-3**
- 🟡 PII: shared `Redactor` is now applied before chunking/embedding/index upsert by default, with explicit `pre_index_redact` / `detect_only` / `block` ingestion policy modes, policy-change reindexing, and expanded regex coverage for explicit names, employee IDs, street addresses, postal codes, and SSNs. Visual OCR/caption sensitivity now propagates into region/chunk/crop/asset metadata; sensitive crops default to `visual-region-redaction-required`; and the authorized asset view substitutes public sensitive crop URIs to `memory://redacted-crops/...` instead of returning raw crop URIs. Remaining gap is NER/dictionaries for unstructured names/addresses/industry identifiers and redacted-bitmap materialization in the production image store/OCR pipeline. → **P2-8 / P1-3**
- ✅ SQS worker/DLQ projection and long-lived worker service are wired repo-side. Remaining validation is AWS redelivery/concurrency in the deployed environment. → **P1-9 closed locally**

### C. Chunking / Embedding / Indexing — interface-clean, wiring-inconsistent
- ✅ Embedding model selection rationale (`research.md:248-266`, `bedrock_cohere.py:52-98`).
- ✅ Chunking is now document-type aware: manufacturing ingest passes `ManufacturingDocumentMetadata.document_kind` into `SentenceChunker.chunk_document(...)`, records the selected profile/config on Document/Chunk metadata, and applies overlap for work instructions, inspections, reports, minutes, ledgers, and training docs while preserving the old no-overlap `chunk(text)` behavior for existing callers. → **P2-2 closed locally**
- 🟡 Core retrieval now unions ACL-visible metadata identifier exact matches and lexical keyword matches with vector results before rerank/top-k, including the Postgres adapter over chunk + document JSONB metadata, bounded recency boost, and a live-chunk tsvector GIN index. Remaining gap: prod-scale EXPLAIN/load and real reranker/model routing. → **P1-7**
- 🟡 **Embedding wiring:** live/eval/prod now build embeddings through the same settings-backed provider/dim path and re-index on model/dim change; Cohere/1024 selection fails fast unless schema/reindex is handled. Remaining: real Cohere/1024 migration or explicit hashing/256 production decision, backfill, and refreshed eval baselines. → **P1-15**

### D. Retrieval — strong refusal, hybrid candidate union, prod-scale validation pending
- ✅ "no relevant doc → refuse" **(critic: PARTIAL — only proven for the no-op extractive generator)**.
- 🟡 Metadata/identifier exact-match, lexical keyword overlap, and recency-boost candidate union now live in the core + Postgres path and are metered; Postgres lexical has a tsvector GIN index. Remaining gaps are production-scale EXPLAIN/load and real reranker/model routing. → **P1-7**
- ✅ Quality regression gate now includes precision@k, MRR, deterministic faithfulness, a committed
  golden baseline, and seeded regression tests. Real production embedding-space baseline refresh remains
  after the final embedding provider/backfill decision. → **P1-5 closed locally / P1-15 prod follow-up**
- ✅ Retrieval failure/root-cause logging exports prefilter counts, empty-retrieval outcomes, and rerank failure metrics/spans. → **P1-8 closed locally**

### E. Generation / Grounding — verified at core, real generative model still a release decision
- ✅ Citation tied to chunk/document/source (`services/answer.py:204-234`).
- ✅ Answer display contract now ships on the answer-service HTTP boundary: responses include a versioned `answer_template_version` and stable `display_sections` for status, answer text, safety signals, and evidence/citations. → **P3-2 closed locally**
- 🟡 Deployed generator remains `ExtractiveLLMProvider` in local/default composition. Prompt-injection
  defense is live, and the answer hot path is capped to one generation call; a real generative LLM still
  needs a grounding/instruction-hierarchy prompt, Guardrails integration, and release-bound eval before
  promotion. → **P1-2 closed locally; real-LLM release validation remains**
- ✅ Unsupported-claim regression coverage is now measured by deterministic eval faithfulness over the
  committed golden baseline. LLM-as-judge remains an optional eval/sampling overlay, not a default
  synchronous hot-path call. → **P1-5 / T119 closed locally**
- ✅ Manufacturing uncertainty/safety signals are serialized under the nested `manufacturing` response block over HTTP. → **GAP-M02 closed locally**
- ✅ (closed after audit) **Citation→live-chunk integrity** is re-validated before generation and again before returning citations; tombstoned/ACL-revoked chunks are dropped and can demote the answer to `insufficient_evidence`. → **P1-14**

### F. Evaluation — real gate mechanism, representative local baseline, prod embedding refresh pending
- ✅ retrieval-vs-generation metrics separated; ✅ blocking CI eval-gate exists; ✅ committed golden
  baseline detects precision/MRR/faithfulness regressions.
- ✅ Eval security hard-gates compute real probes in-runner and fail closed when probe execution is missing. → **P0-1 closed locally**
- 🟡 GAP-S1 adversarial recall corpus + default eval probe now gate known dangerous phrasings; broader jailbreak/red-team expansion and SME-reviewed danger corpus remain. → **P1-6**
- ✅ Synthetic QA candidates + SME review workflow are local-ready: generated candidates stay outside release gates until approved, and only approved items can materialize into an `EvaluationSet`. → **P2-7 closed locally**
- ✅ Eval runs persist and trend locally: `EvaluationRunner` accepts an optional repository, answer-service eval wiring writes through it, `evaluation_runs` has additive persistence/version-registry migrations, and in-memory/Postgres repositories share a deterministic row codec. → **P2-9 closed locally**

### G. Security / Governance — strong invariants, dead-wired defenses
- ✅ RBAC/tenant isolation; ✅ admin/governance mutation role gate at the NestJS facade (`admin` / `tenant_admin` / `platform_admin` / `owner`, denied before upstream forwarding) → **P2-1 closed locally**; ✅ PII output suppression (regex); ✅ human-in-the-loop (deployment-gated).
- ✅ Prompt-injection defense is default-on in the live answer flow with query refusal and context neutralization telemetry. Remaining future work is a real generative-LLM grounding prompt/Guardrails integration. → **P1-2 closed locally**
- 🟡 Audit/governance durability is now mostly repo-side mitigated: deployed `ProductionSystem.answer()` writes reference-only audit events to Postgres/RLS; durable manufacturing hash-chain writer and durable DataUsePolicy/no-train store now exist and are wired through the manufacturing product API for policy/status/audit export; approval state writes back through jsonb-safe `Document.metadata`. Remaining gap: real Postgres survive-restart Tier-B coverage and deployed-env verification. → **P1-10 / P1-3**
- 🟡 **Rate-limiting / abuse / WAF:** CDK now defines a WAFv2 WebACL on the public API ALB with AWS managed common protections plus IP and `x-user-token` rate-based rules, and exposes WAF metrics on the operations dashboard. Remaining: deploy to AWS, tune thresholds from real traffic, and add alert/runbook thresholds. → **P1-11**
- ✅ Model/prompt/dataset version registry is now enforced in eval: runs persist `version_registry`, committed baselines can pin it, and the gate fails on mismatch. Remaining prod task: refresh the committed baseline after the real embedding-space migration/backfill decision. → **P2-10 closed locally**

### H. Observability / Operations — repo-side telemetry and runbooks, AWS action wiring pending
- 🟡 Trace/metrics cover query, retrieval, rerank, generation, hot-path tokens/latency, citation
  revalidation drops, and retrieval failure causes locally. Remaining closure is exporting/tuning these
  in the deployed AWS environment.
- 🟡 **Production telemetry path is repo-side mitigating:** RAG metrics/traces can now export sanitized metric/span JSON logs when `RAKU_TELEMETRY_EXPORT_ENABLED=true` (ECS → CloudWatch Logs / OTel sidecar), but real AWS deployment/action wiring and alarm-state smoke remain. NestJS `LangfuseExporter` still has no prod caller. → **P1-4**
- 🟡 **Repo-side CloudWatch alarms now exist:** CDK defines alarms for API 5xx, DLQ visibility, queue age, Aurora CPU, and WAF rate-limit blocks; remaining: deploy to AWS, enable app telemetry export, wire actions/escalation, and run an alarm-state smoke. → **P1-4**
- ✅ SLO/SLA draft, standalone incident runbook, and prompt/model rollback procedure now live in `incident-slo-runbook.md`; remaining prod work is real AWS alarm-action wiring and threshold tuning. → **P1-4 / P2-4 closed locally**

### I. CI/CD / Deployment — strong CI, no deploy story
- ✅ unit/integration/security tests in CI; ✅ Docker/secrets-management (CDK KMS + Secrets Manager).
- ✅ eval-gate has a committed baseline plus default-on security probes; real prod embedding-space
  baseline refresh remains after the embedding/backfill decision. → **P1-5 closed locally / P1-15 prod follow-up**
- ✅ Migration smoke now targets real sqlite migration content and asserts an applied migration; Dockerfiles, CDK synth CI, image scan/SBOM, release/rollback runbook, and CD skeleton exist repo-side. Remaining deployment work is real AWS wiring/dry-runs. → **P1-12 closed locally**
- ✅ Secret-scanning runs in CI with a committed baseline and seeded self-test. → **P1-13 closed locally**

---

## Prioritized remediation backlog

Safety-boundary items (always human per `docs/loop-engineering.md §6`) are flagged **[!safety]**. The Spec Kit action for each is the concrete next artifact.

### P0 — false assurance / security blindness (do first)
| ID | Title | Feature | Spec Kit action |
|---|---|---|---|
| **P0-1** | Eval security hard-gates compute **real probes** (ACL/deletion/tenant) inside the runner + add **prompt-injection & source-poisoning** eval checks; wire answer-service + dagster callers; CI asserts counts are non-empty | Eval Harness + Prompt-Injection Defense | Spec `011-eval-security-probes` (spec+plan+impl) |

> **P0-1 status:** closed locally. The runner computes the gate signal from real default-on probes,
> including source poisoning and high-risk recall; caller counts can only force-block, never downgrade a
> probe-found leak; missing probe execution fails closed.

### P1 — production readiness (ordered)
| ID | Title | Feature | Notes |
|---|---|---|---|
| P1-1 **[!safety]** | Wire mfg safety/governance overlay onto the deployed answer path (GAP-F05/M02) — NestJS `ManufacturingController` + `/internal/manufacturing`; serialize high-risk block + obsolete warning | Citation Contract + Secure Retrieval | **Closed locally**; AWS/RDS deployed smoke remains |
| P1-2 **[!safety-adjacent]** | Invoke prompt-injection defense in the live generate path + delimit untrusted retrieved context + grounding/anti-fabrication system prompt | Prompt-Injection Defense | **Closed locally for deterministic guard**; real generative LLM prompt/Guardrails validation remains |
| P1-3 **[!safety]** | Persist mfg metadata/approval/audit/no-train + DataUsePolicy to Postgres+RLS (GAP-F08); Tier-B survive-restart test | Secure Retrieval + Observability | **Mitigating:** durable DataUsePolicy store exists and product API writes/reads it; approval state writes through `Document.metadata`; real Tier-B survive-restart remains |
| P1-4 | Production telemetry: export app spans/metrics + safety-boundary counters; deploy alerts as real `cloudwatch.Alarm` + a test that fires | Observability Runbook | **Repo-side mitigating**; AWS alarm actions/tuning/firing smoke remain |
| P1-5 | Representative per-industry **golden corpus** + committed baseline; add **precision@k/MRR + faithfulness** metric | Eval Harness | **Closed locally**; production embedding-space baseline refresh remains |
| P1-6 **[!safety]** | Adversarial/red-team suite incl. **novel-phrasing dangerous queries for GAP-S1**; gate on is_high_risk recall | Eval Harness + Prompt-Injection Defense | **Mitigating:** synthetic high-risk recall corpus + release-blocking `high_risk_recall` probe landed; SME expansion + danger-LLM remain human-owned |
| P1-7 | Implement R13 **hybrid retrieval** (metadata exact + identifier/code match + vector + rerank) + a pgvector query adapter | Secure Retrieval | **Repo-side mitigating:** metadata/identifier exact-match + lexical + recency union is in core + Postgres; tsvector index exists; prod-scale validation and real reranker/model routing remain |
| P1-8 | Retrieval-stage failure/root-cause logging (export `last_prefiltered_count`; reasons: acl_emptied/zero_candidates/rerank_failed) | Observability Runbook | **Closed locally** |
| P1-9 | Fix prod DLQ status/audit (`SqsTaskQueue.fail()`) + long-running consumer + scheduled retry sensor | Observability Runbook | **Closed locally**; AWS redelivery/concurrency validation remains |
| P1-10 **[!safety]** | Persist audit hash-chain to Postgres+RLS and write it from the deployed path (SC-MFG-010) | Observability + Secure Retrieval | **Mitigating:** base answer audit persists to `audit_logs`; durable manufacturing hash-chain writer exists; policy changes and approval transitions use the durable/audited path locally; real Tier-B survive-restart coverage remains |
| P1-11 | Request rate-limiting / abuse protection (per-token/IP) + WAF at the edge | Secure Retrieval | **Repo-side mitigating**; AWS deploy/tuning/alerts remain |
| P1-12 | Deployment story: Dockerfiles + `cdk synth/diff` CI job + release checklist/rollback runbook + fix migration smoke | Observability Runbook | **Closed repo-side**; real AWS/OIDC deploy remains |
| P1-13 | Secret-scanning in CI (gitleaks/detect-secrets) | Secure Retrieval | **Closed locally/CI-side** |
| P1-14 | Citation→live-chunk integrity: invalidate tombstoned/ACL-revoked chunks before generation and citation return | Citation Contract | **Closed locally**; pinned by `tests/security/test_citation_revalidation.py` |
| P1-15 | Resolve embedding dimension/wiring inconsistency + validate model-version-change quality end-to-end | Eval Harness | **Mitigating:** settings-backed provider/dim wiring + reindex-on-change + dimension fail-fast landed; real 1024 migration/backfill/baseline remains |

### P2 / P3
~~P2-1 role-gate admin mutations~~ **closed locally; safety role policy remains human-owned** · ~~P2-2 per-doc-type chunking + overlap~~ **closed locally; real-corpus tuning remains prod-owned** · ~~P2-3 concurrent-idempotency hardening~~ **closed locally; real SQS concurrency validation remains AWS-owned** · ~~P2-4 incident runbook + SLO/SLA + prompt/model rollback~~ **closed locally; AWS alarm actions/tuning remain prod-owned** · ~~P2-5 regulation taxonomy~~ **closed locally; SME/legal applicability review remains human-owned** · ~~P2-6 vector DR runbook + recency-boost~~ **closed locally; restore drill remains AWS-owned** · ~~P2-7 synthetic QA + SME review~~ **closed locally; actual SME review remains human-owned** · P2-8 PII NER + production redacted-bitmap materialization (expanded pre-index regex redaction, policy modes, visual redaction-required contract, and redacted crop URI substitution are mitigating) · ~~P2-9 persist+trend eval runs~~ **closed locally; real Postgres retention/trend ops remain prod-owned** · ~~P2-10 model/prompt/dataset version registry~~ **closed locally; prod baseline refresh remains after embedding decision** · ~~P3-1 0006 enum CHECKs (GAP-M04)~~ **closed locally; safety-boundary policy remains human-owned** · ~~P3-2 answer-style/format template~~ **closed locally; UX/content tuning remains product-owned**.

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
