# Manufacturing Field Knowledge RAG — Architecture

The 002 manufacturing feature is a **solution layer built on top of** the 001 generic RAG platform
(`src/raku_rag/`). It does **not** re-implement multi-tenancy, ACL, ingestion, retrieval, groundedness,
answer assembly, deletion/tombstone, or the audit base — it **reuses** them and **overlays** the
manufacturing-specific rules (safety gating, approval metadata, drafts, trouble cases, governance,
telemetry/KPI).

The whole package lives under `src/raku_rag/manufacturing/`.

## Design principle: extend / overlay, never redefine 001

Every module in the package carries the same discipline in its docstring: it wraps a reused 001
service and adds a thin, additive overlay. Concretely:

- **Tenancy** — reuses `raku_rag.core.tenancy.enforce_same_tenant`. The manufacturing layer never
  invents a tenant check; cross-tenant reads raise `TenantIsolationError`.
- **ACL** — reuses `raku_rag.core.security.acl.AclPolicy` (deny-by-default). The manufacturing
  `ManufacturingScope` is *translated* into 001 `ACLGrant` records (see `domain/acl_mapping.py`); the
  visibility decision is still 001's.
- **Retrieval / groundedness / answer** — reuses `raku_rag.services.retrieval.RetrievalService`,
  `raku_rag.services.groundedness.GroundednessGate`, `raku_rag.services.answer.AnswerService`. The
  manufacturing answer overlay orchestrates these and layers the safety gate on the result.
- **Ingestion** — reuses `raku_rag.services.ingestion.IngestionService`, swapping in a
  `CompositeParser` so DOCX/XLSX/CSV are accepted behind the same 001 `Parser` abstraction.
- **Deletion** — reuses `raku_rag.services.*` tombstone/cascade via `self._mvp.deletion`.
- **Audit** — extends the 001 audit base (Base CR-001-A) into `domain/audit.py` (reference-IDs-only,
  001 `Redactor` reused, SHA-256 hash chain).

Because the answer/search overlays consult the **same** 001 `RetrievalService` (which applies the ACL
pre-filter inside `InMemoryVectorStore.search`), every manufacturing endpoint inherits the
deny-by-default boundary for free — there is no parallel authorization path.

## Package layout (`src/raku_rag/manufacturing/`)

| Subpackage | Module(s) | Responsibility |
|------------|-----------|----------------|
| `domain/` | `metadata.py` | `ManufacturingDocumentMetadata` + enums (`DocumentKind`, `ApprovalStatus`, `ApprovalSource`) stored in 001 `Document.metadata` / `Chunk.metadata`. |
| `domain/` | `safety.py` | Frozen value objects `HighRiskClassification`, `SafetyDecision`, `SafetyBlockReason`, `ClassificationSource`. |
| `domain/` | `draft.py` | `DraftArtifact` + `DraftType` / `DraftStatus` / `CreatedBy` enums. |
| `domain/` | `audit.py` | `AuditLogEntry`, `InMemoryAuditLogWriter` (redaction + hash chain), `SafetyTelemetryResult`, org-context snapshot helpers. |
| `domain/` | `acl_mapping.py` | `ManufacturingScope` → 001 `ACLGrant` translation + `apply_scope` enforcement seam + denial-audit helpers. |
| `domain/` | `policy.py` | `DataUsePolicy`, `RetentionConfig`, `NoTrainFallback`. |
| `domain/` | `entities.py` | `Factory`, `Process`, `Equipment`, `TroubleCase`, `FailureMode`, `Countermeasure`, `TroubleCaseResult`, and the `MeasureClass` / `CountermeasureType` axes. |
| `safety/` | `classifier.py` | `RuleHighRiskClassifier` — 3-stage cascade (metadata / keyword / LLM tie-break), fail-safe to high-risk. |
| `safety/` | `gate.py` | `ManufacturingSafetyGate` — the approved+effective-citation requirement, obsolete/draft handling, block-reason normalization. |
| `ingestion/` | `metadata_enrichment.py` | `MetadataEnricher` — attach metadata to the 001 Document + propagate to chunks (`MFG_META_KEY = "_mfg_meta"`). |
| `ingestion/` | `approval.py` | `ApprovalWorkflow` — lightweight transition workflow + imported-approval-as-source-of-truth. |
| `knowledge/` | `trouble_cases.py` | `InMemoryTroubleCaseStore` + `TroubleCaseRetriever` + 2-axis countermeasure normalization (Hard Rule 4). |
| `drafts/` | `generator.py` | `DraftGenerator` — always `status=draft`, `created_by=ai`. |
| `drafts/` | `review.py` | `ReviewWorkflow` — only a human reviewer reaches `approved`. |
| `governance/` | `no_train.py` | `InMemoryDataUsePolicyStore` + `InMemoryNoTrainGuard` (opt-in enforcement, GQ1 capability block). |
| `governance/` | `retention.py` | `InMemoryRetentionManager` — effective retention (365/365) delegating expiry to the 001 tombstone. |
| `telemetry/` | `safety_metrics.py` | `SafetyTelemetry` — audit-derived high-risk / block counts, mutually-exclusive breakdown. |
| `kpi/` | `poc_metrics.py` | FR-MFG-028 KPI report (json/csv export), reusing the same safety counters. |
| `api/` | `answer_ext.py`, `search_ext.py`, `drafts.py`, `trouble.py`, `dashboard.py`, `policy.py`, `audit.py` | Overlay service surfaces + audit recording. |
| `interfaces.py` | — | The ABC contracts the concrete classes structurally satisfy. |
| `app.py` | `ManufacturingSystem` | The composition root. |

