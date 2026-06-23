# Production-Readiness Loop — State Log

Append-only loop record (newest first). One entry per loop iteration. SSOT for "where are we / what's next".
Companion to `rag-production-readiness.md` (audit + backlog) and `eval-plan.md`. Driven per `docs/loop-engineering.md`.

---

## Loop 56 — 2026-06-22 — Local-only cross-industry gap closure (GAP-F13/GAP-F14)

**Implemented:**
- Closed GAP-F13 for the investment/regulated extension runtime:
  - `RegulatedActivityPolicy.prohibited_ai_actions` now blocks explicit prohibited AI actions.
  - `RegulatedActivityPolicy.restricted_ai_actions` forces human review on otherwise factual answers.
  - `ComplianceReviewPolicy.review_states` now governs runtime compliance states via a safe alias map
    (`changes_requested` -> `changes_required`, `compliance_approved` -> `approved`) while preserving
    the existing prerequisite that the business draft must be approved first.
  - `DisclosureEvidencePolicy.required_source_document_types` now governs marketing source selection
    and persisted disclosure-policy validation.
- Closed GAP-F14 repo-side by adding a live Postgres Tier-B test for domain-table RLS over
  `industry_profiles`, `real_estate_properties`, and `investment_funds`, and wiring `gate.sh b` to apply
  0002/0003/0004/0005/0006 before discovering `tests/postgres`.

**Tests added/updated:**
- `tests/industry/test_investment_api.py`
- `tests/industry/test_framework.py`
- `tests/postgres/test_domain_table_rls.py`

**Verification:** investment API/framework tests GREEN (25 tests); domain RLS test is skip-safe without
Postgres/domain migrations (3 skipped locally) and wired into Tier-B; `bash -n scripts/gate.sh`; black +
ruff clean on touched Python files.

**Status:** GAP-F13 and GAP-F14 are closed locally/repo-side. GAP-F14's actual non-skipped execution
requires the Docker/Postgres Tier-B gate.

---

## Loop 55 — 2026-06-22 — Local-only release-gate reconciliation (T117/T118/T119)

**Implemented:**
- Added a regression test proving that enabling extra profile flags (`query_rewrite_enabled` /
  `self_eval_enabled`) does **not** add hidden synchronous LLM calls to the answer hot path.
- Reconciled `specs/001-rag-platform/tasks.md` so T117/T118/T119 reflect the already-landed load
  harness, EXPLAIN gate, and no-default-LLM-judge hot-path behavior.
- Refreshed production-readiness docs that still described old audit findings as current state
  (caller-supplied eval counts, self-derived baseline, no live prompt-injection defense, and the
  stale P1-1 Postgres-data step).

**Tests added/updated:**
- `tests/integration/test_rag_performance_caps.py` now pins one generation call and one
  `llm_call_count` metric even when future profile switches are set.

**Verification:** targeted `tests.integration.test_rag_performance_caps` GREEN (4 tests). Full local
gate is re-run at the end of this loop before handoff.

**Status:** Local performance/release-gate reconciliation is closed. Remaining ownership is still
real-environment work: AWS/OIDC deploy wiring, production-scale Postgres/pgvector EXPLAIN and
p50/p95/p99 load numbers, rollback/backup/vector-restore drills, production embedding backfill +
baseline refresh, production redacted-bitmap materialization, and SME/red-team/human safety review.

---

## Loop 54 — 2026-06-22 — Local-only manufacturing HTTP facade completion (GAP-F05/GAP-M02)

**Implemented:**
- Extended answer-service `/internal/manufacturing/*` routing over existing `ManufacturingSystem` methods for:
  - source sync request/status and ingestion-run status
  - document metadata update and approval transition/import
  - trouble-case search
  - draft create/get/assign/review
  - dashboard, safety telemetry, and KPI
  - existing answer, data-use policy, governance status, and audit export paths
- Extended NestJS `ManufacturingController` with matching `/v1/manufacturing/*` facade routes.
- Kept tenant identity sourced from the signed principal/header path, not from request body overrides.
- Kept business logic in Python manufacturing services; TypeScript remains a thin authenticated facade.
- Reconciled `tasks.md` and readiness docs for GAP-F05/GAP-M02.

**Tests added/updated:**
- `apps/api/test/manufacturing.e2e-spec.ts` now pins representative forwarding for every manufacturing contract route family, auth on answer, signed-principal tenant forwarding, and pre-upstream denial for protected non-admin mutations.

**Verification:** `apps/api` typecheck GREEN; app + manufacturing API e2e 13 OK; answer-service manufacturing endpoint + manufacturing migration contract slice 9 OK; Python `black --check` + `ruff check` clean on touched Python files; `git diff --check` + `detect-secrets` clean; `scripts/gate.sh all` GREEN (**760 OK, skipped 6**).

**Status:** GAP-F05 and GAP-M02 are **closed locally**. Remaining production ownership: deploy these routes to AWS and run the real environment smoke against the actual answer-service/RDS/queue stack.

**Still not locally closable:** production AWS/OIDC wiring, real RDS/pgvector load and EXPLAIN evidence, rollback/backup/vector-restore drills, production embedding migration/backfill plus baseline refresh, production redacted-bitmap materialization, and SME/legal/red-team review of safety and regulation decisions.

---

## Loop 53 — 2026-06-22 — Local-only manufacturing DB enum CHECK backstop (P3-1 / GAP-M04)

**Implemented:**
- Added DB-level enum CHECK constraints to `0006_manufacturing_domain.sql` for:
  - manufacturing document kind
  - approval status and approval source
  - countermeasure type and measure class
  - trouble-case countermeasure relation type
  - draft artifact type, status, and creator
  - safety classification source
  - safety block reason on audit and safety-decision rows
- Kept the existing AI-self-approve DB backstop (`NOT (created_by = 'ai' AND status = 'approved')`) and pinned it explicitly in the migration contract test.
- Reconciled P2-9/P3-1 readiness docs so already-landed local eval persistence and the new enum CHECK backstop are no longer listed as local-open work.

**Tests added/updated:**
- `tests/contract/test_manufacturing_migration_sql.py` now asserts the enum CHECKs and the AI-generated draft approval CHECK.

**Verification:** manufacturing migration contract tests 7 OK; `black --check` + `ruff check` clean for the touched test; `git diff --check` + `detect-secrets` clean; `scripts/gate.sh all` GREEN (**760 OK, skipped 6**).

**Status:** P3-1 is **closed locally**. Remaining ownership: human review of safety enum semantics if the policy vocabulary changes, plus real migration execution in the deployed database.

**Still not locally closable:** production AWS/OIDC wiring, real RDS/pgvector load and EXPLAIN evidence, rollback/backup/vector-restore drills, production embedding migration/backfill plus baseline refresh, production redacted-bitmap materialization, and SME/legal/red-team review of safety and regulation decisions.

---

## Loop 52 — 2026-06-22 — Local-only answer style/format template (P3-2)

**Implemented:**
- Added a versioned answer display contract:
  - `ANSWER_TEMPLATE_VERSION = "grounded-answer-display-v1"`
  - `answer_template_version`
  - `display_sections`
- The answer-service HTTP boundary now includes stable display sections for:
  - status
  - answer text
  - safety/manufacturing signals when present
  - evidence/citations when present
- The NestJS shared DTO and OpenAPI schema now expose the display contract for both standard and manufacturing answer responses.
- Existing answer text/citation semantics are unchanged; the new contract is additive.

**Tests added/updated:**
- `tests/unit/test_answer_format.py` pins deterministic section ordering, citation/evidence sections, and manufacturing safety sections.
- `apps/api/test/app.e2e-spec.ts` pins the OpenAPI schema for `answer_template_version` and `display_sections`.

**Verification:** answer-format unit tests 3 OK; `apps/api` typecheck GREEN; answer/manufacturing API e2e slice 12 OK; `black --check` + `ruff check` clean on touched Python files; `git diff --check` + `detect-secrets` clean; `scripts/gate.sh all` GREEN (**758 OK, skipped 6**).

**Status:** P3-2 is **closed locally**. Remaining product ownership: final customer-facing copy/layout choices and any future style-conformance eval over a real generative model.

**Still not locally closable:** production AWS/OIDC wiring, real RDS/pgvector load and EXPLAIN evidence, rollback/backup/vector-restore drills, production embedding migration/backfill plus baseline refresh, production redacted-bitmap materialization, and SME/legal/red-team review of safety and regulation decisions.

---

## Loop 51 — 2026-06-22 — Local-only vector index DR runbook (P2-6)

**Implemented:**
- Added `docs/production-readiness/vector-dr-runbook.md` covering:
  - vector/lexical/metadata index failure modes.
  - containment, classification, evidence preservation, and recovery path selection.
  - index rebuild + `ANALYZE` + EXPLAIN gate checklist.
  - embedding model/dimension reindex/backfill policy tied to eval `version_registry`.
  - freshness/recency validation after restore/reindex.
  - quarterly restore drill with initial RPO/RTO targets.
- `release-execution-checklist.md` now includes the vector DR scratch-cluster drill.
- `rag-production-readiness.md` now marks P2-6 repo-side closed.

**Verification:** docs-only change; `git diff --check` clean after the update. Full gate remained GREEN after Loop 50 (**755 OK, skipped 6**) before this docs-only addition.

**Status:** P2-6 is **closed locally**. Remaining production ownership: run the actual restore/index rebuild drill against AWS RDS/pgvector and record real restore/reindex timings.

**Still local-only and not yet done:** PR-009 SME/danger-LLM closure, PR-015 production redacted-bitmap materialization, and the real prod embedding migration/backfill decision.

---

## Loop 50 — 2026-06-22 — Local-only document-type chunking profiles + overlap (P2-2)

**Implemented:**
- `SentenceChunker` now supports metadata-aware `chunk_document(...)` while preserving the existing `chunk(text)` behavior.
- Added document-kind profiles with bounded overlap for manufacturing docs:
  - work instructions, inspections, quality/trouble reports, minutes, ledgers, drawings, and training docs.
- `IngestionService.ingest(...)` now accepts optional `chunking_metadata`, selects a chunking profile when supported by the chunker, and records:
  - `chunking_config_version`
  - `chunking_profile`
  - `max_chunk_chars`
  - `chunk_overlap_chars`
  on both `Document.metadata` and `Chunk.metadata`.
- Manufacturing in-memory/file ingest and production `/internal/ingest` pass `ManufacturingDocumentMetadata.to_mapping()` into chunking, so `document_kind` drives the profile before chunks are embedded.
- Updated manufacturing ingestion docs and Spec Kit data-model with the chunking profile contract.

**Tests added/updated:**
- `tests/unit/test_profiled_chunking.py` pins document-kind profile selection, overlap source ranges, existing no-overlap default behavior, ingestion metadata recording, and manufacturing metadata-driven profile selection.

**Verification:** profiled chunking + core quality + ingest + embedding configuration slice 15 OK; local P2-2/P2-5/P2-7 regression slice 22 OK; `black --check` + `ruff check` clean on touched files; `git diff --check` + `detect-secrets` clean; `scripts/gate.sh all` GREEN (**755 OK, skipped 6**).

**Status:** P2-2 is **closed locally**. Remaining production ownership: tune profile sizes/overlap against real customer corpora and rerun production-scale retrieval quality/load tests.

**Still local-only and not yet done:** PR-009 SME/danger-LLM closure, PR-015 production redacted-bitmap materialization, and the real prod embedding migration/backfill decision.

---

## Loop 49 — 2026-06-22 — Local-only synthetic QA with SME approval gate (P2-7)

**Implemented:**
- Added `src/raku_rag/eval/synthetic_qa.py`:
  - deterministic synthetic QA candidate generation from live, non-tombstoned chunks.
  - `SyntheticQAItem` with `generated` / `approved` / `rejected` review status, reviewer id, note, and generator version.
  - `approve_synthetic_qa_item()` / `reject_synthetic_qa_item()` requiring a reviewer id.
  - `materialize_approved_eval_set()` that accepts only SME-approved candidates and refuses an empty approved set.
- Exported the workflow from `raku_rag.eval`.
- Updated `eval-plan.md` and readiness backlog so generated/rejected synthetic QA cannot silently become release-gating eval items.

**Tests added/updated:**
- `tests/unit/test_synthetic_qa_review.py` pins live-chunk-only generation, unreviewed candidate rejection, approved-only materialization, reviewer-id requirement, and review-state round-trip.

**Verification:** synthetic QA + eval regression + golden corpus slice 13 OK; `black --check` + `ruff check` clean on touched eval files.

**Status:** P2-7 is **closed locally**. Remaining production ownership: actual SME/red-team review content, reviewer identity mapping, and ongoing corpus curation.

**Still local-only and not yet done:** PR-009 SME/danger-LLM closure, PR-015 production redacted-bitmap materialization, and the real prod embedding migration/backfill decision. Superseded for doc-type chunking/overlap by Loop 50.

---

## Loop 48 — 2026-06-22 — Local-only manufacturing regulation taxonomy anchors (P2-5)

**Implemented:**
- Added `ManufacturingDocumentMetadata.regulation_refs`, persisted through `to_mapping()` / `from_mapping()` so regulation/standard anchors survive the existing `Document.metadata` / Postgres jsonb path.
- Added `src/raku_rag/manufacturing/domain/regulations.py` with a small explicit catalog for:
  - `ISO_45001_2018`
  - `ISO_12100_2010`
  - `ISO_13849_1_2023`
  - `ISO_9001_2015`
  - `JIS_B_9700_2013`
  - `JIS_B_9960_1_2019`
  - `JP_ISHA`
  - `JP_ISH_RULES`
- Added deterministic `infer_regulation_refs()` to attach likely SME-review anchors from safety/quality/hazard metadata without claiming legal applicability.
- Updated manufacturing ingestion docs and Spec Kit data-model so the design includes regulation/standard anchors.

**Tests added/updated:**
- `tests/manufacturing/unit/test_regulation_taxonomy.py` pins jsonb-safe round-trip, inferred safety/machine/electrical/quality anchors, unknown-ref rejection, and source URL coverage.

**Verification:** regulation taxonomy + Postgres overlay metadata + ingest metadata parse slice 12 OK; `black --check` + `ruff check` clean on touched Python files; `git diff --check` + `detect-secrets` clean; `scripts/gate.sh all` GREEN (**746 OK, skipped 6**).

**Status:** P2-5 is **closed locally**. Remaining production ownership: SME/legal review of tenant-specific applicability, required editions, and any industry/customer-specific regulatory catalog extensions.

**Still local-only and not yet done:** P2-2 doc-type chunking/overlap, PR-009 SME/danger-LLM closure, PR-015 production redacted-bitmap materialization, and the real prod embedding migration/backfill decision. Superseded for synthetic QA + SME review workflow by Loop 49.

---

## Loop 47 — 2026-06-22 — Local-only incident/SLO/model rollback runbook (P2-4)

