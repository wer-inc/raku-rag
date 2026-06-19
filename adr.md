# Architecture Decision Records

## ADR-001: Separate 001, 010, and Industry Solution Layers

Status: Accepted

Decision: Keep 001 as the base RAG platform, 010 as the industry solution framework, and 002/003/006 as industry solution layers.

Rationale: This preserves the generic RAG engine while allowing industry metadata, risk policy, workflow, draft artifacts, KPI, and dashboards to vary independently.

Consequences: New industries should add profiles and solution specs, not modify 001 core responsibilities.

## ADR-002: Use NestJS + Python Worker + SQS as MVP Default

Status: Accepted

Decision: Use NestJS for synchronous API and admin surfaces, Python workers for parser/OCR/embedding/evaluation jobs, and SQS + DLQ as the MVP queue.

Rationale: NestJS fits API contracts and B2B admin workflows. Python is stronger for document processing and evaluation. SQS is operationally simple on AWS.

Consequences: Shared contracts must be explicit between TypeScript and Python.

## ADR-003: Keep Dagster Future-Compatible, Not MVP-Mandatory

Status: Accepted

Decision: Keep SourceSyncState, SourceDocumentManifest, DocumentProcessingState, IngestionRun, AssetMaterializationRef, and ReindexPlan compatible with Dagster, but use SQS worker as MVP default.

Rationale: SQS is smaller for MVP. Dagster becomes valuable for backfill, reindex, lineage, quality checks, evaluation, and KPI materialization.

Consequences: Do not put Dagster in the online search/answer path.

## ADR-004: Use Aurora PostgreSQL + pgvector + RLS Initially

Status: Accepted

Decision: Use Aurora PostgreSQL with pgvector and RLS as initial metadata, app state, and vector store.

Rationale: It keeps tenant isolation, metadata filters, approval state, audit, cost, and vector search in one operational boundary for MVP.

Consequences: Query plans, partitioning, HNSW/IVFFlat indexes, and RLS tenant context must be tested early.

## ADR-005: Initial Retrieval Uses Metadata/Identifier + Vector + Rerank

Status: Accepted

Decision: Do not use vector-only retrieval. Use metadata exact filters, normalized identifier/code match, pgvector semantic search, and bounded rerank.

Rationale: Manufacturing IDs, property/unit IDs, contract IDs, fund codes, ISINs, and other identifiers are not reliably solved by embeddings alone.

Consequences: RetrievalProfile is a core config object and benchmark dimension.

## ADR-006: Do Not Use LangChain in the Critical Path

Status: Accepted

Decision: Keep retrieval, answer, citation, groundedness, risk gate, audit, and cost orchestration in explicit services.

Rationale: This product relies on strict ACL, evidence, audit, and policy boundaries that should not be hidden behind a broad chaining framework.

Consequences: Thin provider adapters are acceptable, but business-critical orchestration remains first-party.

## ADR-007: Start with Bedrock Claude, Cohere Embed, and Cohere Rerank

Status: Accepted

Decision: Use Bedrock Claude Sonnet/Haiku, Cohere Embed Multilingual v3, and Cohere Rerank as initial candidates.

Rationale: This supports AWS-first B2B governance and Japanese/multilingual RAG evaluation.

Consequences: Chunking must respect embedding limits, and model choice remains versioned through ProviderPolicy and EmbeddingJob.

## ADR-008: Parser/OCR Providers Are Controlled by ProviderPolicy

Status: Accepted

Decision: Azure Document Intelligence, Google Document AI, Textract, OSS, and customer-managed parsers are selected per tenant/collection through ProviderPolicy.

Rationale: OCR/table accuracy and data residency requirements vary by customer.

Consequences: External cloud parsing requires explicit opt-in, provider region, no-train/zero-retention capability, and audit.

## ADR-009: Guardrails Are Defense-in-Depth Only

Status: Accepted

Decision: Bedrock Guardrails and similar model filters are supplemental controls, not replacements for ACL, tenant isolation, RequiredEvidencePolicy, GroundednessGate, RiskGate, or review workflows.

Rationale: Business and data security controls must be deterministic and auditable.

