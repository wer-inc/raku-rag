# Implementation Roadmap

## Phase 0/1 Decision Locks

Locked 2026-06-19 (ADR-015; OD-001 / OD-003 / OD-008):

- **Schema (OD-003):** 001 core entities are normalized; industry metadata is JSONB + `schema_version`; hot fields are promotable (generated column / expression index / materialized projection); per-industry normalization is deferred to Phase 3–5.
- **Observability (OD-008, resolved):** Langfuse stores IDs / versions / model metadata / latency / cost / citation+document+chunk IDs / risk decision metadata / groundedness by default; raw retrieved context is never stored by default; query/answer redacted; raw storage only via local/dev or tenant opt-in (LoggingPolicy).
- **IndustryProfile (OD-001):** no runtime profile editing in Phase 0/1; 010 profiles are seed / read-only config; schema carries `profile_version` / `schema_version` / `effective_from` / `deprecated_at`; runtime-editing scope is decided before Phase 2.

Phase 2 carries the OD-001 remainder and the Phase-2 (010 / MetadataSchema) portion of OD-003; per-industry full normalization is deferred to Phase 3–5.

## Phase 0: Local-First Foundation

Goals:

- local docker compose
- NestJS skeleton
- Python worker skeleton
- PostgreSQL + pgvector
- MinIO
- LocalStack SQS
- mock providers
- migrations
- seed data

Exit criteria:

- Local API, worker, database, object storage, and queue boot successfully.
- Deterministic mocks can run ingestion/search/answer contract tests.

## Phase 1: 001 Production Adapter MVP

Scope:

- tenant isolation and RLS
- ACL pre-filter
- ingestion job and SQS worker
- document, chunk, embedding, citation, audit, cost models
- metadata exact filter, identifier/code match, vector search, rerank interface
- answer with citation and insufficient evidence
- tombstone and cache invalidation
- no-train ProviderPolicy, RetrievalProfile, LoggingPolicy

Exit criteria:

- Cross-tenant leakage = 0.
- ACL leakage = 0.
- Deleted documents not searchable.
- Raw retrieved context not stored by default.
- Local mocks and contract tests pass.

## Phase 2: 010 Industry Framework

Scope:

- IndustryProfile
- MetadataSchema and indexed hot fields
- RiskPolicy and RequiredEvidencePolicy
- WorkflowDefinition
- common DraftArtifact and DraftReviewPolicy
- KPIDefinition and DashboardWidgetDefinition
- GovernanceProfile and AuditEventDefinition
- regulated extensions for 006

Exit criteria:

- 002, 003, and 006 can be represented as profiles.
- AI-created DraftArtifact cannot auto-approve.
- RequiredEvidencePolicy blocks high-risk answers without approved/effective citations.

## Phase 3: 002 Manufacturing Vertical Slice

Scope:

- upload representative manufacturing docs
- metadata enrichment
- alarm/trouble Q&A
- safety/quality/equipment high-risk gate
- checklist/report/FAQ draft
- provisional/permanent countermeasure distinction
- dashboard/KPI

Exit criteria:

- Dangerous work requires approved safety citation.
- Obsolete/draft sources are not formal evidence.
- Manufacturing PoC KPI calculated.

## Phase 4: 003 Real Estate Vertical Slice

Scope:

- lease contract, repair history, inquiry docs
- property/unit/lease metadata
- contract question and repair investigation
- occupant reply draft and owner report draft
- move-out/restoration checklist draft
- personal data handling
- dashboard/KPI

Exit criteria:

- Contract/cost/restoration/legal risk fails closed without approved/effective citation.
- Occupant personal data does not leak to unauthorized contexts.
- Real estate PoC KPI calculated.

## Phase 5: 006 Investment Vertical Slice

Scope:

- fund question
- RFP/DDQ draft
- inquiry reply draft
- marketing material check
- monthly commentary draft
- compliance rule question
- DisclosureEvidence
- advice boundary and regulated activity gate
- compliance review state

Exit criteria:

- No investment advice, buy/sell recommendation, or suitability judgment is auto-produced.
- Regulated outputs require evidence and review.
- Investment PoC KPI calculated.

## Phase 6: Evaluation, Benchmark, and Hardening

Scope:

- parser/OCR PoC
- embedding/retrieval benchmark
- rerank benchmark
- risk gate evaluation
- security hard-gate evaluation
- performance and cost evaluation

Exit criteria:

- Recall@5/10, citation accuracy, spreadsheet cell citation accuracy, groundedness, insufficient evidence rejection, parser table accuracy, p95 latency, and query cost are measured.
- ACL leakage, tenant leakage, deleted searchable, raw context logging violation are zero.

## Phase 7: Staging AWS Deployment

Scope:

- ECS Fargate
- Aurora PostgreSQL + pgvector
- SQS/DLQ
- S3
- Bedrock
- Cognito/SAML/OIDC
- KMS and Secrets Manager
- Langfuse ECS
- CloudWatch/OpenTelemetry
- optional Dagster components

Exit criteria:

- AWS staging passes local contract tests plus provider integration tests.
- ProviderPolicy opt-in and residency controls are verified.