**Implemented:**
- Added `docs/production-readiness/incident-slo-runbook.md` with:
  - internal SLO/SLA draft thresholds for availability, `/v1/answer` p95/p99, safety probes, eval quality, ingestion freshness, DLQ, error rate, and privacy.
  - error-budget policy and SEV-1/2/3 classification.
  - first-response checklist and playbooks for safety/security breach, latency/capacity breach, retrieval quality regression, and ingestion/indexing backlog.
  - prompt/model rollback order tied to eval `version_registry`, including provider/model config, prompt template, injection guard, embedding model, and VLM/captioning rollback.
- `release-and-rollback.md` now links the SLO/incident/model rollback runbook and adds it to human go/no-go.
- `release-execution-checklist.md` now includes incident/SLO/prompt rollback dry-run review in the real-infra handoff.
- `rag-production-readiness.md` and `risk-register.md` now represent P2-4 as repo-side closed instead of "missing".

**Verification:** docs-only change; `git diff --check` clean. Full gate remained GREEN after Loop 46 (**741 OK, skipped 6**) before this docs-only addition.

**Status:** P2-4 is **closed locally**. Remaining production ownership: wire real AWS alarm actions/escalation, tune thresholds from measured production traffic, and run the operational dry-runs in the deployed environment.

**Still local-only and not yet done:** P2-2 doc-type chunking/overlap, P2-7 synthetic QA + SME review workflow, PR-009 SME/danger-LLM closure, PR-015 production redacted-bitmap materialization, and the real prod embedding migration/backfill decision. Superseded for regulation taxonomy anchors by Loop 48.

---

## Loop 46 — 2026-06-22 — Local-only concurrent ingestion idempotency hardening (P2-3)

**Implemented:**
- `PostgresIngestionRunStore.create_queued()` now uses a single Postgres atomic insert for idempotency:
  - `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING`
  - `RETURNING ingestion_run_id`
- Concurrent duplicate redelivery now returns the existing ingestion run instead of raising a unique-constraint error.
- Duplicate redelivery no longer re-projects the queued processing state; only the first successful insert emits the initial state transition.
- The existing chunk/document upsert idempotency behavior remains unchanged.

**Tests added/updated:**
- `tests/unit/test_postgres_ingestion_idempotency.py` simulates duplicate idempotency-key redelivery and pins:
  - first create returns `(run, True)`
  - duplicate create returns the same existing run with `(run, False)`
  - processing-state projection happens once
  - the SQL contains `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING` and `RETURNING ingestion_run_id`

**Verification:** ingestion idempotency + ingest queue + Tier-B migration SQL slice 12 OK; `black --check` + `ruff check` clean on touched files; `git diff --check` + `detect-secrets` clean; `scripts/gate.sh all` GREEN (**741 OK, skipped 6**).

**Status:** P2-3 is **closed locally**. The Postgres ingestion run write path now degrades safely under concurrent duplicate delivery instead of relying on a race-prone select-then-insert pattern. Remaining production ownership: validate the same path under real SQS redelivery/concurrency in AWS.

**Still local-only and not yet done:** P2-2 doc-type chunking/overlap, P2-5 regulation taxonomy, P2-7 synthetic QA + SME review workflow, PR-009 SME/danger-LLM closure, PR-015 production redacted-bitmap materialization, and the real prod embedding migration/backfill decision. Superseded for the incident/SLO/model rollback runbook by Loop 47.

---

## Loop 45 — 2026-06-22 — Local-only eval model/prompt/dataset version registry (P2-10)

**Implemented:**
- `EvaluationSet` now carries a deterministic `dataset_version` hash derived from the scrubbed eval items and expected evidence, so dataset drift is visible even if an eval set id is reused.
- Added `EvaluationVersionRegistry` and default runner wiring. Every `EvaluationRun` now records:
  - `dataset_version`
  - `embedding_provider`
  - `embedding_model_version`
  - `embedding_dimension`
  - `llm_model_version`
  - `vlm_model_version`
  - `prompt_template_version`
  - `injection_guard_version`
  - `registry_version`
- `EvaluationBaseline` can now include `version_registry`; `evaluate_baseline_gate()` fails when the committed baseline's version keys do not match the run. This turns version provenance into a gate, not only a log field.
- `evaluation_runs` persistence now round-trips `version_registry` through the in-memory and Postgres repositories.
- Added migration `0011_eval_version_registry.sql` (+ down) to persist the registry in the RLS-scoped `evaluation_runs` table.
- The answer-service eval set response exposes `dataset_version`; the NestJS shared DTO/OpenAPI/e2e facade now exposes `version_registry` on eval run status.
- The committed golden baseline now pins the current model/prompt/dataset registry for the golden corpus.

**Tests added/updated:**
- `tests/unit/test_eval_version_registry.py` pins dataset-version drift, run-level model/prompt/dataset provenance, and baseline-gate failure on version mismatch.
- `tests/unit/test_eval_run_repository.py` pins persistence/readback of `version_registry`.
- `tests/integration/test_golden_corpus.py` pins the committed baseline registry and a seeded mismatch failure.
- `tests/integration/test_eval_persistence_endpoint.py` pins API persistence/readback of the registry.
- `tests/contract/test_schema_lock_migration_sql.py` pins the migration and down migration.
- `apps/api/test/eval-feedback.e2e-spec.ts` pins DTO facade passthrough.

**Verification:** eval/version/persistence/golden/schema slice 29 OK; `apps/api` eval/app e2e 10 OK; `apps/api` typecheck + build GREEN; `black --check` + `ruff check` clean on touched Python files; `git diff --check` + `detect-secrets` clean; `scripts/gate.sh all` GREEN (**740 OK, skipped 6**).

**Status:** P2-10 is **closed locally**. Eval runs now persist and gate on a model/prompt/dataset version registry. Remaining production ownership: once the real production embedding choice is finalized (for example Cohere/1024 vs hashing/256), run the real migration/backfill and refresh the committed baseline over that production embedding space.

**Still local-only and not yet done:** P2-2 doc-type chunking/overlap, P2-4 SLO/SLA + incident/model rollback runbook, P2-5 regulation taxonomy, P2-7 synthetic QA + SME review workflow, PR-009 SME/danger-LLM closure, PR-015 production redacted-bitmap materialization, and the real prod embedding migration/backfill decision. Superseded for concurrent idempotency hardening by Loop 46.

---

## Loop 44 — 2026-06-22 — Local-only admin/governance mutation role gate (P2-1)

**Implemented:**
- Added a shared NestJS role gate for admin/governance mutations. Allowed roles are `admin`, `tenant_admin`, `platform_admin`, and `owner`; non-admin callers receive `403 Forbidden`.
- `AdminSettingsController` now gates non-GET admin setting mutations before forwarding to the answer-service.
- `AdminJobsController` now gates retry, reindex, and document-delete mutations before forwarding.
- `ProviderPoliciesController` now gates provider-policy upserts while leaving read/validate routes available.
- `RetrievalProfilesController` now gates retrieval-profile upserts and benchmark-run creation.
- `ManufacturingController` now gates `PUT /v1/manufacturing/policy/data-use` while leaving policy/status/audit reads and `/answer` behavior unchanged.

**Tests added/updated:**
- `apps/api/test/admin-settings.e2e-spec.ts` asserts a `reader` role is denied on ACL/provider/retrieval/benchmark mutations and that no upstream request is made.
- `apps/api/test/admin-jobs.e2e-spec.ts` asserts a `reader` role is denied on retry/reindex/delete and that no upstream request is made.
- `apps/api/test/manufacturing.e2e-spec.ts` asserts a `reader` role is denied on data-use policy mutation before upstream forwarding.

**Verification:** targeted admin/manufacturing e2e slice 23 OK; `apps/api` typecheck + build GREEN; `git diff --check` + `detect-secrets` clean; `scripts/gate.sh all` GREEN (**735 OK, skipped 6**).

**Status:** P2-1 is **closed locally at the API facade**. Admin/governance mutation endpoints now separate read access from mutation authority and fail before touching the core service. Remaining production ownership: map these local roles to the real IdP/Cognito/JWKS claims in the deployed AWS environment and keep safety-boundary role policy human-reviewed.

**Still local-only and not yet done:** SME-expanded high-risk/danger-LLM closure for PR-009, real redacted-bitmap materialization for PR-015, real 1024-dim embedding migration/backfill if choosing Cohere for production, and AWS-deployed role-claim mapping.

---

## Loop 43 — 2026-06-22 — Local-only visual crop URI hardening: no raw sensitive crop URI in asset view (PR-015/P2-8)

**Implemented:**
- `CropService.create_region_crop()` now records both `raw_crop_uri` and, for sensitive/redaction-required regions, a deterministic `redacted_crop_uri` under `memory://redacted-crops/...`.
- `AssetService.get_visual_asset()` now substitutes the public `crop_uri` for sensitive regions/crops with the redacted derivative URI. The raw internal `memory://crops/...` URI is no longer returned in authorized asset JSON when `visual_region_redaction_required=true`.
- Benign crops keep the existing raw `crop_uri` behavior and `redaction_policy_ref=inherit`.

**Tests added/updated:**
- `tests/security/test_redaction.py` now asserts sensitive asset region/crop URIs use `memory://redacted-crops/...` and do not expose raw crop URI prefixes.
- `tests/unit/test_assets_service.py` pins the asset API substitution behavior.
- `tests/unit/test_crop_service.py` pins raw/redacted URI metadata for benign and sensitive crops.

**Verification:** visual redaction/crop/assets/quickstart/visual-answer slice 18 OK; `apps/api` app/assets e2e 10 OK; `black --check` + `ruff check` clean on touched asset/crop/redaction files; `git diff --check` + `detect-secrets` clean; `scripts/gate.sh all` GREEN (**735 OK, skipped 6**).

**Status:** PR-015 remains **Mitigating**. The local visual masking contract is stronger: product consumers no longer receive raw sensitive crop URIs through the asset view. Full closure still needs production image-store integration that materializes the redacted bitmap object and higher-recall NER/dictionaries for unstructured names/addresses/industry identifiers.

**Still local-only and not yet done:** real 1024-dim embedding migration/backfill if choosing Cohere for production. PR-009's remaining closure is partly human/model-owned; PR-015's remaining bitmap materialization requires the production image store/OCR pipeline choice.

---

## Loop 42 — 2026-06-22 — Local-only high-risk recall precision/coverage expansion (PR-009/P1-6)

**Implemented:**
- Expanded `src/raku_rag/eval/fixtures/high_risk_adversarial_corpus.json` from 8 dangerous / 4 benign cases to 12 dangerous / 7 benign cases.
- Added dangerous variants for energized electrical-panel work, chemical spill cleanup, crane/heavy-object handling, and Japanese emergency-stop/guard-bypass/manual-restart phrasing.
- Added benign false-positive controls for pump/operator panel lookup and electrical-cabinet maintenance-calendar queries.
- Tightened `RuleHighRiskClassifier` by removing the bare `panel` keyword from `electric_shock`; the classifier now requires dangerous electrical context such as `energized`, `400v`, `live wire`, `electrical panel`, or similar phrases.

**Tests added/updated:**
- `tests/security/test_high_risk_recall_probe.py` now pins the larger corpus size.
- `tests/manufacturing/unit/test_high_risk_classifier.py` now pins the panel false-positive controls plus the new adversarial danger categories.

**Verification:** high-risk recall + classifier unit slice 23 OK; eval probe / safety gate / source poisoning / visual answer regression slice 25 OK; `black --check` + `ruff check` clean on touched classifier/probe files; `git diff --check` + `detect-secrets` clean; `scripts/gate.sh all` GREEN (**735 OK, skipped 6**).

**Status:** PR-009 remains **Mitigating**. Local synthetic recall/precision coverage is stronger and a reproduced false-positive class (`pump/operator panel`) is closed without weakening energized-panel danger detection. Full closure still requires SME/red-team corpus review and a production danger-classification LLM/guardrail for genuinely novel phrasings.

**Still local-only and not yet done:** real 1024-dim embedding migration/backfill if choosing Cohere for production. PR-009's remaining closure is partly human/model-owned, not fully local-only.

---

## Loop 41 — 2026-06-22 — Local-only visual-region redaction contract (PR-015/P2-8)

**Implemented:**
- `CaptioningResult` now carries `sensitive_detection_labels`, so the visual pipeline preserves detection provenance while still storing redacted caption text.
- `VisualIngestionExecutor` now detects sensitive OCR/caption labels before redaction and annotates each `LayoutRegion` with:
  - `sensitive_detected`
  - `sensitive_detection_labels`
  - `pii_redaction_applied`
  - `secret_redaction_applied`
  - `pii_redaction_policy_ref`
  - `visual_region_redaction_required`
  - `visual_region_redaction_status`
  - `visual_redaction_policy_ref`
- `visual_chunks_from_ingestion()` persists the same redaction contract into visual chunk metadata, so the retrieval/asset path does not lose it.
- `CropService.create_region_crop()` resolves default `inherit` to `visual-region-redaction-required` for sensitive visual regions and carries only labels/policy flags, not raw OCR/caption text.
- `AssetService.get_visual_asset()` now returns redaction-required flags and detection labels for authorized regions/crops without exposing OCR/caption text.
- The NestJS OpenAPI schema documents the optional visual redaction fields on asset regions/crops.

**Tests added/updated:**
- `tests/security/test_redaction.py` now pins sensitive visual OCR/caption redaction plus region/chunk/crop/asset redaction-required propagation.
- `tests/unit/test_crop_service.py` pins benign crops stay `inherit` while sensitive-region crops require `visual-region-redaction-required`.
- `tests/unit/test_assets_service.py` pins authorized asset responses include redaction-required metadata while still omitting OCR/caption text.

**Verification:** `tests.security.test_redaction` + `tests.unit.test_crop_service` + `tests.unit.test_assets_service` + `tests.integration.test_quickstart` 15 OK; visual/OpenAPI/deletion/eval regression slice 19 OK (skipped 1); `apps/api` app/assets e2e 10 OK; `apps/api` typecheck + build GREEN; `black --check` + `ruff check` + `git diff --check` + `detect-secrets` clean; `scripts/gate.sh all` GREEN (**734 OK, skipped 6**).

**Status:** PR-015 remains **Mitigating**. The local visual-region redaction contract is now closed for this repo's current visual abstraction: sensitive OCR/caption labels flow through region/chunk/crop/asset metadata and raw visual crop consumers are told when masking is required. Full closure still needs real bitmap/region masking in the production image store/OCR pipeline and higher-recall NER/dictionaries for unstructured names/addresses/industry identifiers.

**Still local-only and not yet done:** SME-expanded high-risk/danger-LLM closure for PR-009, and real 1024-dim embedding migration/backfill if choosing Cohere for production.

---

## Loop 40 — 2026-06-22 — Local-only approval-state durability: Document.metadata write-through (PR-004/P1-3)