Consequences: Tests must prove guardrails cannot bypass primary controls.

## ADR-010: Use Langfuse Self-Host with Redacted/Sampled Logging

Status: Accepted

Decision: Self-host Langfuse, but raw retrieved context is not stored by default. LoggingPolicy controls query/context/input/output storage, redaction, sampling, and retention.

Rationale: Observability is needed, but RAG context contains customer secrets and personal data.

Consequences: Store citation IDs, chunk IDs, prompt template versions, model metadata, latency, and cost by default.

## ADR-011: Store Industry Metadata as JSONB with Schema Validation and Indexed Hot Fields

Status: Accepted

Decision: Store flexible industry metadata as JSONB, validate through MetadataSchema, and index frequently filtered fields.

Rationale: Industry schemas differ and evolve, but retrieval and ACL filters need performance.

Consequences: MetadataSchema.indexed_fields drives generated indexes or expression indexes.

## ADR-012: Use Common DraftArtifact with Industry-Specific Payloads

Status: Accepted

Decision: Store DraftArtifact common lifecycle and audit fields in a shared model, with industry-specific payload JSON validated by DraftArtifactTypeDefinition.

Rationale: Review, audit, and no-auto-approval are common, while output structures differ by industry.

Consequences: AI-generated artifacts always start in draft and cannot auto-approve.

## ADR-013: Use Local-First Development with Deterministic Mocks

Status: Accepted

Decision: Core logic must run locally with Postgres/pgvector, MinIO, LocalStack SQS, mock LLM/embedding/rerank/auth/guardrail, and parser/eval fixtures.

Rationale: Security and policy behavior should be testable without cloud dependencies.

Consequences: Model/OCR quality is validated in staging, but policy gates run in CI locally.

## ADR-014: Use Hybrid Profile Management

Status: Accepted

Decision: Baseline industry profiles are code/seed data; tenant-specific enablement, overrides, thresholds, templates, and KPI targets are DB-managed config.

Rationale: Profiles need reproducibility and customer-level adjustability.

Consequences: Profile changes are versioned and audited.

## ADR-015: Lock Phase 0/1 Scope for JSONB Boundary, Trace Granularity, and Profile Runtime

Status: Accepted (2026-06-19)

Decision: For roadmap Phase 0 (local-first foundation) and Phase 1 (001 production-adapter MVP), the Phase 0/1-relevant scope of three open decisions is locked:

- OD-003 (JSONB vs normalized boundary): 001 core entities are normalized; industry metadata is JSONB + `schema_version` with hot fields promotable via generated column / expression index / materialized projection; full per-industry normalization is deferred to the vertical slices (Phase 3–5). Refines ADR-011.
- OD-008 (Langfuse trace granularity): IDs, versions, model metadata, latency, cost, citation/document/chunk IDs, risk decision metadata, and groundedness result are stored by default; raw retrieved context is never stored by default; user query/answer are redacted; raw prompt/context storage requires local/dev or tenant-admin opt-in; production follows LoggingPolicy. Refines ADR-010. This decision is fully resolved (no Phase 2 remainder).
- OD-001 (runtime DB-managed IndustryProfile): no runtime profile editing in Phase 0/1; 010 profiles are seed / read-only config; the schema carries `profile_version`, `schema_version`, `effective_from`, and `deprecated_at`; the full runtime-editing element set is decided before Phase 2. Refines ADR-014.

Rationale: Phase 0/1 must focus on the 001 local-first foundation and production-adapter MVP. These locks remove the schema, logging, and config ambiguity that would otherwise block Phase 0/1, while deferring the broader industry-config and per-industry normalization questions to Phase 2+.

Consequences: Phase 2 (010 framework) carries the OD-001 remainder and the Phase-2 (010 / MetadataSchema) portion of OD-003; per-industry full normalization is deferred to Phase 3–5. Phase 0/1 migrations must add `schema_version` to JSONB metadata and the profile version/lifecycle fields (`profile_version`/`schema_version`/`effective_from`/`deprecated_at` on ProviderPolicy/RetrievalProfile/LoggingPolicy/QueryProfile) even though runtime editing is not yet built.
