# Architecture Hardening

## Purpose

This document hardens the product architecture before implementation. It clarifies boundaries across `001-rag-platform`, `010-industry-solution-framework`, `002-manufacturing-field-knowledge-rag`, `003-real-estate-property-management-rag`, and `006-investment-management-mutual-fund-rag`.

## Layer Responsibilities

### 001 Base RAG Platform

001 owns the RAG engine and production safety controls:

- tenant isolation and tenant_id as the hard boundary
- authentication integration, signed user claims, ACL pre-filter, RLS context
- ingestion state, document/chunk/citation/embedding lifecycle, tombstone and cache invalidation
- parser, OCR, layout, embedding, rerank, LLM, VLM, vector store, and task queue abstractions
- retrieval, answer generation, groundedness, insufficient evidence behavior, citation, cost, audit, evaluation
- ProviderPolicy, RetrievalProfile, LoggingPolicy, no-train provider configuration
- SQS worker as MVP default, optional Dagster-compatible control plane state

001 must not contain industry semantics such as equipment safety, lease restoration, or investment advice boundary rules.

### 010 Industry Solution Framework

010 owns the reusable solution-layer contract:

- IndustryProfile registry and compatibility rules
- MetadataSchema, DocumentTypeDefinition, EntityTypeDefinition
- RiskPolicy, RequiredEvidencePolicy, ApprovalPolicy, ACLMappingPolicy
- WorkflowDefinition and schema validation for industry workflows
- common DraftArtifact model, DraftArtifactTypeDefinition, DraftReviewPolicy
- KPIDefinition, DashboardWidgetDefinition, EvaluationProfile, GovernanceProfile
- regulated-industry extensions such as AdviceBoundaryPolicy and DisclosureEvidencePolicy

010 does not parse documents, store embeddings, authorize users at request time, or generate final answers by itself. It configures and validates how industry solutions call 001.

### 002 Manufacturing Solution Layer

002 owns manufacturing semantics:

- factory, line, process, equipment, alarm, product, part, defect, failure metadata
- safety, quality, equipment operation, dangerous work high-risk policy
- provisional vs permanent countermeasure distinction
- manufacturing DraftArtifact types such as maintenance_checklist, trouble_report, quality_report, training_material, faq
- manufacturing dashboard and PoC KPI

### 003 Real Estate Solution Layer

003 owns property management semantics:

- property, building, unit, owner, occupant, lease contract, repair, inquiry, move-out, restoration metadata
- contract condition, cost responsibility, restoration, legal, personal-data risk policy
- occupant and lessee terminology, never platform tenant terminology for residents
- occupant reply, owner report, repair report, move-out checklist, restoration explanation draft types
- real estate dashboard and PoC KPI

### 006 Investment Management Solution Layer

006 owns investment management semantics:

- fund, share class, prospectus, report, marketing material, RFP, DDQ, inquiry, compliance, research, risk, ESG metadata
- advice boundary, regulated activity, disclosure evidence, compliance review, marketing material consistency
- no investment advice, sell/buy recommendation, suitability decision, order execution, or final regulatory judgment
- RFP/DDQ, inquiry reply, marketing check memo, monthly commentary, compliance memo draft types
- investment dashboard and PoC KPI

### Product / Governance Overlay

The overlay is an explanation and governance layer, not a new RAG platform. It describes no-train, audit coverage, AI governance, ISMAP readiness notes, provider governance, and PoC readiness across 001, 010, and industry specs.

### Customer Configuration

Customer configuration adjusts tenant-specific terms, document types, role mappings, branch/department structures, templates, KPI targets, and risk thresholds. It must not weaken 001 tenant isolation, ACL pre-filter, no-train default, audit, or required evidence rules.

## Adding a New Industry

1. Create an industry solution spec that depends on 001 and 010.
2. Define industry metadata, document types, entities, risk categories, workflows, draft types, KPI, dashboard, audit events, non-goals.
3. Map each item to 010 abstractions.
4. Add seed IndustryProfile and MetadataSchema.
5. Add domain-friendly APIs where they improve operator usability.
6. Add tasks and tests without modifying 001 core behavior.

## Runtime Profile Storage

Default decision: hybrid.

- Code/seed data: baseline industry profiles, default schemas, system risk policies, default workflows, default draft types, initial KPI definitions.
- DB-managed runtime config: enabled profiles per tenant/collection, customer overrides, indexed metadata fields, reviewer roles, KPI targets, template references, risk thresholds.
- Change control: profile and policy changes are versioned and audited.
- Phase 0/1 scope (OD-001 / ADR-015): runtime profile editing is OUT OF SCOPE; 010 profiles are seed / read-only DB config. The profile/policy schema carries `profile_version`, `schema_version`, `effective_from`, `deprecated_at` from the start so runtime editing can be added later without a breaking migration. The full tenant-editable runtime element set is decided before Phase 2.

## JSONB vs Normalized Tables

- JSONB metadata: industry-specific document/chunk metadata, sparse fields, import aliases, schema-versioned payloads.
- Indexed hot fields: high-frequency filters such as equipment_id, property_id, unit_id, fund_id, document_type, approval_status, effective_date.
- Normalized tables: workflow entities used directly by UI, ACL, review, dashboard, and joins, such as Equipment, Unit, LeaseContract, Fund, DraftArtifact, KPI.

## Generic APIs vs Industry APIs

- Generic `/industries/...` APIs are used for framework-level profile, metadata validation, workflow execution, drafts, KPI, dashboard, and governance.
- Domain APIs such as `/real-estate/...` and `/investment/...` are allowed when they improve readability, contracts, and operator adoption.
- Domain APIs call 010 services internally and inherit 001 controls.

## DraftArtifact Model

DraftArtifact is common across industries with:

- common lifecycle: draft, in_review, approved, rejected, archived
- source_citations, source_document_ids, generated_at, template_id, audit_log_ref
- industry_id and artifact_type
- schema-validated payload JSONB for industry-specific output
- auto approval disabled by default and forbidden for AI-created artifacts

Industry-specific tables may extend payload semantics, but status transition and audit stay common.

## Policy Evaluation Order

1. Authenticate tenant/app/user claims through 001.
2. Resolve IndustryProfile and WorkflowDefinition through 010.
3. Validate input schema and metadata schema.
4. Apply ACLMappingPolicy to build 001 pre-filter constraints.
5. Execute 001 retrieval with tenant isolation, ACL pre-filter, tombstone exclusion, RetrievalProfile.
6. Evaluate RiskPolicy.
7. Apply RequiredEvidencePolicy and ApprovalPolicy to retrieved citations and document metadata.
8. If evidence is weak, return insufficient_evidence or review_required.
9. Generate answer or DraftArtifact only with authorized context.
10. Run groundedness and citation checks.
11. Write audit, cost, feedback, and KPI events.

## 001 Service Usage by 010 and Industry Layers

010 and industry layers call 001 services, they do not duplicate them:

- RetrievalService for candidate documents/chunks/citations
- AnswerService for grounded answer generation
- CitationService for text, visual, spreadsheet citations
- GroundednessService for pre and post checks
- AuditService for tenant-scoped tamper-evident audit records
- CostService for model, parser, storage, rerank, VLM, and worker costs
- ProviderPolicyService, RetrievalProfileService, LoggingPolicyEnforcer for governance controls