**Implemented:**
- `ManufacturingSystem.get_mfg_meta()` now falls back to the reused 001 `Document.metadata[_mfg_meta]` record when the process-local resolver map is empty.
- `ManufacturingSystem._set_mfg_meta()` writes a jsonb-safe `ManufacturingDocumentMetadata.to_mapping()` back through the reused `DocumentRegistry.put()`.
- Approval transitions now decorate chunks first, then persist the authoritative metadata record, so workflow/imported approval state can survive a production registry round-trip.
- File metadata attach and explicit metadata update now re-apply `_set_mfg_meta()` after enrichment, preserving the same durable write-through behavior.

**Tests added/updated:**
- `tests/manufacturing/test_approval_lifecycle.py` now clears the fast resolver after workflow approval and proves the approved state is restored from `Document.metadata`.

**Verification:** `tests.manufacturing.test_approval_lifecycle` + source-poisoning + manufacturing governance endpoint/wiring slice 11 OK; `black --check` + `ruff check` + `git diff --check` clean; `apps/api` typecheck GREEN; `scripts/gate.sh all` GREEN (**733 OK, skipped 6**).

**Status:** PR-004/P1-3 remains **Mitigating**. The local durable approval-state write-through is now closed via reused 001 `Document.metadata`; remaining to close fully: real Postgres survive-restart Tier-B coverage and a product HTTP approval/metadata facade if we decide that external approval workflow mutation must be exposed through NestJS before release.

**Still local-only and not yet done:** SME-expanded high-risk/danger-LLM closure for PR-009, and real 1024-dim embedding migration/backfill if choosing Cohere for production. Superseded for the visual-region redaction contract by Loop 41.

---

## Loop 39 — 2026-06-22 — Local-only governance production wiring: durable stores on product API (PR-004/P1-3/P1-10)

**Implemented:**
- `ManufacturingSystem` now accepts injected `base_system`, `AuditLogWriter`, and `DataUsePolicyStore` dependencies while preserving the default in-memory composition.
- Added `build_manufacturing_system_for_base()` / `build_production_manufacturing_system()` so the production Postgres base system, `PostgresManufacturingAuditLogWriter`, and `PostgresDataUsePolicyStore` share the same tenant-scoped connection.
- Extended the manufacturing `AuditLogWriter` interface to include the read/tenant/export surface already used by dashboard/KPI/audit export.
- `apps/answer-service` now exposes durable manufacturing governance routes:
  - `GET /internal/manufacturing/policy/data-use`
  - `PUT /internal/manufacturing/policy/data-use`
  - `GET /internal/manufacturing/governance/status`
  - `GET /internal/manufacturing/audit/export`
- `apps/api` now exposes the thin product facade under `/v1/manufacturing/...`, forwarding the signed principal to the answer-service and stripping body-supplied `tenant_id` from policy patches.

**Tests added/updated:**
- `tests/manufacturing/unit/test_durable_manufacturing_wiring.py` pins injected Postgres store/writer composition, policy-change persistence, durable audit readback, and hash-chain verification across recreated adapters.
- `tests/integration/test_manufacturing_governance_endpoint.py` pins the answer-service boundary: policy read/update, governance status, and audit export over the durable stores.
- `apps/api/test/manufacturing.e2e-spec.ts` now covers policy read/update, governance status, audit export, and tenant-override stripping in the NestJS facade.

**Verification:** `tests.integration.test_manufacturing_governance_endpoint` + durable governance/store/writer/governance/no-train slice 28 OK; `tests.contract.test_openapi` 8 OK (skipped 1); `apps/api` manufacturing+app e2e 11 OK; `apps/api` typecheck + build GREEN; `black --check` + `ruff check` + `git diff --check` clean; `scripts/gate.sh all` GREEN (**732 OK, skipped 6**).

**Status:** PR-004/P1-3/P1-10 remains **Mitigating** but the prior local-only production-wiring gap is closed: policy changes now flow through the product API into the durable DataUsePolicy store and durable manufacturing audit writer. Durable approval-state write-through was superseded by Loop 40. Remaining to close fully: real Postgres survive-restart Tier-B coverage and real AWS deploy verification.

**Still local-only and not yet done:** SME-expanded high-risk/danger-LLM closure for PR-009, visual-region redaction beyond text/EXIF/caption redaction, and real 1024-dim embedding migration/backfill if choosing Cohere for production. Superseded for durable approval-state write-through by Loop 40.

---

## Loop 38 — 2026-06-22 — Local-only governance durability: Postgres DataUsePolicy store (PR-004/P1-3)

**Implemented:**
- Added migration `0010_mfg_data_use_policy.sql` (+ down) for `manufacturing_data_use_policies`.
- The table stores the no-train/default opt-in posture, provider no-train requirement, fallback mode, retention settings, export flag, version, and updater fields under tenant RLS.
- Added `PostgresDataUsePolicyStore` with the same safety posture as `InMemoryDataUsePolicyStore`:
  - `get(tenant_id)` auto-seeds the safe default.
  - `update(tenant_id, patch, actor)` validates patchable fields, bumps `policy_version`, records `updated_by`, and rejects `training_opt_in=True` without `opt_in_contract_ref`.

**Tests added/updated:**
- `tests/manufacturing/unit/test_postgres_data_use_policy_store.py` pins safe default seeding, tenant-scoped update, version bump, invalid opt-in rejection without persistence, and valid opt-in.
- `tests/contract/test_schema_lock_migration_sql.py` pins the durable policy table and tenant-isolation policy.

**Verification:** `tests.manufacturing.unit.test_postgres_data_use_policy_store` + existing governance/no-train tests + schema-lock contract 30 OK; `black --check` + `ruff check` clean on touched governance persistence files; `scripts/gate.sh all` GREEN (**730 OK, skipped 6**).

**Status:** PR-004/P1-3 remains **Mitigating**. Durable DataUsePolicy/no-train storage now exists locally; prior production wiring and durable policy-change audit gaps were superseded by Loop 39, and durable approval-state write-through by Loop 40. Remaining to close fully: real Postgres survive-restart coverage and final deployed-env verification.

**Still local-only and not yet done:** SME-expanded high-risk/danger-LLM closure for PR-009, visual-region redaction beyond text/EXIF/caption redaction, and real 1024-dim embedding migration/backfill if choosing Cohere for production. Superseded for durable governance production wiring by Loop 39 and approval-state write-through by Loop 40.

---

## Loop 37 — 2026-06-22 — Local-only manufacturing audit durability: Postgres hash-chain writer (PR-004/P1-10)

**Implemented:**
- `sanitize_audit_log_entry()` is now a shared manufacturing audit sanitizer; `InMemoryAuditLogWriter` reuses it.
- Added `PostgresManufacturingAuditLogWriter` with the same core surface as the in-memory writer:
  - `record(entry)`.
  - `read_all(principal)`.
  - `read_for_tenant(principal, tenant_id)`.
  - `verify_chain(principal)`.
- The writer redacts free-text fields, preserves reference IDs, links entries with `prev_hash`/`entry_hash`, and reads through tenant-scoped RLS context.
- Added migration `0009_mfg_audit_payload.sql` (+ down) to persist the canonical redacted `AuditLogEntry` payload in `manufacturing_audit_events.entry_payload`, while keeping existing dashboard summary columns.

**Tests added/updated:**
- `tests/manufacturing/unit/test_postgres_audit_writer.py` pins redacted write/readback, tenant scoping, hash-chain verification, and tamper detection.
- `tests/contract/test_schema_lock_migration_sql.py` pins the additive payload column.

**Verification:** `tests.manufacturing.unit.test_postgres_audit_writer` + existing manufacturing audit writer/redaction units + schema-lock contract 27 OK; `black --check` + `ruff check` clean on touched manufacturing audit/Postgres persistence files; `scripts/gate.sh all` GREEN (**726 OK, skipped 6**).

**Status:** PR-004/P1-10 remains **Mitigating**. The durable Postgres writer now exists and preserves the same hash-chain semantics; production wiring, durable DataUsePolicy/no-train state, durable policy-change audit, and approval-state write-through were superseded by Loops 38–40. Remaining to close fully: survive-restart Tier-B coverage over real Postgres.

**Still local-only and not yet done:** SME-expanded high-risk/danger-LLM closure for PR-009, visual-region redaction beyond text/EXIF/caption redaction, and real 1024-dim embedding migration/backfill if choosing Cohere for production. Superseded for the durable DataUsePolicy store slice by Loop 38, production wiring by Loop 39, and approval-state write-through by Loop 40.

---

## Loop 36 — 2026-06-22 — Local-only PII recall tail: address/name/employee-id regex expansion (PR-015/P2-8)

**Implemented:**
- `Redactor` now detects and masks additional common PII/secret-adjacent patterns:
  - explicit `Name:` / `Contact Name:` and Japanese `氏名:` / `名前:` fields.
  - `Employee ID` / `Staff ID` / `Worker ID` / `Operator ID` fields.
  - common street-address forms.
  - Japanese postal codes and US SSNs.
- The existing pre-index redaction path automatically applies these patterns before chunking/embedding/upsert.

**Tests added/updated:**
- `tests/unit/test_core_quality.py` pins the expanded redaction labels.
- `tests/security/test_redaction.py` pins that name, employee ID, street address, and postal code patterns do not survive indexed text.

**Verification:** `tests.unit.test_core_quality` + `tests.security.test_redaction` 13 OK; `black --check` + `ruff check` clean on touched redaction/test files; `scripts/gate.sh all` GREEN (**723 OK, skipped 6**).

**Status:** PR-015 remains **Mitigating**. Regex recall is stronger for common address/name/employee-id forms; full closure still needs NER/dictionaries for unstructured names/addresses and visual region-level masking for image PII.

**Still local-only and not yet done:** manufacturing governance/hash-chain durability tail (PR-004/P1-3/P1-10), SME-expanded high-risk/danger-LLM closure for PR-009, visual-region redaction beyond text/EXIF/caption redaction, and real 1024-dim embedding migration/backfill if choosing Cohere for production. Superseded for the durable manufacturing audit writer slice by Loop 37.

---

## Loop 35 — 2026-06-22 — Local-only retrieval index tail: Postgres tsvector lexical index (PR-007/P1-7)

**Implemented:**
- Added `infra/db/migrations/postgres/0008_lexical_retrieval_index.sql` and paired down migration.
- The migration creates `idx_chunks_text_lexical_live`, a partial GIN index over `to_tsvector('simple', text)` for live chunks.
- `PostgresVectorStore.lexical_matches()` now narrows candidates with `to_tsvector('simple', c.text) @@ to_tsquery('simple', $query)` instead of unindexed `LIKE`, while keeping final scoring in the shared Python lexical/recency scorer.

**Tests added/updated:**
- `tests/contract/test_explain_gate.py` pins the tsvector query shape and lexical index.
- `tests/contract/test_schema_lock_migration_sql.py` pins the migration/index declaration.

**Verification:** `tests.contract.test_explain_gate` + `tests.contract.test_schema_lock_migration_sql` + `tests.integration.test_hybrid_retrieval` 17 OK; `black --check` + `ruff check` clean on touched Postgres/contract files; `scripts/gate.sh all` GREEN (**722 OK, skipped 6**).

**Status:** PR-007 remains **Mitigating**; repo-side retrieval now has metadata exact + lexical + recency + vector union, and the deployed lexical leg has an index path. Remaining to close fully: real-data EXPLAIN proving index use, load p50/p95/p99, and real reranker/model routing.

**Still local-only and not yet done:** manufacturing governance/hash-chain durability tail (PR-004/P1-3/P1-10), SME-expanded high-risk/danger-LLM closure for PR-009, higher-recall PII/visual-region redaction beyond regex policy controls, and real 1024-dim embedding migration/backfill if choosing Cohere for production. Superseded for the address/name/employee-id regex expansion by Loop 36.

---

## Loop 34 — 2026-06-22 — Local-only embedding wiring reconciliation (PR-008/P1-15)

**Implemented:**
- `src/raku_rag/providers/embeddings.py` now exposes embedding capability metadata, `embedding_dimension()`, and `embedding_provider_from_settings()`.
- `Settings` now carries `embedding_provider`, `embedding_dim`, and `aws_region`; env wiring adds `RAKU_EMBEDDING_PROVIDER` and `RAKU_EMBEDDING_DIM`.
- `MvpSystem` and `ProductionSystem` both build their embedding provider from the same settings path, so eval/local/prod no longer silently choose separate provider wiring.
- The Cohere/Bedrock provider name is recognized but fail-fast unless `embedding_dim=1024`, making the schema/reindex requirement explicit before a model swap.
- `IngestionService` now stores `embedding_model_version` and `embedding_dimension` in document/chunk metadata and includes both in the skip predicate. Same raw content is re-indexed when model version or dimension changes.
- `PostgresVectorStore` validates vector length before SQL insert, producing a clear dimension mismatch error instead of an opaque pgvector failure.
- `.env.example` documents the provider/dimension knobs and the need to align them with schema + reindex.

**Tests added/updated:**
- `tests/unit/test_embedding_configuration.py` pins provider factory behavior, Cohere 1024-dim fail-fast, env parsing, reindex-on-dimension-change, and Postgres vector length validation.

**Verification:** `tests.unit.test_embedding_configuration` + `tests.security.test_redaction` + `tests.integration.test_ingest_queue` 17 OK; `black --check` + `ruff check` clean on touched embedding/config/app/production/ingestion/Postgres files; `scripts/gate.sh all` GREEN (**722 OK, skipped 6**).

**Status:** PR-008/P1-15 moves from **Open** to **Mitigating**. Repo-side provider/dim wiring is now explicit and stale vectors are reindexed on model/dim changes. Remaining to close fully: actual Cohere/1024 pgvector migration or parallel embedding table path, real reindex/backfill execution, and eval/golden baseline over the selected production embedding provider.

**Still local-only and not yet done:** manufacturing governance/hash-chain durability tail (PR-004/P1-3/P1-10), SME-expanded high-risk/danger-LLM closure for PR-009, higher-recall PII/visual-region redaction beyond regex policy controls, optional Postgres tsvector/BM25 tuning, and real 1024-dim embedding migration/backfill if choosing Cohere for production. Superseded for the Postgres tsvector lexical-index slice by Loop 35.

---

## Loop 33 — 2026-06-22 — Local-only retrieval tail: lexical + recency hybrid leg (PR-007/P1-7)

**Implemented:**
- `src/raku_rag/core/hybrid_retrieval.py` now includes bounded lexical scoring and recency boost helpers. Lexical scores remain below metadata exact-match scores, so explicit business identifiers still win.
- `InMemoryVectorStore.lexical_matches()` returns ACL-visible chunks with direct content-term overlap.
- `PostgresVectorStore.lexical_matches()` adds the deployed lexical leg over live chunks joined to document metadata, using SQL only to narrow candidates and shared Python scoring for behavior parity.
- `RetrievalService` unions metadata exact matches, lexical matches, and vector matches before rerank/top-k; it exports `retrieval_lexical_match_count` and span attribute `lexical_match_count`.

**Tests added/updated:**
- `tests/integration/test_hybrid_retrieval.py` now pins a keyword query where lexical matching beats vector-only order, and a same-keyword tie where newer `effective_date` metadata wins.
- `tests/contract/test_explain_gate.py` statically pins the deployed Postgres lexical/recency leg.

