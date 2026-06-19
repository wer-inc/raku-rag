# Open Decisions

> **Phase 0/1 decision pass (2026-06-19):** OD-003, OD-008, and OD-001 were reviewed for items
> that block roadmap Phase 0 (local-first foundation) / Phase 1 (001 production-adapter MVP).
> Their Phase 0/1-relevant scope is now LOCKED under ADR-015. OD-002/004/005/006/007/009/010 are
> unchanged and remain deferred to their stated decision points. See each block's **Status** line.

## OD-001: Scope of Runtime DB-Managed IndustryProfile

Decision needed: Which profile elements are tenant-editable at runtime.
Default recommendation: Keep baseline profile, schema, workflow, and hard safety policy in seed/code; allow tenant enablement, display names, reviewer groups, templates, KPI targets, and thresholds in DB.
Alternatives: fully code-only, fully DB-managed.
Impact: More DB flexibility increases governance and migration burden.
When to decide: Before Phase 2 implementation.
Owner: Framework lead.

Status: Phase 0/1 scope LOCKED (2026-06-19, ADR-015); full decision DEFERRED to Phase 2.
Phase 0/1 resolution: IndustryProfile runtime editing is OUT OF SCOPE for Phase 0/1. 010 profiles
are treated as seed data / read-only DB config. To keep runtime editing addable later without a
breaking migration, the profile/policy schema MUST carry `profile_version`, `schema_version`,
`effective_from`, and `deprecated_at` from the start. The full set of tenant-editable runtime
elements (the Default recommendation above) is decided before Phase 2 (refines ADR-014).
Phase 2 follow-up (deferred): 010 data-model.md currently gives IndustryProfile / MetadataSchema /
policies only a bare `version`; before the Phase 2 010 build, add the four lifecycle fields there too
(010 ISF-001). 001 Phase 0/1 does NOT create 010 IndustryProfile — the four fields land on the seeded
001 policy/config entities (ProviderPolicy / RetrievalProfile / LoggingPolicy / QueryProfile) per
data-model.md "Phase 0/1 Lock Schema Additions".

## OD-002: Ratio of Generic APIs to Domain APIs

Decision needed: How much workflow execution should use `/industries/...` vs domain endpoints.
Default recommendation: Use generic APIs internally and expose domain APIs for user/operator-facing workflows.
Alternatives: generic-only, domain-only.
Impact: Generic-only reduces code but hurts usability; domain-only fragments contracts.
When to decide: Before Phase 2 and each vertical slice.
Owner: API lead.

## OD-003: JSONB vs Normalized Tables Boundary

Decision needed: Which industry fields are normalized vs kept in JSONB.
Default recommendation: Normalize entities used by workflow, ACL, review, and dashboard; keep sparse document metadata in JSONB with indexed hot fields.
Alternatives: JSONB-only, full normalization.
Impact: Affects migrations, query performance, and customer customization.
When to decide: During Phase 1/2 schema design.
Owner: Data lead.

Status: Phase 0/1 boundary LOCKED (2026-06-19, ADR-015; substance in ADR-011); per-industry full
normalization DEFERRED to the vertical slices (Phase 3–5).
Phase 0/1 resolution: 001 core entities are NORMALIZED tables (per data-model.md): Tenant,
Collection, DataSource, Document, Chunk, Citation, AuditLog, CostRecord, ProviderPolicy,
RetrievalProfile, LoggingPolicy, IngestionJob/IngestionRun, DocumentProcessingState (plus
SourceSyncState/SourceDocumentManifest and the visual entities). Embedding stays canonical on
Chunk/LayoutRegion (not a separate entity). Industry-specific document/chunk metadata is JSONB +
`schema_version` (ADR-011). Frequently filtered industry fields (equipment_id, property_id,
unit_id, fund_id, document_type, approval_status, effective_date) are promotable to hot fields via
generated column / expression index / materialized projection. Full per-industry normalization is
NOT done in Phase 0/1.

