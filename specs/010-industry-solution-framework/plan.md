# Implementation Plan: Industry Solution Framework

**Feature**: `010-industry-solution-framework`  
**Status**: Draft  
**Base dependency**: `001-rag-platform`  
**Solution dependencies**: `002-manufacturing-field-knowledge-rag`, `003-real-estate-property-management-rag`, `006-investment-management-mutual-fund-rag`

## Summary

010 is a solution-layer framework, not a new RAG platform. It provides a profile registry, schema/policy contracts, workflow dispatch contracts, DraftArtifact base model, KPI/dashboard definitions, and governance/audit extension points that run on top of 001.

001 remains responsible for tenant isolation, ACL pre-filter, ingestion, retrieval, answer, citation, groundedness, evaluation, cost, audit, visual RAG, provider abstraction, ProviderPolicy, RetrievalProfile, LoggingPolicy, and job processing state.

## Technical Context

- API/runtime: NestJS service modules in the same API surface as 001.
- Persistence: PostgreSQL tables for profile/policy definitions, JSONB for versioned schema payloads, indexed columns for frequently filtered common fields.
- Workers: no direct parser/indexing ownership. Ingestion/KPI materialization jobs use 001 worker state and may be triggered through SQS or optional Dagster control plane.
- Contracts: generic `/industries/...` APIs plus domain-friendly APIs owned by each solution spec.
- Security: all reads and workflow execution inherit 001 tenant isolation, ACL pre-filter, audit, redaction, no-train, and cost controls.

## Boundary with 001

010 MUST NOT define a vector store, parser, embedding model, LLM provider, authorization source of truth, tenant ACL source of truth, audit source of truth, or online answer path. It only contributes industry metadata/risk/workflow/draft/KPI configuration and validation around 001 services.

## Services

- `IndustryProfileService`: resolve active profile by tenant, collection, and industry.
- `MetadataSchemaService`: validate versioned industry metadata and identify indexable fields.
- `IndustryDocumentEnrichmentService`: apply metadata/schema validation after 001 parsing and before indexing.
- `IndustryRiskPolicyService`: evaluate RiskPolicy and optional classifier result.
- `RequiredEvidencePolicyService`: enforce approved/effective citation requirements using 001 citation and document metadata.
- `IndustryWorkflowService`: dispatch generic workflow definitions to 001 retrieval/answer/citation/audit/cost services.
- `DraftArtifactService`: manage common DraftArtifact lifecycle and industry-specific payload validation.
- `DraftReviewService`: enforce review policies and block automatic approval.
- `IndustryKPIService`: calculate common and industry-specific KPIs from audit/feedback/draft/evaluation sources.
- `IndustryDashboardService`: assemble widgets with ACL-filtered metrics.
- `IndustryGovernanceService`: expose no-train, audit, retention, provider governance, and regulated extension status.

## Data Model Strategy

Definitions are first-class rows with JSONB payloads and explicit version fields. Common lookup fields such as `tenant_id`, `industry_id`, `collection_id`, `document_id`, `approval_status`, `effective_date`, `no_train_policy_ref`, and `retention_policy_ref` are modeled consistently. Industry-specific metadata remains JSONB but can declare indexed fields for generated columns or expression indexes.

## API Strategy

Provide generic APIs for profile discovery, metadata validation, document enrichment, workflow execution, DraftArtifact review, dashboard, KPI, and governance. Solution specs may expose domain-friendly APIs that call the same services internally.

## Mapping Strategy

- 002 maps to a manufacturing IndustryProfile with safety/quality/equipment RiskPolicy and manufacturing draft/KPI definitions.
- 003 maps to a real estate property management IndustryProfile with property/lease/repair metadata and contract/legal/financial/personal-data RiskPolicy.
- 006 maps to an investment management IndustryProfile with financial/regulated extensions, AdviceBoundaryPolicy, DisclosureEvidencePolicy, ComplianceReviewPolicy, and RecordRetentionPolicy.

## Testing Strategy

- Schema validation tests for MetadataSchema versioning and invalid metadata rejection.
- RiskPolicy tests for high-risk classification, uncertain-case fail-safe, and RequiredEvidencePolicy behavior.
- DraftArtifact tests for no auto approval and allowed transitions.
- ACL tests ensuring profile metadata does not bypass 001 pre-filter.
- KPI/dashboard tests ensuring tenant isolation and role-based visibility.
- Compatibility tests mapping 002/003/006 into the same abstractions without changing industry semantics.

## Risks

- Over-abstraction can hide industry semantics. Mitigation: keep domain meanings in solution specs.
- JSONB-only metadata can degrade search. Mitigation: indexed field declarations and generated indexes.
- Generic workflow API can become unreadable. Mitigation: allow domain-friendly APIs in solution specs.
- Policy changes can break existing profiles. Mitigation: versioned policy/profile definitions and migration checks.

## Readiness Gates

- 001 responsibilities remain unchanged.
- 002/003/006 can be represented as IndustryProfiles.
- DraftArtifact cannot auto-approve.
- RequiredEvidencePolicy can block high-risk answers without approved/effective citations.
- No-train, audit, ACL, tenant isolation apply to all industries through 001.