**Verification:** `tests.integration.test_hybrid_retrieval` + `tests.contract.test_explain_gate` 10 OK; `black --check` + `ruff check` clean on touched retrieval/vectorstore/Postgres/hybrid files; `scripts/gate.sh all` GREEN (**717 OK, skipped 6**).

**Status:** PR-007 remains **Mitigating** but its repo-side core path is now much stronger: metadata exact identifiers + lexical keyword overlap + recency boost are all in the core and Postgres path. Remaining to close fully: production-scale EXPLAIN/load validation, optional tsvector/BM25 index tuning, and real reranker/model routing.

**Still local-only and not yet done:** manufacturing governance/hash-chain durability tail (PR-004/P1-3/P1-10), embedding dimension/model wiring reconciliation (PR-008/P1-15), SME-expanded high-risk/danger-LLM closure for PR-009, higher-recall PII/visual-region redaction beyond regex policy controls, and optional Postgres tsvector/BM25 tuning if we want stronger lexical index guarantees before real-data EXPLAIN. Superseded for the provider/dim wiring slice by Loop 34.

---

## Loop 32 — 2026-06-22 — Local-only PII policy tail: selectable pre-index redaction modes (PR-015/P2-8)

**Implemented:**
- `IngestionService` now supports explicit PII/secret handling modes:
  - `pre_index_redact` (default): current safe behavior; redact before chunking/embedding/upsert.
  - `detect_only`: retain indexed text only when explicitly configured, while tagging detected sensitive classes.
  - `block`: fail ingestion when sensitive content is detected.
- Redaction policy is now part of diff-sync: the same raw document is re-indexed when `pii_redaction_mode` changes, avoiding stale raw/redacted chunks after a policy change.
- Document and chunk metadata now record `sensitive_detected`, `sensitive_detection_labels`, `pii_redaction_applied`, `secret_redaction_applied`, `pii_redaction_mode`, and `pii_redaction_policy_ref`.
- `Settings.pii_redaction_mode` + `RAKU_PII_REDACTION_MODE` wire the policy into both `MvpSystem` and `ProductionSystem`.
- `.env.example` documents the allowed values.

**Tests added/updated:**
- `tests/security/test_redaction.py` now pins default pre-index redaction metadata, explicit `detect_only` retain/tag behavior, explicit `block` behavior, policy-change reindexing for unchanged raw content, and env parsing.

**Verification:** `tests.security.test_redaction` 8 OK; `black --check` + `ruff check` clean on touched ingestion/config/app/production/redaction-test files; `scripts/gate.sh all` GREEN (**714 OK, skipped 6**).

**Status:** PR-015 remains **Mitigating**. Repo-side policy-selectable pre-index behavior is now implemented; full closure still needs higher-recall PII detection for names/addresses/industry identifiers (NER/dictionaries) and, for visual PII, region-level masking beyond text/EXIF/caption redaction.

**Still local-only and not yet done:** manufacturing governance/hash-chain durability tail (PR-004/P1-3/P1-10), embedding dimension/model wiring reconciliation (PR-008/P1-15), true lexical/recency tail of P1-7, SME-expanded high-risk/danger-LLM closure for PR-009, and higher-recall PII/visual-region redaction beyond regex policy controls. Superseded for the core lexical/recency retrieval slice by Loop 33.

---

## Loop 31 — 2026-06-22 — Local-only audit durability: deployed answer audit to Postgres (PR-004/P1-10 slice)

**Implemented:**
- `src/raku_rag/observability/audit.py` now exposes an `AuditSink` protocol and shared `sanitize_audit_event()` redaction path. The in-memory sink reuses the same sanitizer, including nested metadata redaction.
- `src/raku_rag/persistence/postgres.py` adds `PostgresAuditSink`, writing reference-only answer audit events into the existing RLS-protected `audit_logs` table. It persists tenant/correlation/actor/action/decision/reason/document IDs/chunk IDs/citation IDs/policy metadata without raw prompt, answer, or retrieved context.
- `ProductionSystem` now wires `PostgresAuditSink` instead of `InMemoryAuditSink`, so deployed `ProductionSystem.answer()` audit events survive process restarts and participate in tenant RLS.
- `AnswerService` depends on the `AuditSink` protocol rather than the in-memory implementation.

**Tests added/updated:**
- `tests/unit/test_audit_sink.py` pins nested redaction, Postgres sink insert/readback behavior, tenant-scoped reads, and the requirement that Postgres reads specify a tenant.

**Verification:** `tests.unit.test_audit_sink` + `tests.integration.test_answer_observability` + `tests.postgres.test_production_smoke` 7 OK; `black --check` + `ruff check` clean on touched audit/Postgres/service files; `scripts/gate.sh all` GREEN (**710 OK, skipped 6**).

**Status:** PR-004/P1-10 moves from **Open** to **Mitigating** for the deployed base answer path. Remaining to close fully: manufacturing hash-chain durability, no-train/DataUsePolicy persistence, approval-state governance tables/writers, and a Tier-B survive-restart test for those manufacturing governance controls.

**Still local-only and not yet done:** manufacturing governance/hash-chain durability tail (PR-004/P1-3/P1-10), embedding dimension/model wiring reconciliation (PR-008/P1-15), deeper PII detection/policy (PR-015 tail), true lexical/recency tail of P1-7, and SME-expanded high-risk/danger-LLM closure for PR-009. Residual `multer>=2.2.0` closure appears blocked on upstream/override behavior rather than a straightforward repo-only patch. Superseded for the PII policy-selectable redaction slice by Loop 32.

---

## Loop 30 — 2026-06-22 — Local-only observability tail: sanitized app telemetry export (PR-005/P1-4)

**Implemented:**
- `src/raku_rag/observability/exporters.py` — optional `TelemetryExporter` seam with:
  - `InMemoryTelemetryExporter` for tests.
  - `StructuredLogTelemetryExporter` for sanitized JSON log export (ECS stdout → CloudWatch Logs / OTel sidecar).
  - identity-label hashing and recursive redaction before export.
- `MetricsRecorder` exports metric points when an exporter is attached; `InMemoryTracer` exports finished spans on context exit. Export failures are swallowed so telemetry cannot break retrieval/generation.
- `Settings.telemetry_export_enabled` + `RAKU_TELEMETRY_EXPORT_ENABLED`; `MvpSystem` and `ProductionSystem` wire the structured exporter only when enabled.
- `.env.example` documents the opt-in.

**Tests added/updated:**
- `tests/unit/test_observability_metrics.py` now pins sanitized metric export, sanitized span export, non-propagating exporter failures, and env-driven structured exporter creation.

**Verification:** observability unit + answer/trace/retrieval regression slice 13 OK; `black --check` + `ruff check` clean on touched observability/config files; `scripts/gate.sh all` GREEN (**707 OK, skipped 6**).

**Status:** PR-005 remains **Mitigating**. Repo-side app telemetry export path and CloudWatch alarms now exist; full closure needs AWS deployment with the env enabled, alarm actions/escalation topics, and a deployed alarm-state/firing smoke.

**Still local-only and not yet done:** governance/audit durability (PR-004/P1-3/P1-10), embedding dimension/model wiring reconciliation (PR-008/P1-15), deeper PII detection/policy (PR-015 tail), true lexical/recency tail of P1-7, and SME-expanded high-risk/danger-LLM closure for PR-009. Residual `multer>=2.2.0` closure appears blocked on upstream/override behavior rather than a straightforward repo-only patch. Superseded for the deployed base answer audit slice by Loop 31.

---

## Loop 29 — 2026-06-22 — Local-only safety eval: high-risk recall adversarial corpus (PR-009/P1-6)

**Implemented:**
- `src/raku_rag/eval/fixtures/high_risk_adversarial_corpus.json` — synthetic manufacturing red-team corpus (8 dangerous + 4 benign controls, no real customer data) for GAP-S1 high-risk recall.
- `src/raku_rag/eval/high_risk_recall.py` — deterministic corpus loader/evaluator that records missed dangerous queries, wrong expected reason families, and benign false positives.
- `high_risk_recall_probe` added to `DEFAULT_PROBES` and `SECURITY_CHECKS`, so release eval blocks if known-dangerous manufacturing queries are not classified high-risk or if a degenerate all-high-risk classifier overfires on benign controls.

**Tests added/updated:**
- `tests/security/test_high_risk_recall_probe.py` — corpus positive/negative controls; real classifier passes; false-negative classifier blocks; all-high-risk classifier blocks; default `EvaluationRunner` includes `high_risk_recall`.
- Existing default-probe coverage still asserts every `SECURITY_CHECK` has a real probe and default suite runs clean.

**Verification:** `tests.security.test_high_risk_recall_probe` + default probe coverage + eval probe suite 21 OK; `black --check` + `ruff check` clean on touched eval files; `scripts/gate.sh all` GREEN (**703 OK, skipped 6**).

**Status:** PR-009 moves from **Open/PARTIAL** to **Mitigating**. Remaining to close fully: SME/red-team corpus expansion and a production danger-classification LLM/guardrail for genuinely novel phrasings (human-owned safety boundary).

**At that point still local-only and not yet done:** governance/audit durability (PR-004/P1-3/P1-10), app-level telemetry export beyond CDK alarms (PR-005 tail), embedding dimension/model wiring reconciliation (PR-008/P1-15), deeper PII detection/policy (PR-015 tail), true lexical/recency tail of P1-7, and SME-expanded high-risk/danger-LLM closure for PR-009. Residual `multer>=2.2.0` closure appears blocked on upstream/override behavior rather than a straightforward repo-only patch. Superseded for the PR-005 telemetry-export tail by Loop 30.

---

## Loop 28 — 2026-06-22 — Local-only retrieval hardening: core metadata identifier exact-match leg (PR-007/P1-7)

**Implemented:**
- `src/raku_rag/core/hybrid_retrieval.py` adds shared identifier extraction/matching for hot business identifiers (`equipment_id`, `alarm_code`, `property_id`, `contract_id`, `fund_id`, `isin`, etc.) with nested metadata support (`_mfg_meta`, `manufacturing_metadata`, `manufacturing`, `industry_metadata`).
- `RetrievalService` now unions ACL-visible metadata exact matches with vector results before rerank/top-k, de-duplicates by chunk, re-runs the existing ACL post-check, and emits `retrieval_metadata_exact_match_count` in metrics + span attributes.
- `InMemoryVectorStore.metadata_exact_matches()` supports the Tier-A/local path and nested manufacturing metadata dataclasses/mappings on chunk metadata.
- `PostgresVectorStore.metadata_exact_matches()` supports the deployed path by querying joined `chunks` + `documents` JSONB metadata; this covers production-ingested manufacturing metadata persisted on `Document.metadata`, not only chunk metadata.

**Tests added/updated:**
- `tests/integration/test_hybrid_retrieval.py` — an exact `EQ-PRESS-100` / `E-142` metadata match beats a stronger vector-only distractor; an ACL-hidden exact match is excluded.
- `tests/contract/test_explain_gate.py` — statically pins that the core/Postgres identifier leg exists alongside the vector EXPLAIN gate shape.

**Verification:** `tests.integration.test_hybrid_retrieval` + `tests.contract.test_explain_gate` 7 OK; retrieval/citation/redaction regression slice 18 OK; `black --check` + `ruff check` clean on touched Python; `scripts/gate.sh all` GREEN (**697 OK, skipped 6**).

**Status:** PR-007 moves from **Open** to **Mitigating**. Remaining to close fully: true lexical/BM25 or tsvector leg, recency boost, real reranker/model routing, and prod-scale EXPLAIN/load validation.

**At that point still local-only and not yet done:** governance/audit durability (PR-004/P1-3/P1-10), app-level telemetry export beyond CDK alarms (PR-005 tail), high-risk recall/adversarial corpus (PR-009/P1-6), embedding dimension/model wiring reconciliation (PR-008/P1-15), deeper PII detection/policy (PR-015 tail), and the true lexical/recency tail of P1-7. Residual `multer>=2.2.0` closure appears blocked on upstream/override behavior rather than a straightforward repo-only patch. Superseded for the initial PR-009 corpus by Loop 29.

---

## Loop 27 — 2026-06-22 — Local-only observability: repo-side CloudWatch alarms (PR-005/P1-4)

**Implemented:**
- `infra/cdk/lib/raku-rag-stack.ts` now creates real `cloudwatch.Alarm` resources for:
  - `ApiTarget5xxAlarm` — API target 5xx over 5 minutes.
  - `IngestionDlqVisibleAlarm` — any DLQ-visible message.
  - `IngestionQueueAgeAlarm` — stale SQS ingestion age.
  - `AuroraCpuAlarm` — Aurora pgvector CPU pressure.
  - `ApiWafRateLimitBlockedAlarm` — WAF IP/token rate-limit blocks.
- Dashboard metric objects are reused by the alarms where possible, with `TreatMissingData.NOT_BREACHING`.
- `CloudWatchAlarmNames` output added for release automation / post-deploy smoke checks.
- `tests/contract/test_cdk_infrastructure.py` and `infra/cdk/README.md` now pin CloudWatch alarms.

**Verification:** `tests.contract.test_cdk_infrastructure` 5 OK; `cd infra/cdk && npm run build` GREEN; `cd infra/cdk && npm run synth` GREEN and emits `AWS::CloudWatch::Alarm` resources for all five alarms.

**Status:** PR-005 moves from **Open** to **Mitigating**. Remaining to close fully: export app-level RAG metrics/spans out of ECS (currently in-memory), wire alarm actions/escalation topics in the real AWS account, and run a deployed alarm-state/firing smoke.

---

## Loop 26 — 2026-06-22 — Local-only supply-chain follow-up: NestJS 11 + Trivy allowlist narrowing (PR-014)

**実装した変更:**
- `apps/api/package.json` / `package-lock.json` — API workspace upgraded from NestJS 10.4.x to NestJS 11.1.x (`@nestjs/common/core/platform-express/testing`) and Nest CLI 11.0.x.
- `apps/api/src/main.ts` — typed the CORS origin callback explicitly for the NestJS 11 / stricter TS surface.
- `.trivyignore` — removed stale picomatch acceptance; after NestJS 11, API dev tooling uses picomatch 4.0.4 and prod-only dependency resolution has no picomatch (`npm ls --omit=dev picomatch` empty).
- `risk-register.md`, `release-execution-checklist.md`, `release-and-rollback.md` — PR-014 updated from the old "NestJS 10 -> 11 will fix it" assumption to the measured state: NestJS 11 works, but `@nestjs/platform-express@11.1.27` still reifies `multer@2.1.1`; `multer <2.2.0` remains an accepted availability-only CVE family.