## OD-004: OpenSearch Introduction Trigger

Decision needed: When to add OpenSearch for Japanese hybrid search.
Default recommendation: Start with Aurora pgvector and benchmark; add OpenSearch only if recall/code lookup/latency targets fail.
Alternatives: OpenSearch from day one, never OpenSearch.
Impact: Adds operational cost and complexity.
When to decide: After Phase 6 retrieval benchmark.
Owner: Search lead.

## OD-005: Dagster Introduction Trigger

Decision needed: When to introduce Dagster operationally.
Default recommendation: Add Dagster when backfill/reindex/model migration/evaluation/KPI materialization creates operational pain beyond SQS worker.
Alternatives: Dagster from day one, SQS only indefinitely.
Impact: Adds control plane complexity but improves lineage and retry orchestration.
When to decide: After Phase 1 MVP and before large-scale ingestion.
Owner: Platform lead.

## OD-006: Parser/OCR Provider Selection

Decision needed: Azure DI, Google DI, Textract, OSS, or customer-managed default per tenant profile.
Default recommendation: AWS-only/customer-managed default; Azure/Google/Textract as opt-in providers after PoC quality and residency review.
Alternatives: Pick one global provider, customer-specific provider only.
Impact: Affects OCR/table quality, data residency, and sales/security review.
When to decide: During Phase 6 parser PoC.
Owner: Ingestion lead.

## OD-007: Frontend Hosting

Decision needed: Vercel hosting vs AWS-hosted Next.js.
Default recommendation: Use Vercel AI SDK as a library option, but choose hosting per residency requirement. AWS-hosted fallback is required.
Alternatives: Vercel-only, AWS-only.
Impact: Affects residency, telemetry, ops, and delivery speed.
When to decide: Before Phase 7 staging.
Owner: Product/Infra lead.

## OD-008: Langfuse Trace Granularity

Decision needed: Which traces store raw/redacted model input/output.
Default recommendation: Store IDs, versions, model metadata, latency, and cost by default. Store redacted content only by tenant policy and sampling.
Alternatives: no content ever, full content with redaction.
Impact: Affects debugging, privacy, and audit obligations.
When to decide: Before Phase 1 observability implementation.
Owner: Security/Observability lead.

Status: RESOLVED (2026-06-19, ADR-015; substance in ADR-010). 001 Phase 1 observability decision,
fully locked.
Resolution: Langfuse traces store request_id/trace_id, tenant_id, prompt_template_version, model,
provider, latency, token usage, cost, citation_ids, document_ids, chunk_ids, risk decision
metadata, and groundedness result by default. Raw retrieved context is NOT stored by default.
user query / answer are stored only after redaction. Raw prompt / raw context storage is allowed
only on local/dev or with explicit tenant-admin opt-in. Production behavior follows LoggingPolicy
per tenant (sampling / redaction / retention). Enforced by LoggingPolicy (data-model.md) and
LoggingPolicyEnforcer (tasks T098/T099).

## OD-009: 006 Customer-Facing Draft Scope

Decision needed: How far 006 allows customer-facing draft generation.
Default recommendation: Allow only internal drafts for review, never direct customer delivery or final approval.
Alternatives: internal-only with no customer-facing phrasing, broader drafts with compliance workflow.
Impact: Affects regulated activity, compliance review load, and product positioning.
When to decide: Before Phase 5.
Owner: Investment product/compliance lead.

## OD-010: 003 Legal Review Scope

Decision needed: Whether 003 includes explicit legal-review routing or only review_required flags.
Default recommendation: MVP has review_required flags and reviewer_group assignment; legal review routing is customer config or future workflow.
Alternatives: no legal routing, full legal review workflow.
Impact: Affects PM workflow complexity and legal/compliance expectations.
When to decide: Before Phase 4.
Owner: Real estate product lead.