## Composition root: `ManufacturingSystem` (`app.py`)

`ManufacturingSystem` is the stage-2 analog of `raku_rag.app.MvpSystem`. It **wraps** an `MvpSystem`
(`self._mvp`) and assembles the overlay around it. Key wiring in `__init__`:

- `self._mvp = MvpSystem(settings)` — the reused 001 system (store, embedder, chunker, registry, ACL,
  retrieval, groundedness gate, answer service, deletion, profiles, LLM).
- `self.audit = InMemoryAuditLogWriter()` — the single shared audit log (source of truth for
  telemetry/KPI).
- `self._parser = CompositeParser([TextParser(), DocxParser(), SpreadsheetParser()])` and a dedicated
  `IngestionService` so OOXML types are accepted (001's `TextParser` alone rejects them).
- `self._enricher = MetadataEnricher(...)`, `self._approval = ApprovalWorkflow(...)`.
- `classifier = RuleHighRiskClassifier(llm=self._mvp.llm)`, `safety_gate = ManufacturingSafetyGate(today=...)`,
  composed into `self._answer = ManufacturingAnswerService(...)`.
- `self._search`, `self._drafts`, `self._trouble_cases` / `self._trouble_retriever` / `self._trouble_search`,
  `self._dashboard`, plus the governance overlay `self._policy_store` / `self.no_train` /
  `self.retention` / `self._governance`.

### Entrypoints (the public method surface)

- **Admin / ACL**: `grant(...)` (delegates to 001), `grant_scope(scope: ManufacturingScope)`
  (delegates to `acl_mapping.apply_scope` on `self._mvp.acl`).
- **Ingestion**: `ingest_manufacturing(...)` (001 text path + metadata attach),
  `ingest_manufacturing_file(...)` (DOCX/XLSX/CSV/text via the CompositeParser),
  `update_metadata(...)`.
- **Approval**: `transition_approval(...)`, `import_external_approval(...)`.
- **Answer / search**: `answer(...) -> ManufacturingAnswer`, `search(...)`.
- **Drafts (US4)**: `generate_draft(...)`, `get_draft(...)`, `assign_reviewer(...)`, `review_draft(...)`.
- **Trouble cases (US3)**: `register_trouble_case(...)`, `search_trouble_cases(...)`.
- **Governance (US7)**: `use_for_training(...)`, `capability_status(...)`,
  `resolve_capability_provider(...)`, `get_data_use_policy(...)`, `update_data_use_policy(...)`,
  `governance_status(...)`, `export_audit(...)`, `delete_document(...)`.
- **Knowledge-ops / telemetry / KPI (US5)**: `knowledge_ops_dashboard(...)`, `safety_telemetry(...)`,
  `kpi(...)`.

The production entrypoint (NestJS API / pgvector / SQS worker) would assemble the **same overlay**
behind those adapters; the in-memory `ManufacturingSystem` is the reference composition the tests
drive directly.

## Where the rules live (cross-reference)

- Safety gating + high-risk classification → `docs/manufacturing/safety-and-drafts.md`
- DOCX/XLSX/CSV parsing + cell anchors + approval metadata → `docs/manufacturing/ingestion.md`
- No-train / retention / audit / governance APIs → `docs/manufacturing/governance.md`
- The 6 absolute hard gates and how `scripts/gate.sh` enforces them → `docs/manufacturing/hard-gates.md`