**Verification:**
- `npm ci --ignore-scripts` GREEN (strict lockfile install).
- `npm ls --workspace @raku-rag/api @nestjs/common @nestjs/core @nestjs/platform-express @nestjs/testing @nestjs/cli multer picomatch --all`: NestJS 11.1.x, CLI 11.0.x, `multer@2.1.1`, dev-only picomatch 4.0.4/2.3.2.
- `npm ls picomatch --omit=dev --all`: empty (npm exits 1 for an empty dependency tree).
- `npm audit --workspace @raku-rag/api --omit=dev --json`: still reports `multer` via `@nestjs/platform-express`; root/workspace overrides to `multer@2.2.0` were tested and did not change the reified tree.
- `npm run typecheck --workspace @raku-rag/api` GREEN.
- `npm run build --workspace @raku-rag/api` GREEN.
- `npm run test:e2e --workspace @raku-rag/api` GREEN (77/77).

**Status:** PR-014 remains **Mitigating**, not "fully fixed": the repo-side scanning/SBOM/secret-scan gates are in place and NestJS 11 is locally validated, but the last runtime accepted CVE family (`multer@2.1.1` < 2.2.0) requires an upstream NestJS dependency bump or a package-manager override that actually reifies 2.2.0 in CI.

**Still local-only and not yet done:** governance/audit durability (PR-004/P1-3/P1-10), production telemetry/alarms (PR-005/P1-4), hybrid retrieval core path (PR-007/P1-7), high-risk recall/adversarial corpus (PR-009/P1-6), deeper PII detection/policy (PR-015 tail), and the residual `multer>=2.2.0` supply-chain closure when upstream/override support exists.

---

## Loop 25 — 2026-06-22 — Local-only hardening: API WAF + IP/token rate limits (PR-011)

User goal continuation: first crush the items that can be completed locally before the remaining real-infra release gates.

**Implemented:**
- **PR-011 / P1-11 → Mitigating repo-side:** `infra/cdk/lib/raku-rag-stack.ts` now creates an AWS WAFv2 WebACL for the public NestJS API ALB and associates it with the ALB.
- WAF rules:
  - `AWSManagedCommonRuleSet` for managed common web protections.
  - `IpRateLimit` rate-based block keyed by source IP (`limit`: prod 2000 / non-prod 1000 per WAF evaluation window).
  - `UserTokenRateLimit` rate-based block keyed by `x-user-token` via WAF custom aggregation key (`limit`: prod 600 / non-prod 300), scoped to requests where the token header is present.
- Operations dashboard now includes WAF allowed/blocked request metrics and specific rate-limit block widgets for `IpRateLimit` and `UserTokenRateLimit`.
- `ApiWebAclArn` output added so release/deploy automation can locate the attached edge control.
- `infra/cdk/README.md` and `tests/contract/test_cdk_infrastructure.py` updated to pin the WAF/rate-limit boundary.

**Verification:** `tests.contract.test_cdk_infrastructure` **5 OK**; `npm run build` in `infra/cdk` GREEN; `npm run synth` in `infra/cdk` GREEN and emits `AWS::WAFv2::WebACL`, `AWS::WAFv2::WebACLAssociation`, dashboard WAF metrics, and `ApiWebAclArn`.

**Remaining for full closure:** deploy the CDK stack to the real AWS account, tune limits from production traffic, and add alert/runbook thresholds for elevated WAF blocks. No runtime RAG code changed.

**At that point still local-only and not yet done:** NestJS 10→11 supply-chain follow-up (multer/picomatch), governance/audit durability (PR-004/P1-3/P1-10), production telemetry/alarms (PR-005/P1-4), hybrid retrieval core path (PR-007/P1-7), high-risk recall/adversarial corpus (PR-009/P1-6), and deeper PII detection/policy (PR-015 tail). Superseded for the NestJS item by Loop 26; the residual is `multer>=2.2.0` upstream/override closure.

---

## Loop 24 — 2026-06-22 — Local-only hardening: citation live revalidation + pre-index text redaction

User goal: first crush the items that can be completed locally before the remaining real-infra release gates.

**Implemented:**
- **PR-013 / P1-14 → Fixed locally:** `AnswerService` now revalidates retrieved evidence against the current `Document` state and retrieval visibility (`tenant_id`, tombstone, ACL) before any chunk reaches generation, then rechecks again before returning citations. Invalidated chunks emit `answer_citation_revalidation_dropped_total`; if the profile's minimum evidence is no longer met, the answer is demoted to `insufficient_evidence` with reason `citation_revalidation`.
- `RetrievalService.is_visible()` exposes the same live ACL/tombstone/tenant decision used by retrieval so already-retrieved evidence can be rechecked at serve time.
- **PR-015 / P2-8 → Mitigating:** `IngestionService` applies the shared `Redactor` to text before chunking/embedding/upsert and stores `pii_redaction_applied` + `pii_redaction_policy_ref` on `Document.metadata`. This closes the simple raw email/API-key-at-rest path; higher-recall PII (names/addresses/industry identifiers) and policy-selectable retain/redact behavior remain open.
- Readiness docs updated so PR-013 is not still listed as an open serve-time citation gap and PR-015 is represented honestly as mitigating, not fully closed.

**Tests added/updated:**
- `tests/security/test_citation_revalidation.py` — tombstoned documents and ACL-revoked chunks cannot be served as citations; a revoked chunk is not passed to the LLM context when another valid citation remains.
- `tests/security/test_redaction.py` — text ingestion redacts raw email/API-key values before indexing and answers do not expose the raw sensitive values.

**Verification:** `py_compile` GREEN; targeted security/integration tests **9 OK**; `black` + `ruff` clean on touched code/tests; `scripts/gate.sh all` GREEN (**Tier A 320 OK; full suite 694 OK, skipped 6**).

**At that point still local-only and not yet done:** NestJS 10→11 supply-chain follow-up (multer/picomatch), governance/audit durability (PR-004/P1-3/P1-10), production telemetry/alarms (PR-005/P1-4), hybrid retrieval core path (PR-007/P1-7), high-risk recall/adversarial corpus (PR-009/P1-6), WAF/rate-limit definitions (PR-011/P1-11), and deeper PII detection/policy (PR-015 tail). Superseded for WAF by Loop 25 and for the NestJS item by Loop 26.

---

## Loop 23 — 2026-06-21 — Root-cause campaign for the 4 mitigations/partials (PRs #4–8 merged) + doc reconcile

Driven by the user's "根本解決を求めます" goal — convert each band-aid to a genuine fix, each a verified CI-green merged PR.

- **PR-001 → Fixed (PR #7):** the eval gate now has a real probe for EVERY SECURITY_CHECK. Added `unauthorized_context` + 4 visual probes (the last caller-count-only ones) to `DEFAULT_PROBES`; `tests/unit/test_security_check_probe_coverage.py` pins full coverage + each new probe blocks a leaky stub / is unavailable on a no-op. (PR #6 first loosened the protected suite assertion to a superset — §5-safe test-only change — to allow the expansion.)
- **PR-002 → Fixed/Hardened (PR #5):** the injection guard normalizes (zero-width strip) + uses whitespace-flexible AI-directed patterns, closing the reworded/whitespaced/zero-width bypasses the pre-merge review reproduced; context-neutralization is audited+metered (parity with the query path). Benign manufacturing "override/safety" ops phrasing stays unflagged. Honest limit: a deterministic denylist is defense-in-depth; full closure needs a generative-LLM grounding prompt + Guardrails.
- **PR-003 → write path closed (PR #4):** `/internal/ingest` (+ NestJS DTO/controller) parses a `manufacturing` block and persists it via `ingest_document(manufacturing_metadata=…)`; Tier-B verified over real Postgres. The safety overlay now gets metadata for production-ingested docs (was inert).
- **PR-014 → CVEs root-caused (PR #8):** Next.js 14→15.5 fixes the 5 `next` advisories; clean prod-only image install removes glob/tmp. picomatch (prod via next) + multer (hard-pinned by @nestjs/platform-express@10) accepted — **npm `overrides` are not honored in this workspace** (verified twice; leaves deps "invalid", breaking `npm ci`). Follow-up: NestJS 10→11.

**Verification:** every PR — ruff+black, Tier A + full suite, detect-secrets, §5 separation; #4 Tier-B on real Postgres; #8 blocking Trivy on real images (api+web). All merged into 002; CI green on each.

**残り (product release, real-infra/migration — your environment):** AWS CD/OIDC, rollback/backup dry-run, production-scale load p50/p95/p99, real-data EXPLAIN. Historical note: the NestJS 10→11 item listed here was revisited in Loop 26; NestJS 11 is locally validated, picomatch is removed from prod-only deps, and the remaining supply-chain tail is `multer>=2.2.0` upstream/override closure.

---

## Loop 22 — 2026-06-21 — P1-9 SQS worker/DLQ ops boundary fixed (SQS vs Dagster separation)

**実装した変更:**
- `src/raku_rag/workers/queue/sqs.py` — `SqsTaskQueue` now takes `SQS_DLQ_URL` and `SQS_MAX_RECEIVE_COUNT`; normal failures only shorten visibility, while the final receive returns `True`, copies the original message to the DLQ when configured, and deletes the source message so app state and queue state do not drift.
- `workers/ingest/worker.py` — added production `--serve` mode for long-lived ECS polling; `--drain` remains local/maintenance only. The worker passes DLQ config into the SQS adapter.
- `infra/cdk/lib/raku-rag-stack.ts` — ECS worker command changed from `--drain` to `--serve`; worker receives `SQS_DLQ_URL`/`SQS_MAX_RECEIVE_COUNT` and can send to the DLQ.
- `workers/ingest/README.md` — documents `--serve` vs `--drain` and keeps Dagster as offline control plane for reindex/backfill/evaluation/KPI, not request-time answer/search.

**検証:** targeted unit/integration/contract tests GREEN (11): SQS retry vs final DLQ projection, ingestion worker DLQ state projection, CDK worker long-running command + DLQ env. `py_compile` GREEN; worker `--serve --max-idle-polls 1` smoke GREEN.

**Risk PR-010 → Fixed.** Remaining Dagster productionization is separate: add real Dagster webserver/daemon/EcsRunLauncher if you want the optional control plane on ECS, without putting Dagster in the hot answer/search path.

## Loop 21 — 2026-06-21 — #5 Trivy flipped to BLOCKING after real CVE triage (PR-014 → Fixed at that point; revised in Loop 26)

**Triage of the real CI Trivy report** (api/web/worker images): OS/debian base layers **0 HIGH/CRITICAL**; 9 distinct HIGH npm CVEs (0 CRITICAL). Root cause: both node Dockerfiles `COPY` the FULL `node_modules` (incl. devDeps) into runtime. `npm why` split them: dev = glob/picomatch/tmp (3, via jest); prod = next ×2 + multer ×4 (6).

**実装した変更:**
- `apps/{web,api}/Dockerfile` — `npm prune --omit=dev` after build (build stage) so dev tooling is NOT shipped in runtime images → removes the 3 dev CVEs for real (also good image hardening). worker is Python — unaffected.
- `.trivyignore` (NEW) — accepted advisories (0 CRITICAL) with per-package justification + follow-ups. **Iterated on CI to nail the true survivor set** (the box-drawing Trivy table wraps, so early CVE→package mapping was wrong). Final, evidence-based: `npm prune --omit=dev` (per-image 13→4 HIGH) **removes glob+tmp** (verified: adding them changed the count by 0); **picomatch survives** prune (hoisted via @nestjs/cli/@angular-devkit/chokidar) → accepted by CVE-2026-33671; **multer** (prod) accepted by 4 CVEs; **next** (frontend, 3 advisories) was the persistent blocker because Trivy's DB keys its advisories by **EITHER CVE or GHSA depending on the DB snapshot** (one run showed CVE-2026-44573/44578, another GHSA-8h8q/h25m/q4gf) — fixed by listing BOTH id forms. Follow-up: prod-only runtime install + multer→2.2.0 + Next.js 15. **GREEN on CI: 19 pass, 0 fail (both api+web image builds pass under blocking Trivy).**
- `.github/workflows/deploy-checks.yml` — `trivyignores: .trivyignore` + **`exit-code: "0"`→`"1"` (BLOCKING)**.

**検証:** Trivy can't run locally (no Docker) — CI deploy-checks is the authority. Took several CI iterations to read the wrapped table correctly (key lesson: Trivy reports npm advisories by GHSA *or* CVE; ignore by the exact ID it prints). Re-verified green on CI.

**Risk PR-014 → Fixed at that point; PR-012 Trivy-flip thread closed.** Current PR-014 status was revised in Loop 26 after the NestJS 11 follow-up measured the remaining `multer@2.1.1` CVE tail. Remaining real-infra: AWS CD/OIDC (#3), rollback/backup (#4), real-data EXPLAIN + load p50/p95/p99 (#2).

**次のループ:** push branch → PR → CI deploy-checks Trivy (blocking) confirms → merge.

---

## Loop 20 — 2026-06-21 — P1-1 Postgres-data step + Tier-B VERIFIED on real Postgres (PR-003 → Fixed)

**Discovery:** a real **PostgreSQL 14 + pgvector 0.8.0** is reachable in this environment (DSN `…/raku_parity`) — Tier-B is runnable here, not only on CI runners. (Updates the prior "Tier-B only on runners" assumption.)

**実装した変更 (PR-003 remaining "Postgres-data" step):**
- `src/raku_rag/production.py` — `ProductionSystem.attach_manufacturing_metadata()` persists `ManufacturingDocumentMetadata.to_mapping()` (jsonb-safe) into `Document.metadata`; `ingest_manufacturing()` = reused 001 text-ingest + attach. In-memory path untouched (no regression); the deployed resolver reads it back via `from_mapping`.
- `tests/postgres/test_manufacturing_overlay_parity.py` (NEW, Tier B) — over real Postgres: to_mapping→jsonb→from_mapping round-trip; draft-only high-risk **blocked**; approved+effective **answers** (no over-block).
- `.github/workflows/gate.yml` — tier-b change-detection now also triggers on `src/raku_rag/production.py` + `tests/postgres/` (so the gate runs on the runner's real Postgres).
- `scripts/postgres-migration-smoke.sh` — extended to **0007** (apply + evaluation_runs column check + down): full 0001..0007 chain.

**検証 (REAL Postgres):** 001 security parity **49 OK** over Postgres (`RAKU_TEST_BACKEND=postgres`); `tests/postgres` **7 OK** (incl. the 3 new); migration smoke **0001..0007 GREEN** with tenant RLS (`tenant_a_sees=1`, `tenant_b_cannot=1`); HNSW index present on `chunks` (runtime EXPLAIN index-scan needs production-scale rows — table had 3, planner correctly Seq-Scans tiny tables: an honest data-volume gap, not an index regression). Tier A GREEN (319), full suite GREEN, lint clean.

**Risk PR-003 → Fixed** (overlay on the deployed path + jsonb round-trip + high-risk gate verified over real Postgres). Thin remaining thread: call `ingest_manufacturing`/`attach_manufacturing_metadata` from the actual ingest API/worker so production-ingested docs carry mfg metadata; chunk-level metadata over Postgres (search `manufacturing_filters`) is a separate follow-up.

**次のループ:** push branch `004-tier-b-p1-1-postgres` → PR → CI tier-b confirms on the runner → merge. Then remaining real-infra gates: real-data EXPLAIN + load p50/p95/p99 (#2), AWS CD/OIDC (#3), rollback/backup dry-run (#4), Trivy-blocking flip after CVE triage (#5).

---

## Loop 19 — 2026-06-21 — PR #1 opened, CI greened, adversarial pre-merge verify, GAP-S3 secondary-slot fix

**PR #1 + CI:** pushed `003-production-readiness-hardening`, opened **PR #1** (base `002`). First CI run was red; triaged 5 real failures (all in NON-protected files, §5 intact): Trivy action tag `@0.28.0`→`@v0.36.0` (hash-pinned `setup-trivy`, immune to the upstream `setup-trivy@v0.2.1` tag deletion); detect-secrets false-positive on a planted probe fixture → inline `# pragma: allowlist secret`; **Tier-B Postgres first-init race** → TCP `pg_isready` pre-warm step in `gate.yml` (gate.sh untouched); new-branch `before=000…0` diff-128 → `git rev-parse --verify` + force-run fallback; black format debt on 5 landed-perf files. Result: **all CI green** on `ff8323c` (Tier A/B, security-hard-gate, eval-gate, separation, RT1, Tier D, image-build+SBOM+Trivy, CDK).

**Adversarial pre-merge verification (Workflow, 10 agents — review + refute):** `no-weakening` **SAFE both rounds** (ACL pre-filter, deletion, citation, groundedness intact — no regression); `ci-fix-soundness` SAFE; `eval-gate-real` confirmed probes computed + fail-closed (flake not reproducible over 200 runs). **GAP-S3 → HIGH, reproduced by both agents:** the demotion guarded only `citations[0]`; with approved`[0]`+draft`[1]`, the draft's dangerous text leaked into a high-risk answer (cited at `[1]`, no demotion). Injection denylist bypass + log-only neutralization noted as MEDIUM residuals (PR-002, not regressions).

**実装した変更 (GAP-S3 secondary-slot fix — SAFETY BOUNDARY, human-directed):**
- `src/raku_rag/manufacturing/api/answer_ext.py` — high-risk demotion now fires unless **EVERY** citation is approved+effective (was `[0]`-only). Covers text contamination at the root (any contaminating chunk is necessarily cited).
- `tests/manufacturing/test_source_poisoning.py` — `test_poison_draft_in_secondary_slot_is_demoted` (verified FAIL pre-fix / PASS post-fix); primary-slot + positive control retained.
- `src/raku_rag/eval/probes.py` — `source_poisoning_probe` runs BOTH orderings (primary + secondary); secondary scenario leaks pre-fix (1) → 0 post-fix. Release-blocking.

**検証:** reproduction confirmed (revert→FAIL/leak=1, restore→PASS/leak=0); Tier A GREEN (319), full suite GREEN (667), ruff+black+detect-secrets clean, separation OK. Commit `2d7abf0` (`fix(002)!`). Risk **PR-016 → Fixed (two rounds)**.

**次のループ:** push the GAP-S3 fix, confirm CI green, **merge PR #1** (user chose fix-then-merge). Then the irreducible real-infra remainder (Tier-B/Postgres data path, load+EXPLAIN, CD→AWS, Trivy-flip, rollback/backup dry-run) + final human release GO. Injection denylist hardening (PR-002 residual) is a candidate follow-up.

---

## Loop 18 — 2026-06-21 — P1-1 NestJS facade (ManufacturingController) — P1-1 complete at app layer

**実装した変更:**
- `apps/api/src/manufacturing/manufacturing.controller.ts` (NEW) — `POST /v1/manufacturing/answer` thin facade: AuthMiddleware principal → forwards to answer-service `/internal/manufacturing/answer`; tenant/identity from the **signed token, never the body**; safety fields passed through; 502 on upstream failure. No RAG/safety logic reimplemented.
- `apps/api/src/app.module.ts` — registered `ManufacturingController` (controllers + AuthMiddleware-protected routes).
- `apps/api/test/manufacturing.e2e-spec.ts` (NEW, 2) — 401 without auth; forwards with signed principal (body `tenant_id` ignored → `tenant_a`), safety fields (`high_risk`, `safety_block_reason`) passed through (upstream stubbed, no Postgres needed).

**検証:** `npm run typecheck --workspace @raku-rag/api` clean; **`npm run test:api` 19 suites / 77 tests GREEN** (+2, no regression); Python `scripts/gate.sh a` GREEN; separation OK.

**🎯 P1-1 complete at the application layer** — overlay factory + persisted-metadata resolver (Loop 13) → answer-service route + serializer (Loop 17) → NestJS facade + e2e (Loop 18). Risk **PR-003 → Mitigating**; remaining = `metadata.to_mapping()` on the Postgres ingest path + Tier-B over `ProductionSystem` (real DB only).

**All 5 release blockers are now done to the limit of what the sandbox can build+verify. The irreducible remainder is real-infra-only** (Tier-B/Postgres, real load+EXPLAIN, CD→AWS, Trivy-flip after CVE triage, rollback/backup dry-run) + the **commit/PR** (your go) + the final human **release-checklist GO**.

---

## Loop 17 — 2026-06-21 — P1-1 deployment exposure on the answer-service + eval-persistence wiring

Both are sandbox-doable productionization items (server.py is editable + in-process-importable via the existing `load_answer_service_module` test pattern).

**P1-1 route (deployed boundary):**
- `apps/answer-service/server.py` — `POST /internal/manufacturing/answer` runs the safety overlay via `build_manufacturing_answer_service(system)` (high-risk gate, approved+effective requirement, draft/obsolete never primary incl. GAP-S3) + `_manufacturing_answer_json` serializer (safety fields nested under `manufacturing`, GAP-M02; citations carry approval provenance).
- `tests/integration/test_manufacturing_answer_endpoint.py` (NEW, 2) — high-risk w/o approved → `insufficient_evidence` + `manufacturing.safety_block_reason=approved_citation_missing`; with approved → ok + on-site notice + `citations[0].approval_status=approved`.
- Risk **PR-003 → Mitigating**. Remaining: NestJS `ManufacturingController` facade + e2e; write `metadata.to_mapping()` on the Postgres ingest path; Tier-B over `ProductionSystem`.

**eval-persistence → server.py (本番化 item):**
- `_EvalFeedbackStore` now persists runs via an `EvaluationRunRepository` (default in-memory; production swaps `PostgresEvaluationRunRepository(system._conn)` once migration 0007 is applied); `get_run` reads from the durable repo; added `list_runs` (trendable, tenant-isolated).
- `tests/integration/test_eval_persistence_endpoint.py` (NEW, 2) — create_run persists (metrics/gate_result/probes_executed read back); list_runs trends + tenant-isolated.

**検証:** endpoint 2 + persistence 2 + answer-service consumers GREEN; `scripts/gate.sh all` GREEN (**666**); separation OK; ruff/black clean; server.py secret-clean; CI mypy GREEN.

**Irreducible real-infra remainder (cannot run from sandbox):** NestJS facade + e2e (npm), Tier-B over real Postgres, real p50/p95/p99 at scale, actual `EXPLAIN`, CD→AWS/OIDC/Secrets Manager, Trivy flip after CVE triage, rollback/backup dry-run, and the final human release-checklist GO. The **commit/PR** of this changeset awaits your go (safety-boundary work + outward-facing).

---

## Loop 15 — 2026-06-21 — T117/T118 performance readiness (harness + EXPLAIN gate)

**実装した変更:**
- `tests/benchmarks/load_harness.py` (NEW) — reusable `run_load(call, concurrency, iterations)` → `LoadStats(p50/p95/p99/qps, errors)`; stdlib `ThreadPoolExecutor`. Drives the in-memory path (smoke) or a deployed-service client (real load).
- `tests/integration/test_load_smoke.py` (NEW, T117) — concurrent **multi-tenant** (5 tenants × 8 docs) load smoke: asserts p99 ≤ `Settings.target_p95_latency_ms`, 0 errors, and **tenant isolation under concurrency** (a worker raises on any cross-tenant citation → error). Sandbox run: 160 calls, 0 errors, p50≈3.9ms / p95≈11ms / p99≈15ms.
- `tests/contract/test_explain_gate.py` (NEW, T118 static) — pins the query SHAPE an EXPLAIN confirms: pgvector cosine `embedding <=> ::vector` over the live (`tombstone=false`) set, RLS tenant binding via `set_config`, and hnsw + metadata/identifier hot indexes declared.
- `scripts/postgres-explain-gate.sh` (NEW, T118 runtime) — runs `EXPLAIN` on the tenant-scoped vector search against a real Postgres, **fails on `Seq Scan on chunks`** (index-not-used regression); exit 2 if no PG (Tier B / CI).

**検証:** load-smoke + explain-contract 5 GREEN; `scripts/gate.sh all` GREEN (**662**, skipped 6); separation OK; ruff/black clean; secret-clean; script `bash -n` OK.

**Needs real infra (NOT sandbox-verifiable):** real p50/p95/p99/QPS at scale (run `load_harness` against the deployed service, large corpus / many tenants on real infra); the actual `EXPLAIN` via `scripts/postgres-explain-gate.sh` on a real pgvector DB (Tier B / CI).

---

## Loop 14 — 2026-06-21 — P1-8 retrieval failure root-cause logging (PR-006)

**実装した変更 (`src/raku_rag/services/retrieval.py`, additive — behavior unchanged):**
- Rerank failures are no longer silent: logged (`retrieval.rerank_failed`) + metric `retrieval_rerank_failures_total` + span attrs `rerank_status`/`rerank_error`; still fail-safe (falls back to capped order).
- `last_prefiltered_count` exported (metric `retrieval_prefiltered_count` + span attr) so an empty retrieval is attributable.
- Empty-retrieval root cause: `retrieval_outcome` ∈ {`ok`,`no_visible_candidates`,`post_filter_empty`} (span + `retrieval_empty_total{outcome}` + log) — distinguishes "tenant/ACL/tombstone removed all" from "candidates passed but none survived". (`record_stage` stays `ok`: an empty result is a valid outcome, not an error.)

**検証:** `tests/integration/test_retrieval_failure_logging.py` (3): rerank failure recorded (fallback still returns results); ACL-emptied retrieval → `no_visible_candidates` + `prefiltered_count=0` + metric; success → `ok`. must-not-regress 16 GREEN. `scripts/gate.sh a` GREEN (**319**); `scripts/gate.sh all` GREEN (**657**); separation OK; ruff/black clean; secret-clean. **Risk PR-006 → Fixed.**

**次のループ:** **T117/T118** performance readiness — load-test harness (p50/p95/p99, concurrency, large corpus, many tenants) + EXPLAIN gate (filter pushdown / pgvector index / RLS plan). The harness is authorable + sandbox-smoke-runnable (in-memory); real load numbers + actual `EXPLAIN` need a real Postgres + load infra.

---

## Loop 13 — 2026-06-21 — P1-1 (GAP-F05) safety-overlay deployment wiring — verifiable core

**Key architecture finding:** `ProductionSystem(MvpSystem)` exposes the SAME `.retrieval/.gate/.answer_service/.registry/.llm`, and `ManufacturingAnswerService` is composed purely from those injected deps — so the safety overlay runs over EITHER base system unchanged. The only deployment-specific piece is resolving mfg metadata from the PERSISTED `Document.metadata` (not an in-process dict).

**実装した変更 (verifiable core):**
- `src/raku_rag/manufacturing/domain/metadata.py` — `ManufacturingDocumentMetadata.to_mapping()` / `from_mapping()` (jsonb-safe round-trip; also unblocks Postgres mfg-metadata persistence / GAP-F08).
- `src/raku_rag/manufacturing/wiring.py` (NEW) — `registry_mfg_meta_resolver(system)` (reads metadata from `Document.metadata`, dataclass OR jsonb-dict; tombstone-aware, GAP-S2) + `build_manufacturing_answer_service(system)` (composes the overlay — high-risk gate, approved+effective requirement, draft/obsolete-never-primary incl. the GAP-S3 demote — over any 001 base system).
- `tests/manufacturing/test_overlay_wiring.py` (NEW, Tier-A) — proves the overlay's safety gate fires over a plain `MvpSystem` via persisted `Document.metadata`: high-risk blocked without approved citation; answers with approved+effective primary (+ on-site confirmation); **resolves the Postgres jsonb-dict form**; tombstoned doc → None.

**検証:** overlay-wiring 4 + metadata round-trip GREEN; `scripts/gate.sh a` GREEN (**319**); `scripts/gate.sh all` GREEN (**654**, skipped 6); separation OK; ruff/black clean; CI mypy GREEN; secret-clean. Nothing committed.

**Remaining for P1-1 (deployment exposure — needs real DB / npm e2e, NOT sandbox-verifiable):**
- answer-service `/internal/manufacturing/answer` route calling `build_manufacturing_answer_service(self._system)` + serialize the safety fields; NestJS `ManufacturingController` thin facade + e2e.
- `ingest_manufacturing` write `metadata.to_mapping()` into `Document.metadata` (jsonb) on the Postgres path so the resolver reads persisted metadata (the in-memory path already works).
- Tier-B test of the overlay over `ProductionSystem`.
The factory makes these mechanical; they are gated on a real Postgres + the NestJS e2e harness.

**次のループ:** **P1-8** retrieval failure root-cause logging (fully sandbox-verifiable, self-contained: `services/retrieval.py` non-`ok` statuses + `last_prefiltered_count` export + surfaced rerank failures).

---

## Loop 12 — 2026-06-21 — P1-2 prompt-injection defense in the LIVE answer flow

**実装した変更:**
- `src/raku_rag/services/injection.py` (NEW) — `PromptInjectionGuard`: deterministic denylist (EN+JP, specific multi-token phrases; not broad words like "override"). `inspect(text)` (detect) + `neutralize(text)` (replace instruction spans with an inert marker, keep legit content).
- `src/raku_rag/services/answer.py` — guard wired into the live flow (default-on, provider-agnostic), after evidence selection, before generation: **query injection → REFUSE** (`insufficient_evidence`, reason `prompt_injection`, audited); **context injection → NEUTRALIZE** the chunk text passed to the model (citations still match ORIGINAL chunk text; never obeyed; logged, not silent). Never widens ACL/groundedness.
- `tests/security/test_prompt_injection_flow.py` (NEW hard gate, Tier-A) — unit (detect EN/JP, neutralize keeps legit, benign untouched, "override" not flagged) + integration (query override refused; embedded instruction neutralized + no exfiltration of an unauthorized doc; benign not over-blocked).

**Policy fixed:** query-injection ⇒ `insufficient_evidence` (refuse); context-injection ⇒ neutralize+proceed (logged). (`AnswerStatus` has no separate `review_required`/`blocked`; `insufficient_evidence` is the established no-assert outcome.)

**検証:** injection-flow 7 + must-not-regress 17 GREEN; `scripts/gate.sh a` GREEN (**315**); `scripts/gate.sh all` GREEN (**650**, skipped 6); separation OK; ruff/black clean; CI mypy GREEN (16 files; services not in mypy scope); secret-clean. Nothing committed. **Risk PR-002 → Mitigating.**

**Remaining for PR-002:** NestJS Guardrails adapter as facade defense-in-depth + grounding/anti-fabrication system prompt once a real generative LLM is wired (deployed provider is still extractive).

**次のループ:** **P1-1** wire the manufacturing safety overlay onto the deployed answer path (GAP-F05) — now unblocked (`apps/answer-service/server.py` committed at e26c397).

---

## Loop 11 — 2026-06-21 — GAP-S3 / PR-016 source-poisoning SAFETY FIX (perf changeset landed at e26c397)

**Baseline:** perf changeset committed at `e26c397` ("Add RAG performance guardrails") — blockers cleared; my prior uncommitted work intact; Tier A green on the new HEAD. This is a **safety-boundary** change, human-directed by the user with explicit acceptance.

**実装した変更:**
- `src/raku_rag/manufacturing/api/answer_ext.py` (FIX) — the post-answer demote now also covers the high-risk case: a high-risk answer whose **PRIMARY** citation is not approved+effective is demoted to `insufficient_evidence` (`approved_citation_missing`), **even when an approved doc is cited elsewhere** (the source-poisoning hole — the SafetyGate only checked that *some* approved doc existed among candidates, not that the asserted/primary evidence was approved). Existing obsolete-primary demote (FR-MFG-011) preserved unchanged.
- `tests/manufacturing/test_source_poisoning.py` (NEW hard gate, Tier-A auto-included) — reproduces the old failure (approved + poison draft, high-risk → must not assert from the draft primary) and asserts the fixed demote; **positive control** (approved-only high-risk still answers → no over-block). Pre-fix it FAILS, post-fix it passes.
- `src/raku_rag/eval/probes.py` + `runner.py` — `source_poisoning_probe` is now **default-on** (in `DEFAULT_PROBES`) and a gate name in `SECURITY_CHECKS` (release-blocking). Probe leak logic updated: a *demote* (status≠ok) is the SAFE outcome; a LEAK = status ok with the draft cited / non-approved primary. Stub tests updated (poison→blocked, clean→ok, demote→ok, no-high-risk→unavailable).

**Acceptance (5/5):** draft/poisoned cannot be primary evidence for high-risk ✓ · high-risk demoted to insufficient_evidence unless approved/effective supports ✓ · `source_poisoning_probe` in the default release-blocking suite ✓ · hard-gate test reproduces old failure + passes after fix ✓ · no weakening of groundedness/ACL/deletion/citation ✓ (protected gates `test_safety_gate`/`test_obsolete_draft_evidence`/`test_draft_only` **unmodified + green**; full suite green).

**検証:** new gate + eval probes + consumers (22) GREEN; real ManufacturingSystem poison scenario now `insufficient_evidence`/`approved_citation_missing`/no-citations; `scripts/gate.sh a` GREEN (**315**); `scripts/gate.sh all` GREEN (**643**, skipped 6); `scripts/gate.sh separation` OK; ruff/black clean; **CI mypy GREEN** (16 files; the lone explicit-file mypy note is pre-existing + out-of-scope in `_matches_filters`, untouched); new files secret-clean. Separation: no tracked protected file modified (new gate is a new file; `test_eval_security_probes.py` is still untracked). Nothing committed. **Risk PR-016 → Fixed; GAP-S3 → [x].**

**次のループ:** **P1-2** prompt-injection defense in-flow (pairs with the injection eval probe; now unblocked — `services/answer.py`/`apps/api/guardrails`), then **P1-8** retrieval failure logging (`services/retrieval.py`). Both editable now that e26c397 landed.

---

## Loop 10 — 2026-06-21 — P2-9 persist eval runs to evaluation_runs (trendable across releases)

**実装した変更 (scope: eval/persistence/migration/tests — NO forbidden runtime files):**
- `infra/db/migrations/postgres/0007_eval_run_persistence.sql` (+`.down.sql`, NEW) — **additive** ALTER of `evaluation_runs` (created RLS-scoped in 0002): adds `eval_set_id`, `baseline`, `gate_result`, `baseline_comparison` jsonb, `probe_results` jsonb, `probes_executed`, + `idx_evaluation_runs_trend (tenant_id, eval_set_id, created_at DESC)`. New file → separation-safe; new columns inherit 0002 RLS; protected RLS/schema tests assert presence (not a closed set) so unaffected.
- `src/raku_rag/persistence/evaluation_runs.py` (NEW) — shared row **codec** (`evaluation_run_to_row`/`row_to_evaluation_run`) + `InMemoryEvaluationRunRepository` (default, Tier A) + `PostgresEvaluationRunRepository` (Tier B, RLS via session tenant, `ON CONFLICT DO UPDATE`). Stores the **serialized** row and reconstructs on read (no echo). `examples` intentionally not persisted (metric/gate/provenance trending, not per-item replay). psycopg imported lazily → Tier-A-import-clean.
- `src/raku_rag/eval/runner.py` — **additive** optional `run_repository=None`; when supplied the completed run is persisted at the end of `run()`. Default None → existing behavior unchanged.

**Acceptance (4/4, verified locally):** writes metrics/security_checks/baseline_comparison/gate_result/provenance ✓ · read back deterministically ✓ (codec round-trip) · existing eval behavior unchanged ✓ (`run_repository` default None; `test_runner_without_repository_is_unchanged`) · **no no-op/echo loophole** ✓ (`test_persistence_is_a_copy_not_a_reference`: mutate original after save → stored row unchanged; `get()` returns a reconstructed object) · trendable ✓ (`list_runs` ordered per tenant/eval-set; tenant-isolated).

**実行したテスト:** `test_eval_run_repository` (8) + extended `test_schema_lock_migration_sql` (0007 columns + index + down) GREEN; eval consumers no-regression; ruff/black/mypy clean; `scripts/gate.sh all` GREEN (**640**, skipped 6); `scripts/gate.sh separation` OK; new files secret-clean. **Postgres adapter is Tier-B-validated** (no Postgres locally; pattern-faithful to `PostgresIngestionRunStore`). Nothing committed.

**Deferred (blocked):** wiring the repository into the deployed eval endpoint (`apps/answer-service/server.py`, in-memory dict today) — `server.py` is in the concurrent-actor/forbidden set; wire once it lands. The capability + repo + migration are ready.

**次のループ:** the user plans to **commit the perf changeset**, which unblocks **P1-1 / P1-2 / P1-8 + GAP-S3** (the higher-impact items in `answer.py`/`retrieval.py`/`server.py`). On commit: re-check `git status`/HEAD, then pick up P1-2 (prompt-injection defense in-flow — pairs with the injection eval probe) or P1-1 (deploy the safety overlay) or GAP-S3 (safety fix). Until then, remaining isolated docs/infra items only.

---

## Loop 9 — 2026-06-21 — P1-12 tail: release/rollback runbook + safe CD skeleton + Trivy flip policy

**実装した変更 (docs/.github only — NO runtime RAG code):**
- `docs/production-readiness/release-and-rollback.md` (NEW) — §1 **release checklist** mapping this repo's actual gates (gate.yml Tier A/B/separation/rt1, ci.yml eval+security, deploy-checks build/SBOM/Trivy, golden-corpus baseline, secret-scan, migration smoke) + human go/no-go to a GO/NO-GO decision; §2 **rollback runbook** (app image rollback, migration **expand-only/forward-fix** policy using the paired `*.down.sql`, config rollback via Secrets Manager versions, incident comms w/ SEV table — ACL/tenant/deletion/safety = SEV-1); §3 **CD path** via GitHub OIDC + Secrets Manager (no repo secrets); §4 **Trivy flip criteria** (triage → `.trivyignore` → fix → flip exit-code 0→1; explicit blocking criterion = new fixable HIGH/CRITICAL).
- `.github/workflows/deploy.yml` (NEW) — **safe CD skeleton**: `workflow_dispatch`-only, `environment`-gated (production = required reviewer), **OIDC** role assumption via `vars.AWS_DEPLOY_ROLE_ARN` (no committed secrets), preflight **inert until configured**, `dry_run` default true (real deploy needs dry_run=false + approval + vars). Inputs passed via `env:` + quoted (`security-guidance` injection-safe).

**Acceptance (4/4):** release checklist maps preflight→go/no-go ✓ · rollback runbook covers app image / migration rollback+forward-fix / config / incident comms ✓ · CD path documented w/o prod secrets in repo ✓ (OIDC + Secrets Manager + inert skeleton) · Trivy blocking criteria explicit but not flipped blindly ✓.

**検証:** deploy.yml valid YAML · both new files secret-clean (detect-secrets) · `scripts/gate.sh a` GREEN · `scripts/gate.sh separation` OK · footprint docs/.github only. Nothing committed.

**Risk:** PR-012 → Mitigating (repo-side done; remaining is the ops task of wiring the skeleton to a real AWS account + flipping Trivy after triage). **🎯 P1-12 closed at the repo level.**

**次のループ:** **P2-9** persist eval runs to the unused `evaluation_runs` table (isolated, eval area) is the next isolated item. **P1-1/2/8 + GAP-S3** still wait for the concurrent perf changeset (`answer.py`/`retrieval.py`/`metrics.py`/`retrieval-profile*` still uncommitted at HEAD `d225f73`).

---

## Loop 8 — 2026-06-21 — P1-12 deployment outer-frame (Dockerfiles + CDK synth + image scan/SBOM + migration-smoke fix)

**実装した変更 (scope: Dockerfiles / .github CI / infra / migration-smoke — NO runtime RAG code):**
- `apps/api/Dockerfile`, `apps/web/Dockerfile`, `workers/ingest/Dockerfile` (NEW) — multi-stage; build context = repo root (npm workspaces + `@raku-rag/shared`; `src/`+`workers/` for the Python worker). api entry `dist/src/main.js`; worker `python -m workers.ingest.worker`.
- `.github/workflows/deploy-checks.yml` (NEW, path-gated) — **cdk-synth** job (`npm ci && build && synth`) + **image-build-scan** matrix (api/web/worker): `docker build` → **SBOM** (anchore/syft, SPDX-JSON, uploaded) → **Trivy** HIGH/CRITICAL scan (report-only, `ignore-unfixed`, flip to blocking after triage). No untrusted `github.event.*` input (static matrix via `env:`).
- `.github/workflows/ci.yml` — **migration-smoke false positive FIXED**: was `--dir infra/db/migrations` (only `.gitkeep`; real SQL in `postgres/`, non-recursive + Postgres-only) → applied 0 & passed. Now runs the runner against `infra/db/migrations/sqlite/` and **asserts** "applied 1 migration" + idempotent "no pending"; fails on a no-op.
- `infra/db/migrations/sqlite/0001_runner_smoke.sql` (NEW) — trivial sqlite framework smoke (clearly documented as NOT a production migration; real PG migrations stay in `postgres/`, covered by gate.yml tier-b + `scripts/postgres-migration-smoke.sh`).

**Acceptance (5/5):** Dockerfiles build in CI ✓ (CI-validated on GitHub runner; underlying `build:shared`/`nest build`/`next build`/worker-import all verified locally) · CDK synth runs in CI ✓ (synth+build verified locally exit 0) · migration-smoke false positive fixed ✓ (verified locally) · image scan + SBOM run in CI ✓ (Trivy + syft per image) · no runtime RAG behavior changes ✓.

**実行したテスト/検証:** both workflows valid YAML · migration-smoke exact commands pass locally (apply ✓ idempotent ✓) · `cd infra/cdk && npm run build`+`synth` exit 0 · new files secret-clean (detect-secrets) · `scripts/gate.sh a` GREEN · `scripts/gate.sh separation` OK. **Docker build/Trivy/SBOM validate only on a GitHub Docker host** (no Docker in this env — same constraint as RT1; de-risked via local build-command verification). Nothing committed.

**Risk:** PR-012 → Mitigating (build/scan/SBOM/synth + migration fix landed; CD pipeline + release checklist/rollback runbook remain).

**次のループ:** remaining isolated: CD/deploy pipeline + **release checklist & rollback runbook** (docs), flip Trivy to blocking after CVE triage, **P2-9** persist eval runs. **P1-1/2/8** + **GAP-S3** still wait for the concurrent perf changeset (`answer.py`/`retrieval.py`/`metrics.py`/`retrieval-profile*` still uncommitted).

---

## Loop 7 — 2026-06-21 — P1-13 secret-scanning in CI (isolated quick win)

**実装した変更 (scope: `.github/` + CI/security-scan config ONLY — no runtime RAG code):**
- `.github/workflows/security-scan.yml` (NEW) — `detect-secrets` runs on push/PR: (1) scans all tracked files against the committed `.secrets.baseline` (fails on any new, un-audited secret); (2) **seeded self-test** — generates a throwaway `openssl` key at runtime (no secret literal in the file) and asserts the scanner flags it, else the job fails. Uses no untrusted `github.event.*` input (no injection vector).
- `.secrets.baseline` (NEW) — audited allowlist of the 15 current findings, all confirmed **false positives** (local-dev DSNs `raku:raku`, `.env.example`, docker-compose passwords, doc snippets, tooling hashes, intentional test-fixture secrets). Stores only `hashed_secret` (no raw values). `package-lock.json` + the baseline itself are excluded to avoid noise.

**Acceptance (all met, locally verified — detect-secrets installable here):** secret scan runs in CI ✓ · seeded fake-secret regression proves the scanner fails when expected ✓ (openssl key → hook exit 1) · allowlist avoids generated/fixture false positives ✓ (baseline + excludes; repo scan exit 0) · no runtime RAG code changed ✓.

**実行したテスト:** repo scan exit 0 (clean) · workflow file itself secret-clean · seeded key detected (exit 1) · YAML valid · `scripts/gate.sh a` GREEN · `scripts/gate.sh separation` OK. Actual detect-secrets run happens on GitHub CI; verified locally too. Nothing committed.

**Risk:** PR-014 → Mitigating (secret-scan landed; image-scan/SBOM/Dockerfiles remain under P1-12).

**次のループ:** P1-1 / P1-2 / P1-8 still **blocked** on the concurrent perf changeset (still uncommitted: `answer.py`/`retrieval.py`/`metrics.py`/`retrieval-profile*`). Remaining isolated options: **P1-12** (Dockerfiles + `cdk synth` CI + fix the false-positive migration smoke + image scan/SBOM), **P2-9** (persist eval runs to `evaluation_runs`). **GAP-S3 (PR-016)** safety fix is yours.

---

## Loop 6 — 2026-06-21 — P1-5 (eval depth) slice 3: golden corpus + committed baseline → **P1-5 CLOSED**

**実装した変更 (isolated to fixtures + eval test + spec — none of the concurrent actor's files):**
- `tests/fixtures/uat/golden_corpus.json` (NEW) — representative per-industry synthetic corpus (18 items × 3 industries: manufacturing / real-estate / investment; unique-token questions → deterministic retrieval; no real PII).
- `tests/fixtures/eval/golden_baseline.json` (NEW) — **committed deterministic baseline** (measured floors: recall/mrr/citation/groundedness/faithfulness=1.0, precision@k=0.2 [=1/top_k], query_cost≤18; latency = generous ceiling only). Replaces the self-derived `baseline_from_run` for this gate.
- `tests/integration/test_golden_corpus.py` (NEW, 5 tests) — passes at committed baseline; **seeded regressions FAIL**: (a) tombstone an expected doc → recall/precision/mrr drop → blocked; (b) per-metric degrade of precision_at_k / mrr / faithfulness → blocked; **(c) loophole guard**: `DEFAULT_MIN_METRICS` omits precision/mrr/faithfulness so a default-style baseline misses a faithfulness regression that the committed baseline catches.

**Acceptance (all met):** representative per-industry set ✓ · committed deterministic baseline.json ✓ · seeded regression fails when precision/MRR/faithfulness degrade ✓ · no self-derived loophole ✓.

**実行したテスト:** golden-corpus 5 OK; `scripts/gate.sh a` GREEN (313); `scripts/gate.sh all` GREEN (**630**, skipped 6); `scripts/gate.sh separation` OK; ruff/black clean. Runs in the loop gate automatically (`gate.sh all` = full suite). Nothing committed.

**🎯 P1-5 (eval depth) CLOSED** — precision@k + MRR (Loop 4) + faithfulness (Loop 5) + golden corpus & committed-baseline regression gate (Loop 6). The eval gate is now a real quality-regression detector, not a mechanism check.

**次のループ:** options — (a) **P1-13** secret-scanning CI (isolated `.github/`, quick win); (b) wait for the concurrent perf changeset to land, then **P1-1 / P1-2 / P1-8** (deploy safety overlay / injection-defense-in-flow / retrieval failure logging — all in the actor's files); (c) **GAP-S3 (PR-016)** safety fix is yours. P1-5 US-future (LLM-as-judge faithfulness overlay, larger 20-50/industry corpus) deferred.

---

## Loop 5 — 2026-06-21 — P1-5 (eval depth) slice 2: deterministic faithfulness metric

**Spec Kit:** `specs/012-eval-quality-depth/` created (spec + checklist; US1 precision/MRR done, US2 faithfulness this slice, US3 golden corpus pending). `.specify/feature.json` → 012.

**実装した変更 (isolated in eval/):** `src/raku_rag/eval/runner.py` adds a deterministic **`faithfulness`** metric = mean over `ok` answers of (answer content-terms supported by the used-evidence text) / (answer content-terms), via a pure `_term_support()` helper reusing `core.text.content_terms`. **Additive** — `groundedness` and all existing metrics/gates unchanged (not gated yet; thresholding waits on the golden corpus, US3). Stronger than the old structural groundedness proxy: it discriminates a plausibly-worded *unsupported* answer (catches a real LLM's fabrication later).

**実行したテスト:** `tests/unit/test_eval_metrics.py` (NEW, 4) pins SC-002 discrimination (full→1.0, partial→<1.0, none/empty→0.0); `test_eval` asserts `faithfulness==1.0` for the extractive (faithful-by-construction) path. eval/baseline/visual-eval green. `scripts/gate.sh a` GREEN (313); `scripts/gate.sh all` GREEN (**625**, skipped 6); `scripts/gate.sh separation` OK; ruff/black/mypy clean.

**次のループ:** P1-5 **US3 golden corpus** — materialize `tests/fixtures/uat/` per-industry + commit a real `baseline.json` (replace self-derived `baseline_from_run`) + a seeded-regression gate test (the higher-value, data-heavy piece; makes precision/MRR/faithfulness meaningful as regression detectors). Bigger P1s (P1-1/2/8) still blocked by the concurrent actor's in-flight edits to `server.py`/`answer.py`/`retrieval.py`. Nothing committed.

---

## Loop 4 — 2026-06-21 — P1-5 (eval depth) slice 1: precision@k + MRR; GAP-S3 filed

**実装した変更 (isolated in eval/ — no concurrent-actor overlap):** `src/raku_rag/eval/runner.py` now computes **`precision_at_k`** and **`mrr`** alongside `recall_at_k` (graded over items with expected evidence; ranked/deduped retrieved docs). Additive — not yet baseline-gated (thresholding waits on the golden corpus). Test: `tests/integration/test_eval.py` asserts both == 1.0 on the fixture.

**Also:** filed **GAP-S3** (the PR-016 source-poisoning vuln) in `specs/002-.../tasks.md §Gap Remediation Backlog → Safety boundary (reproduced)`, per your "just file it, you fix". The safety-path change + its hard-gate test remain yours; once it lands, add `source_poisoning_probe` to `DEFAULT_PROBES` + `SECURITY_CHECKS`.

**実行したテスト:** eval/baseline/manufacturing-eval/hard-gate 9 OK; `scripts/gate.sh a` GREEN (313); `scripts/gate.sh all` GREEN (621, skipped 6); `scripts/gate.sh separation` OK; ruff/black/mypy clean.

**次のループ (remaining P1-5 + constraints):** (a) **faithfulness metric** (entailment/claim-support, deterministic CI fallback) — a *metric-design* decision → spec it; (b) **golden corpus** materialization (`tests/fixtures/uat/`) + committed baseline (replaces self-derived `baseline_from_run`). Other high P1s are **blocked by the concurrent actor** right now: P1-1 (`server.py`), P1-2 (`services/answer.py`), P1-8 (`services/retrieval.py`) — revisit once its changeset settles/commits. Isolated alternatives if preferred: P1-13 (secret-scanning CI, `.github/`), P1-12 migration-smoke fix (`ci.yml`).

---

## Loop 3 — 2026-06-21 — P0-1 implemented (4 probes default-on) + reproduced a real safety vuln

**実行日時:** 2026-06-21. **Goal:** implement P0-1 (eval security probes) per the approved design D1–D3.

**実装した変更 (src — isolated from the concurrent actor's files):**
- `src/raku_rag/eval/probes.py` (NEW): `SecurityProbe`/`ProbeResult`/`SuiteOutcome`/`SecurityProbeSuite` + 5 probes (acl_leakage, deleted_reappearance, tenant_isolation, prompt_injection, source_poisoning). Each builds its own ephemeral harness (D1), positive control mandatory, fail-closed (D3).
- `src/raku_rag/eval/runner.py`: runner runs the suite by default and computes the gate signal; caller counts merged by **max** (D2); `probes_executed==False` ⇒ blocked; added `prompt_injection` to `SECURITY_CHECKS`.
- `src/raku_rag/eval/models.py`: additive `probe_results` + `probes_executed` on `EvaluationRun` (+ `to_dict`).
- `src/raku_rag/eval/__init__.py`: export probe API.
- `tests/security/test_eval_security_probes.py` (NEW hard-gate test, 10 tests): clean→0+executed; leaky→blocked; deny→unavailable (SC-003); runner leak-blocks w/o caller counts; merge-by-max preserves caller force-block; source_poisoning via stubs (poison→blocked, clean→ok, deny→unavailable).

**実行したテスト (verified):** new probe tests 10 OK; must-not-regress eval consumers 11 OK; `scripts/gate.sh a` **GREEN (313)**; `scripts/gate.sh all` **GREEN (621, skipped 6, ~0.9s)**; `scripts/gate.sh separation` **OK**; ruff/black/mypy clean on my files. `test_eval_hard_gate.py` unmodified and still green (merge-by-max).

**🔴 NEW FINDING — reproduced safety vulnerability (PR-016 / candidate GAP-S3):** the `source_poisoning` probe, run against the real `ManufacturingSystem`, found a high-risk answer citing a **DRAFT poison doc as `citations[0]`** and asserting its dangerous content when an approved doc coexists (violates FR-MFG-005/006, SC-MFG-006/011). **Held `source_poisoning_probe` OUT of the default suite + `SECURITY_CHECKS`** (enabling it would correctly block every release until fixed) — it stays implemented + stub-tested. NOT a reward-hack: it was never computed before; 4 real probes added; the 5th's finding documented, not hidden.

**/goal status:** 4/5 probes default-on and authoritative; planted-leak→blocked ✓; no-op→unavailable ✓; caller {name:1}→blocked (protected test green) ✓; probes_executed provenance ✓; gate sub-second ✓. **source_poisoning gated on the human-owned safety fix (PR-016).**

**human review が必要 (safety boundary):** the PR-016 fix is a safety-path change (demote draft from primary for high-risk) + its own hard-gate test = **always-human (§0/§6)**. Awaiting direction: (a) fix now under review, or (b) you fix; then enable source_poisoning as a blocker.

**次のループ:** on PR-016 resolution → enable source_poisoning (default-on). Then Phase C anti-regression CI assertion is already largely satisfied (probes_executed provenance + `test_default_runner_runs_probes_and_passes_clean`); optionally add it to `tests/unit/test_ci_eval_gate.py`. Nothing committed (concurrent actor active).

---

## Loop 2 — 2026-06-21 — P0-1 Spec + Plan (gate design for review)

**実行日時:** 2026-06-21. **Target (human-approved):** P0-1 — eval security & injection probes.

**作成した Spec Kit artifact:**
- `specs/011-eval-security-probes/spec.md` (+ `checklists/requirements.md`) — validated, no `[NEEDS CLARIFICATION]`, single pass.
- `specs/011-eval-security-probes/plan.md` — Constitution Check **PASS** (no violations; serves Principles V + III).
- `research.md` (decisions D1–D7), `data-model.md` (SecurityProbe/ProbeResult/Suite + runner contract), `contracts/probe-interface.md` (gate semantics), `quickstart.md` (S1–S6 validation).
- `.specify/feature.json` → repointed to `specs/011-eval-security-probes`.

**調査したファイル:** `eval/runner.py` (the no-op `_security_checks`, line 293-298), `eval/models.py`, `eval/baseline.py`, `dagster/jobs/evaluation.py`, `apps/answer-service/server.py:503-535` (`_EvalFeedbackStore` builds runner w/o counts against a Postgres `ProductionSystem`), `tests/security/test_eval_hard_gate.py` (protected), `tests/helpers.py`, `.specify/memory/constitution.md`.

**実装した変更:** none (spec/plan only — zero `src/`, zero test/gate edits).

**実行したテスト:** `scripts/gate.sh a` + `scripts/gate.sh separation` (additive docs/specs only — see verification below).

**human review が必要な判断 (gate design — always human, §0/§6):**
- **D1 probe-target:** probe a *dedicated ephemeral harness* (in-memory `MvpSystem`/`ManufacturingSystem`) vs the live `ProductionSystem` (would pollute the Postgres store). Recommended: harness.
- **D2 merge semantics:** effective count = `max(probe_count, caller_count)` — keeps the protected test unmodified while making probes authoritative. Recommended.
- **D3 fail-closed:** a probe that can't run ⇒ `unavailable` ⇒ `blocked` (never silent pass). Recommended.

**次のループ (after design approval):** `speckit-tasks` → implement **Phase A (US1: ACL/deletion/tenant probes + merge-by-max + provenance)** TDD, run `gate.sh a` + targeted eval + `gate.sh separation`, present the gate diff for review, record. Then Phase B (injection/poisoning) and Phase C (wire prod callers + anti-regression CI).

---

## Loop 1 — 2026-06-21 — Audit & baseline

**実行日時 (when):** 2026-06-21, branch `002-manufacturing-field-knowledge-rag`.

**調査したファイル (investigated):**
- Orientation: `CLAUDE.md`, `docs/loop-engineering.md` (720 lines, through Step 5b-43), `README.md`, `scripts/gate.sh`, `.github/workflows/gate.yml` + `ci.yml`, root `risk-register.md`, `specs/002-.../tasks.md §Gap Remediation Backlog`.
- Multi-agent A–I sweep (10 agents, 334 tool calls) over `src/raku_rag/**`, `apps/**`, `workers/ingest/**`, `infra/**`, `tests/**`, `specs/**`, `docs/**`.

**実行したテスト (tests run):** `scripts/gate.sh a` → **GREEN, 313 tests / 0.474s** (independently re-run, not trusted from prior reports per `MEMORY.md`). Full suite reported ~607 tests green by the auditor.

**失敗したテスト (failing):** none. Gate is green — but green is **necessary, not sufficient** (see findings).

**見つけたギャップ (gaps found):** Full A–I audit + prioritized P0→P3 backlog in `rag-production-readiness.md`. Headline:
- **Deployment boundary** — the 002 safety/governance overlay (`ManufacturingSystem`, in-memory) is **not on the deployed path** (`apps/answer-service/server.py:1049-1053` → `ProductionSystem.answer`, 001 controls only). High-risk gate, no-train, mfg audit, prompt-injection defense, and the eval security gates therefore **don't fire for real traffic**.
- **P0-1 (only P0):** eval "security hard-gates" are a **no-op that always passes** (`eval/runner.py:293-298` reflects caller-supplied counts; prod callers never set them). No prompt-injection/poisoning eval at all → **false assurance** vs the named top risks.
- 15 × P1 (safety-overlay deploy, prompt-injection-in-flow, governance persistence, telemetry export, golden corpus + faithfulness, red-team/GAP-S1, hybrid retrieval, retrieval failure logging, prod DLQ, durable audit, rate-limit/WAF, deploy story, secret-scanning, citation→live-chunk, embedding-dim reconciliation). + 12 × P2/P3.

**作成/更新した Spec Kit artifact:** none yet (audit-only loop). Created `docs/production-readiness/{rag-production-readiness,loop-state,risk-register,eval-plan}.md`. No `src/` changes.

**実装した変更 (changes implemented):** docs only (4 production-readiness files). Zero `src/`, zero gate/test edits → §5 separation invariant trivially preserved.

**human review が必要な判断 (needs human review):**
1. **Which P0/P1 to spec first** — recommendation **P0-1**; competing framing is **P1-1** (deploy the safety overlay = "single biggest production gap"). Creating a new Spec Kit feature+branch is an L2 boundary → confirm before `speckit-specify`.
2. **P0-1 probe design is a gate-design change** (`loop-engineering.md §3`) — what the eval "No" *computes* must be human-reviewed so it can't be gamed.
3. Any item tagged **[!safety]** (P1-1/3/6/10, P2-1, P3-1) keeps its gate decision / approval / no-train / audit-suppression semantics **human-owned**.

**次のループでやるべきこと (next loop):**
- On approval of the first target: run `speckit-specify` (or extend `specs/002`) → `speckit-plan` → `speckit-tasks`, then implement→verify→record the first small slice. Keep Tier A green and the verification/generation separation intact.
- If P0-1: add real ACL/deletion/tenant probe functions to `eval/runner`, a poisoned-context + prompt-injection fixture, wire `answer-service` + dagster callers, and a CI assertion that probe counts are actually computed — as an **independently-reviewed gate change** separate from any src refactor.
