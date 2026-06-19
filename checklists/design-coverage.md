# Design Coverage Checklist

**Purpose**: Check whether the full RAG product design is consistently reflected across specs, plans, data models, contracts, tasks, and governance notes.

**Scope**:
- `specs/001-rag-platform`
- `specs/010-industry-solution-framework`
- `specs/002-manufacturing-field-knowledge-rag`
- `specs/003-real-estate-property-management-rag`
- `specs/006-investment-management-mutual-fund-rag`
- root and feature-level checklists, quickstarts, contracts, tasks, and governance notes where present

**Rules**:
- This checklist is read-only guidance for design coverage review.
- Do not redefine `001-rag-platform`.
- Do not merge industry-specific semantics across 002 / 003 / 006.
- Treat missing target files as `N/A`, not an automatic failure.
- Mark each item `Covered`, `Partial`, `Missing`, or `N/A` during review.
- A checked box means the reviewer verified the item against actual files.

## 1. Architecture Layering

- [ ] [Severity: Critical] 001 is defined only as the Base RAG Platform.
  - Expected in: `specs/001-rag-platform/spec.md`, `plan.md`, `research.md`
  - Evidence to look for: Base responsibilities include tenant isolation, ACL, ingestion, retrieval, answer, citation, groundedness, evaluation, cost, audit, visual RAG, parser abstraction, no-train provider config.
  - Failure meaning: Industry or product layers may be redefining base platform behavior.
  - Fix guidance: Move base RAG responsibilities back to 001 and leave solution layers as consumers.

- [ ] [Severity: Critical] 010 is defined as the Industry Solution Framework, not a second RAG platform.
  - Expected in: `specs/010-industry-solution-framework/spec.md`, checklist
  - Evidence to look for: IndustryProfile, MetadataSchema, RiskPolicy, WorkflowDefinition, DraftArtifact, KPI, Dashboard, GovernanceProfile are common extension points.
  - Failure meaning: Industry framework may duplicate 001 or become an overly broad platform.
  - Fix guidance: Reword 010 as solution-layer framework and reference 001 for base RAG controls.

- [ ] [Severity: High] 002 is clearly a manufacturing industry solution layer.
  - Expected in: `specs/002-manufacturing-field-knowledge-rag/spec.md`, `plan.md`
  - Evidence to look for: Manufacturing field knowledge, equipment, quality, procedures, safety gates, DraftArtifact, dashboard, PoC KPI.
  - Failure meaning: Manufacturing requirements may be leaking into base or other industries.
  - Fix guidance: Keep manufacturing semantics in 002 and map only common abstractions to 010.

- [ ] [Severity: High] 003 is clearly a real estate property management solution layer.
  - Expected in: `specs/003-real-estate-property-management-rag/spec.md`
  - Evidence to look for: Property/unit/lease/repair/inquiry workflows, occupant terminology, real estate risk gates.
  - Failure meaning: Real estate semantics may be confused with base tenancy or manufacturing.
  - Fix guidance: Keep 003 domain-specific and preserve 001/010 references.

- [ ] [Severity: High] 006 is clearly an investment management / mutual fund solution layer.
  - Expected in: `specs/006-investment-management-mutual-fund-rag/spec.md`
  - Evidence to look for: Internal investment management support, RFP/DDQ, fund materials, regulated query gates, compliance review.
  - Failure meaning: Investment design may imply direct advice or base platform redesign.
  - Fix guidance: Reframe 006 as internal solution layer using 001 and 010.

- [ ] [Severity: High] Product / Governance Overlay is a cross-cutting explanation layer and does not redefine 001.
  - Expected in: 003/006 specs, 010 governance sections, 001 provider governance notes
  - Evidence to look for: no-train, audit coverage, AI governance, ISMAP/readiness/provider governance described as overlay.
  - Failure meaning: Governance content may become a separate platform or duplicate provider controls.
  - Fix guidance: Clarify overlay boundaries and delegate provider capability to 001.

- [ ] [Severity: Critical] Responsibilities across 001 / 010 / 002 / 003 / 006 are explicit.
  - Expected in: all relevant `spec.md`, `plan.md`
  - Evidence to look for: Architecture or Relationship sections naming each layer and its responsibilities.
  - Failure meaning: Later implementation may duplicate services or put domain policy in the wrong layer.
  - Fix guidance: Add relationship diagrams or boundary bullets per feature.

- [ ] [Severity: Critical] Industry specs do not redefine tenant isolation, ACL, citation, groundedness, audit, cost, or no-train.
  - Expected in: 002/003/006 `spec.md`
  - Evidence to look for: Explicit “reuse 001” wording and no replacement base behavior.
  - Failure meaning: Solution layer may weaken or fork base security.
  - Fix guidance: Replace redefinitions with references to 001 and keep only industry-specific mappings.

- [ ] [Severity: High] Industry specs use or map to 010 abstractions.
  - Expected in: 010 spec, 002/003/006 specs
  - Evidence to look for: IndustryProfile, MetadataSchema, RiskPolicy, DraftArtifact, KPI, Dashboard references.
  - Failure meaning: Future industry additions may diverge.
  - Fix guidance: Add explicit 010 mapping sections to each industry spec.

- [ ] [Severity: Medium] Customer Configuration is positioned separately from IndustryProfile.
  - Expected in: `specs/010-industry-solution-framework/spec.md`
  - Evidence to look for: Customer-specific terms, permissions, templates, KPI thresholds, risk thresholds.
  - Failure meaning: Tenant-specific customizations may fork industry specs.
  - Fix guidance: Add Customer Configuration section and versioning rules.

- [ ] [Severity: High] New industries can be added without changing 001.
  - Expected in: `specs/010-industry-solution-framework/spec.md`, future industry template
  - Evidence to look for: 004/005 template, profile-based extension mechanism.
  - Failure meaning: Base platform would need industry-specific edits for each new domain.
  - Fix guidance: Move extension points to 010 and keep 001 industry-agnostic.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 2. 001 Base RAG Platform Coverage

- [ ] [Severity: Critical] Tenant isolation is specified as a hard boundary.
  - Expected in: `specs/001-rag-platform/spec.md`, `plan.md`, `data-model.md`, `tasks.md`
  - Evidence to look for: `tenant_id` on retrievable records, cross-tenant rejection, tenant context propagation.
  - Failure meaning: Cross-tenant leakage risk is not structurally controlled.
  - Fix guidance: Add tenant_id requirements, RLS/session context, and hard-gate tests.

- [ ] [Severity: Critical] Cross-tenant rejection hard gate exists.
  - Expected in: `tasks.md`, `plan.md`, evaluation/security test strategy
  - Evidence to look for: Tests for search, answer context, visual assets, dashboard, workers, admin APIs.
  - Failure meaning: Tenant isolation may rely on convention instead of testable guarantees.
  - Fix guidance: Add explicit security tests and CI hard gate.

- [ ] [Severity: Critical] ACL is deny-by-default and enforced by retrieval pre-filter.
  - Expected in: `spec.md`, `plan.md`, `data-model.md`, `contracts/interfaces.md`, `tasks.md`
  - Evidence to look for: ACLGrant, visibility filter, pre-filter in VectorStore/RetrievalService, deny-by-default wording.
  - Failure meaning: Unauthorized chunks could reach rerank or LLM context.
  - Fix guidance: Require pre-filter in interfaces and security tests.

- [ ] [Severity: Critical] Post-filter-only authorization is explicitly forbidden.
  - Expected in: `plan.md`, `research.md`, `contracts/interfaces.md`
  - Evidence to look for: Post-check described only as defense in depth/assertion.
  - Failure meaning: Retrieval may leak candidates before filtering.
  - Fix guidance: Add pre-filter as primary control and fail-closed post-check.

- [ ] [Severity: High] Document ingestion, parser abstraction, chunking, embedding provider abstraction, vector store abstraction, reranker abstraction, LLM provider abstraction, VLM provider abstraction, and task/job queue abstraction are present.
  - Expected in: `spec.md`, `plan.md`, `contracts/interfaces.md`, `tasks.md`
  - Evidence to look for: Connector, Parser, Chunker, EmbeddingProvider, VectorStore, Reranker, LLMProvider, VLMProvider, TaskQueue.
  - Failure meaning: Provider replacement and production adapter work may be blocked.
  - Fix guidance: Add missing interface contracts and tasks.

- [ ] [Severity: Critical] Citation and groundedness-first behavior are defined.
  - Expected in: `spec.md`, `plan.md`, `contracts/openapi.md`, `data-model.md`
  - Evidence to look for: Citation entity, used_chunks, text citation, visual citation, insufficient_evidence, score/evidence gates.
  - Failure meaning: Answers may be untraceable or hallucinated.
  - Fix guidance: Add citation response shape and groundedness gates.

- [ ] [Severity: High] Spreadsheet citation extension is represented.
  - Expected in: `spec.md`, `contracts/openapi.md`, `data-model.md`, `tasks.md`
  - Evidence to look for: cell_range, sheet/row/column references, spreadsheet citation quality checks.
  - Failure meaning: XLSX/CSV evidence may not be auditable.
  - Fix guidance: Add spreadsheet citation fields and evaluation tasks.

- [ ] [Severity: Critical] No hallucinated answer rule and insufficient evidence response are specified.
  - Expected in: `spec.md`, `plan.md`, `contracts/openapi.md`, `tasks.md`
  - Evidence to look for: `insufficient_evidence`, no guessing, answer status values, tests.
  - Failure meaning: System may answer without evidence.
  - Fix guidance: Add response contract and hard tests.

- [ ] [Severity: Critical] Deletion/tombstone and cache invalidation are complete.
  - Expected in: `plan.md`, `data-model.md`, `tasks.md`
  - Evidence to look for: tombstone immediate exclusion, cascade deletion, answer/retrieval/cache invalidation, visual artifacts/crops/captions deletion.
  - Failure meaning: Deleted content may reappear in search, citations, cache, or visual previews.
  - Fix guidance: Add tombstone filters, cache invalidation rules, and deletion hard tests.

- [ ] [Severity: High] Audit log and cost tracking are modeled.
  - Expected in: `data-model.md`, `plan.md`, `contracts/openapi.md`, `tasks.md`
  - Evidence to look for: AuditLog, CostRecord, Budget, action/result/correlation_id, token/rerank/storage/indexing cost.
  - Failure meaning: Compliance and cost governance gaps.
  - Fix guidance: Add entities, APIs, and instrumentation tasks.

- [ ] [Severity: High] Evaluation covers recall@k, citation accuracy, groundedness, p95 latency, and query cost.
  - Expected in: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/openapi.md`, `tasks.md`
  - Evidence to look for: EvaluationSet/Run, metrics, baseline regression, security hard gates.
  - Failure meaning: Quality cannot be gated.
  - Fix guidance: Add evaluation model/API/tasks and benchmark plan.

- [ ] [Severity: High] Japanese support and Unicode/multibyte citation are covered.
  - Expected in: `research.md`, `data-model.md`, `tasks.md`
  - Evidence to look for: Japanese chunking, NFKC, sentence boundary, offset mapping, grapheme/code point handling.
  - Failure meaning: Japanese citations may be inaccurate.
  - Fix guidance: Add chunking/citation offset requirements and tests.

- [ ] [Severity: High] Visual RAG includes OCR, layout, region, crop, optional captioning, and visual citation.
  - Expected in: `spec.md`, `plan.md`, `data-model.md`, `contracts/openapi.md`, `contracts/interfaces.md`, `tasks.md`
  - Evidence to look for: VisualAsset, LayoutRegion, Crop, OcrEngine, LayoutExtractor, CaptioningProvider, VisualEmbeddingProvider, VLMProvider.
  - Failure meaning: Visual documents cannot be safely cited or governed.
  - Fix guidance: Add visual abstractions and security/evaluation tests.

- [ ] [Severity: High] No-train provider capability is represented as base provider config or CR.
  - Expected in: `spec.md`, `plan.md`, `research.md`, `data-model.md`
  - Evidence to look for: ProviderPolicy, no_train_required, provider capability, provider config audit.
  - Failure meaning: Sales/security claims may be unsupported.
  - Fix guidance: Add provider policy and governance status model.

- [ ] [Severity: High] ProviderPolicy, RetrievalProfile, and LoggingPolicy are included if technical stack has been added.
  - Expected in: `plan.md`, `data-model.md`, `research.md`, `contracts`, `tasks.md`
  - Evidence to look for: ProviderPolicy / RetrievalProfile / LoggingPolicy entities, APIs, tasks.
  - Failure meaning: Stack corrections are not actionable.
  - Fix guidance: Add entities, contracts, tasks, and security tests.

- [ ] [Severity: High] SourceSyncState, SourceDocumentManifest, and DocumentProcessingState are included if Dagster/sync support exists.
  - Expected in: `plan.md`, `data-model.md`, `contracts/openapi.md`, `tasks.md`
  - Evidence to look for: Sync status, manifest, processing state, IngestionRun, ReindexPlan.
  - Failure meaning: Diff sync/backfill/reindex will not be operable.
  - Fix guidance: Add state model and job status APIs.

- [ ] [Severity: Critical] Security hard-gate tests exist for ACL, tenant isolation, tombstone, visual leakage, and logging redaction.
  - Expected in: `tasks.md`, `plan.md`
  - Evidence to look for: `tests/security`, hard gate wording, CI blocking.
  - Failure meaning: Critical security claims are not verifiable.
  - Fix guidance: Add security tasks and CI requirements.

- [ ] [Severity: Medium] Production adapter dependencies are identified.
  - Expected in: `research.md`, `tasks.md`, `plan.md`
  - Evidence to look for: Bedrock, Aurora, SQS, Cognito, KMS, Secrets Manager, Langfuse, parser providers.
  - Failure meaning: MVP may depend on local/mock adapters.
  - Fix guidance: Add production adapter tasks and fallback decisions.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 3. 010 Industry Solution Framework Coverage

- [ ] [Severity: Critical] Core abstractions are defined: IndustryProfile, MetadataSchema, MetadataFieldDefinition, DocumentTypeDefinition, EntityTypeDefinition, WorkflowDefinition, WorkflowInputSchema, WorkflowOutputSchema.
  - Expected in: `specs/010-industry-solution-framework/spec.md`
  - Evidence to look for: Dedicated sections and fields for each abstraction.
  - Failure meaning: Industry profiles cannot be consistently registered.
  - Fix guidance: Add missing abstraction definitions and field lists.

- [ ] [Severity: Critical] Risk and evidence abstractions are defined: RiskPolicy, RiskDecision, RequiredEvidencePolicy, ApprovalPolicy, ACLMappingPolicy.
  - Expected in: `specs/010-industry-solution-framework/spec.md`
  - Evidence to look for: Policy IDs, industry_id, rule categories, evidence requirements, ACL mapping.
  - Failure meaning: High-risk gates will be implemented per-industry ad hoc.
  - Fix guidance: Add shared risk/evidence/ACL policy contracts.

- [ ] [Severity: High] Draft and review abstractions are defined: DraftArtifact base model, DraftArtifactTypeDefinition, DraftReviewPolicy.
  - Expected in: 010 `spec.md`, data model proposal
  - Evidence to look for: status, artifact_type, review_required, auto_approve_allowed false by default.
  - Failure meaning: AI-generated artifacts may bypass review.
  - Fix guidance: Add common DraftArtifact lifecycle and review policy.

- [ ] [Severity: High] KPI/dashboard/prompt/evaluation/governance abstractions are defined.
  - Expected in: 010 `spec.md`
  - Evidence to look for: KPIDefinition, DashboardWidgetDefinition, PromptTemplateSet, EvaluationProfile, GovernanceProfile, NoTrainPolicyRef, AuditEventDefinition.
  - Failure meaning: Dashboard and governance will fragment by industry.
  - Fix guidance: Add the missing common definitions.

- [ ] [Severity: Critical] Common fields include tenant_id, collection_id, document_id, approval_status, effective_date, ACL, no_train_policy_ref, retention_policy_ref.
  - Expected in: 010 `spec.md`, data model section
  - Evidence to look for: Common rules list.
  - Failure meaning: Industry metadata may be unfilterable or unsafe.
  - Fix guidance: Add common field requirements.

- [ ] [Severity: High] Industry metadata has schema versioning, flexible JSONB-like storage, and indexable frequent keys.
  - Expected in: 010 `spec.md`, data model guidance
  - Evidence to look for: schema version, fields/indexed_fields, JSONB, generated/promoted indexes.
  - Failure meaning: Metadata evolution and search performance are unclear.
  - Fix guidance: Add versioning and indexing policy.

- [ ] [Severity: Critical] High-risk query handling is industry-specific via RiskPolicy and RequiredEvidencePolicy.
  - Expected in: 010 `spec.md`
  - Evidence to look for: RiskPolicy per industry, approved/effective citation requirement.
  - Failure meaning: Risk gates may be too generic or missing.
  - Fix guidance: Add policy flow and default high-risk behavior.

- [ ] [Severity: Critical] DraftArtifact is common-managed and cannot auto-approve.
  - Expected in: 010 `spec.md`, checklist
  - Evidence to look for: `auto_approve_allowed false`, status lifecycle.
  - Failure meaning: AI output may become official without human review.
  - Fix guidance: Add no-auto-approval rule.

- [ ] [Severity: High] KPI and dashboard combine common and industry-specific definitions.
  - Expected in: 010 `spec.md`
  - Evidence to look for: common KPI + industry KPI, widget definitions.
  - Failure meaning: Product metrics will be inconsistent.
  - Fix guidance: Add KPI composition model.

- [ ] [Severity: High] Audit log supports common and industry-specific events.
  - Expected in: 010 `spec.md`
  - Evidence to look for: AuditEventDefinition with tenant isolation, PII redaction, retention.
  - Failure meaning: Domain workflows may miss audit coverage.
  - Fix guidance: Add audit event registry rules.

- [ ] [Severity: High] No-train policy applies to all industry solutions.
  - Expected in: 010 `spec.md`
  - Evidence to look for: NoTrainPolicyRef / NoTrainPolicy and applies_to documents/answers/citations/drafts/eval/logs.
  - Failure meaning: Industry solutions may diverge from governance commitments.
  - Fix guidance: Add common no-train rule and provider dependency on 001.

- [ ] [Severity: High] 002, 003, and 006 are mappable to 010 profiles.
  - Expected in: 010 `spec.md`, 002/003/006 specs
  - Evidence to look for: Mapping examples for manufacturing, real estate, investment/regulated.
  - Failure meaning: Framework may not support actual solution layers.
  - Fix guidance: Add mapping examples or update industry specs.

- [ ] [Severity: Medium] Future industry spec template exists for 004/005 or later industries.
  - Expected in: 010 `spec.md`
  - Evidence to look for: Construction/customer support starting points or generic template.
  - Failure meaning: Industry addition process is not standardized.
  - Fix guidance: Add reusable template.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 4. Manufacturing 002 Coverage

- [ ] [Severity: High] 002 is scoped as Manufacturing Field Knowledge RAG.
  - Expected in: `specs/002-manufacturing-field-knowledge-rag/spec.md`, `plan.md`
  - Evidence to look for: Equipment maintenance, quality issues, work instructions, technical knowledge transfer, shop-floor Q&A.
  - Failure meaning: Manufacturing scope may be too broad or unclear.
  - Fix guidance: Clarify MVP scope and users.

- [ ] [Severity: High] Manufacturing workflows are covered.
  - Expected in: 002 `spec.md`, `plan.md`, `tasks.md`
  - Evidence to look for: Alarm investigation, similar trouble search, inspection checklist draft, trouble report draft, quality report draft, training material draft, FAQ draft, dashboard.
  - Failure meaning: Core manufacturing use cases are not implemented/planned.
  - Fix guidance: Add user stories, APIs, and tasks per workflow.

- [ ] [Severity: High] Manufacturing metadata fields are defined.
  - Expected in: 002 `spec.md`, `data-model.md`
  - Evidence to look for: factory_id, line_id, process_id, equipment_id, equipment_model, alarm_code, product_id, part_number, customer_id, defect_type, failure_mode, approval metadata, safety/quality/equipment categories, hazard_tags, owner_department, access_scope.
  - Failure meaning: Retrieval filters and risk gates cannot be precise.
  - Fix guidance: Add ManufacturingDocumentMetadata and index/filter mapping.

- [ ] [Severity: Critical] Manufacturing safety gates cover safety, quality, equipment operation, dangerous work.
  - Expected in: 002 `spec.md`, `plan.md`, `tasks.md`
  - Evidence to look for: high-risk query classification by metadata + intent, uncertain cases high-risk.
  - Failure meaning: Unsafe operational advice may be generated.
  - Fix guidance: Add RiskGateService requirements and tests.

- [ ] [Severity: Critical] Approved and effective citation is required for high-risk manufacturing answers.
  - Expected in: 002 `spec.md`, `plan.md`
  - Evidence to look for: approved/effective required, draft/obsolete not formal evidence.
  - Failure meaning: Unsafe or outdated documents may be used as formal instructions.
  - Fix guidance: Add RequiredEvidencePolicy mapping.

- [ ] [Severity: High] Past cases are shown as reference/candidates, not definitive instructions.
  - Expected in: 002 `spec.md`
  - Evidence to look for: Past trouble cases labeled reference/candidate.
  - Failure meaning: Historical fixes may be over-applied.
  - Fix guidance: Add wording and answer behavior.

- [ ] [Severity: High] Countermeasure measure_class is represented.
  - Expected in: 002 `data-model.md`
  - Evidence to look for: `Countermeasure.measure_class = provisional | permanent | unknown`.
  - Failure meaning: Temporary and permanent countermeasures may be confused.
  - Fix guidance: Add field and validation.

- [ ] [Severity: Critical] AI-generated manufacturing artifacts are draft, reviewer review is required, and auto approval is forbidden.
  - Expected in: 002 `spec.md`, `data-model.md`, `tasks.md`
  - Evidence to look for: DraftArtifact statuses, reviewer, no auto approved.
  - Failure meaning: Draft reports/checklists may become official automatically.
  - Fix guidance: Add draft/review lifecycle.

- [ ] [Severity: Medium] Manufacturing non-goals are explicit.
  - Expected in: 002 `spec.md`
  - Evidence to look for: full DMS, e-signature, arbitrary rollback out of scope; dangerous work/final quality judgment not automated.
  - Failure meaning: Scope creep risk.
  - Fix guidance: Add Non-goals section.

- [ ] [Severity: High] Manufacturing dashboard and PoC KPI are defined.
  - Expected in: 002 `spec.md`, `plan.md`, `data-model.md`
  - Evidence to look for: unanswered, low ratings, frequent questions, referenced docs, obsolete docs, knowledge gaps, high-risk count, safety-gate blocks, self_resolution_rate, average_time_to_answer, expert_interruption_reduction, grounded_answer_rate, insufficient_evidence_rate, low_rating_rate, draft_review_completion_rate.
  - Failure meaning: PoC value cannot be measured.
  - Fix guidance: Add KPI definitions and dashboard tasks.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 5. Real Estate 003 Coverage

- [ ] [Severity: High] 003 is scoped as real estate property management / rental management solution layer.
  - Expected in: `specs/003-real-estate-property-management-rag/spec.md`
  - Evidence to look for: Property management, lease management, PM workflows.
  - Failure meaning: Spec may drift into broad real estate or base platform design.
  - Fix guidance: Clarify MVP business scope.

- [ ] [Severity: Critical] 003 reuses 001 and 010 and does not modify 002.
  - Expected in: 003 `spec.md`
  - Evidence to look for: Relationship to 001/010 and explicit 002 unchanged statement.
  - Failure meaning: Layering or industry isolation issue.
  - Fix guidance: Add relationship/confirmation section.

- [ ] [Severity: Critical] Platform tenant terminology is not confused with occupant/lessee/renter.
  - Expected in: 003 `spec.md`
  - Evidence to look for: Terminology section distinguishing `tenant_id` from Occupant/Lessee/Renter.
  - Failure meaning: ACL/data model confusion.
  - Fix guidance: Rename real estate resident terms consistently.

- [ ] [Severity: High] Real estate use cases are defined.
  - Expected in: 003 `spec.md`
  - Evidence to look for: contract condition Q&A, repair investigation, occupant reply draft, owner report draft, repair report draft, move-out/restoration checklist, dashboard.
  - Failure meaning: MVP workflow coverage incomplete.
  - Fix guidance: Add user stories and success criteria.

- [ ] [Severity: High] RealEstateDocumentMetadata fields are defined.
  - Expected in: 003 `spec.md`, data model if present
  - Evidence to look for: property_id, building_id, unit_id, room_number, owner_id, occupant_id, lease_contract_id, management_contract_id, document_type, dates, repair/incident/equipment/vendor, approval/effective/obsolete, risk categories, branch/access_scope.
  - Failure meaning: Retrieval and ACL filters cannot support PM workflows.
  - Fix guidance: Add metadata entity and required fields.

- [ ] [Severity: Critical] Real estate high-risk categories are defined.
  - Expected in: 003 `spec.md`
  - Evidence to look for: contract conditions, cost responsibility, move-out settlement, restoration, fees, deposits, important explanation, legal judgment, screening, personal data, official customer response, billing, termination, neighborhood disputes.
  - Failure meaning: Risky PM responses may be generated without controls.
  - Fix guidance: Add RiskPolicy mapping.

- [ ] [Severity: Critical] Real estate risk gate requires approved/effective citation and insufficient_evidence behavior.
  - Expected in: 003 `spec.md`
  - Evidence to look for: approved/effective documents, draft/obsolete not formal, legal/contract/cost requires human review, AI output draft.
  - Failure meaning: AI could provide definitive legal/contract/cost answers without evidence.
  - Fix guidance: Add RequiredEvidencePolicy and DraftArtifact review requirements.

- [ ] [Severity: High] Real estate PII categories and redaction/audit/no-train controls are specified.
  - Expected in: 003 `spec.md`
  - Evidence to look for: occupant name, address, phone, email, workplace, guarantor, emergency contact, ID docs, bank/account/payment history, redaction/audit/no-train.
  - Failure meaning: Personal data handling is under-specified.
  - Fix guidance: Add PII section and ACL/redaction/audit requirements.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 6. Investment Management 006 Coverage

- [ ] [Severity: High] 006 is scoped as investment management / mutual fund company solution layer.
  - Expected in: `specs/006-investment-management-mutual-fund-rag/spec.md`
  - Evidence to look for: Internal knowledge/search/draft/compliance support for fund managers, product, RFP/DDQ, reporting, compliance, risk.
  - Failure meaning: Scope may drift into retail advice or trading.
  - Fix guidance: Clarify internal-only MVP.

- [ ] [Severity: Critical] 006 reuses 001 and 010 and does not modify 002/003.
  - Expected in: 006 `spec.md`
  - Evidence to look for: Relationship sections and confirmation.
  - Failure meaning: Layering or industry cross-contamination.
  - Fix guidance: Add explicit dependency and non-modification statements.

- [ ] [Severity: Critical] 006 excludes direct personal investment advice, solicitation, and suitability decisions.
  - Expected in: 006 `spec.md`, Non-goals
  - Evidence to look for: Internal support only; no retail advice, buy/sell recommendation, suitability automation.
  - Failure meaning: Regulatory boundary is unsafe.
  - Fix guidance: Add AdviceBoundaryPolicy and non-goal language.

- [ ] [Severity: High] Investment use cases are covered.
  - Expected in: 006 `spec.md`
  - Evidence to look for: fund info Q&A, RFP/DDQ/inquiry drafts, marketing material consistency check, compliance/policy search, performance/risk investigation, dashboard.
  - Failure meaning: MVP workflow coverage incomplete.
  - Fix guidance: Add user stories, APIs, and SC.

- [ ] [Severity: High] Investment metadata is defined.
  - Expected in: 006 `spec.md`, data model if present
  - Evidence to look for: fund_id, fund_name, fund_code/ISIN, asset_class, region/strategy, benchmark, currency hedge, fees/trust_fee, risk category, target investor/distribution partner, document period/report date, approval/effective/obsolete, legal/compliance/marketing/advice/personal data categories, owner_department, access_scope.
  - Failure meaning: Fund retrieval and regulated gates may be imprecise.
  - Fix guidance: Add InvestmentManagementDocumentMetadata and aliases for fund_code/currency_hedge_policy where needed.

- [ ] [Severity: High] Investment document types are defined.
  - Expected in: 006 `spec.md`
  - Evidence to look for: prospectus, statutory/summary prospectus, trust deed, fund report, monthly/weekly report, marketing material, product summary, investment guideline, compliance manual, internal policy, investment committee minutes, research memo, RFP, DDQ, inquiry response, risk report, ESG report, client report, FAQ.
  - Failure meaning: DisclosureEvidencePolicy cannot identify required sources.
  - Fix guidance: Add document type list and source priority.

- [ ] [Severity: Critical] Regulated query categories are defined.
  - Expected in: 006 `spec.md`, 010 financial extension
  - Evidence to look for: advice-like output, trade recommendation, suitability, specific fund buy/sell, future returns, principal guarantee-like wording, risk understatement, fees, disclosure inconsistency, marketing, past performance, legal/compliance, conflicts, insider information, personal data, official customer response, product comparison, ESG.
  - Failure meaning: Advice/compliance boundary is unsafe.
  - Fix guidance: Add FinancialRiskDecision and AdviceBoundaryPolicy mapping.

- [ ] [Severity: Critical] Investment required controls are present.
  - Expected in: 006 `spec.md`
  - Evidence to look for: no automatic advice/recommendation/suitability, approved/effective citation for regulated query, DraftArtifact for RFP/DDQ/marketing/monthly/client reports, compliance review state, DisclosureEvidence, contradiction check, no auto approval, audit, no-train, confidential financial data handling.
  - Failure meaning: Regulated outputs may be unsafe or unaudited.
  - Fix guidance: Add RequiredEvidencePolicy, ComplianceReviewPolicy, DisclosureEvidencePolicy, RecordRetentionPolicy.

- [ ] [Severity: High] Investment dashboard/KPI are defined.
  - Expected in: 006 `spec.md`
  - Evidence to look for: regulated_query_count, advice_boundary_trigger_count, compliance_review_pending_count, compliance_gate_block_count, disclosure_inconsistency_count, rfp_response_draft_count, ddq_response_draft_count, marketing_material_review_count, inquiry_response_time_reduction.
  - Failure meaning: PoC value and compliance workload cannot be measured.
  - Fix guidance: Add KPI definitions and dashboard requirements.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 7. Technical Stack Coverage

- [ ] [Severity: High] TypeScript + NestJS API is reflected.
  - Expected in: 001 `plan.md`, `research.md`, `tasks.md`
  - Evidence to look for: NestJS API critical path, apps/api paths.
  - Failure meaning: Stack decision did not reach implementation plan.
  - Fix guidance: Update plan/tasks and contracts around NestJS.

- [ ] [Severity: Medium] Next.js + Vercel AI SDK is reflected, with hosting residency caveat.
  - Expected in: 001 `plan.md`, `research.md`, `tasks.md`
  - Evidence to look for: Next.js client, Vercel AI SDK, AWS-hosted fallback.
  - Failure meaning: Frontend plan may conflict with residency requirements.
  - Fix guidance: Add hosting policy and fallback tasks.

- [ ] [Severity: High] Thin custom orchestration is reflected and LangChain is not in the critical path.
  - Expected in: 001 `research.md`, `plan.md`, `tasks.md`
  - Evidence to look for: RetrievalOrchestrator, AnswerOrchestrator, CitationService, GroundednessService, RiskGateService, AuditService, CostService.
  - Failure meaning: Critical controls may be hidden in a generic framework.
  - Fix guidance: Add explicit orchestration services and no LangChain critical path note.

- [ ] [Severity: High] Python + SQS ingestion worker is reflected.
  - Expected in: 001 `plan.md`, `research.md`, `tasks.md`
  - Evidence to look for: SQS + DLQ, Python worker, LocalStack SQS, SQS message IDs.
  - Failure meaning: Worker architecture is not actionable.
  - Fix guidance: Add queue/worker tasks and data-model fields.

- [ ] [Severity: High] Bedrock Claude model split is reflected.
  - Expected in: 001 `plan.md`, `research.md`, `tasks.md`
  - Evidence to look for: Sonnet for answers, Haiku-class for classification/summarization/metadata enrichment/high-risk assistance.
  - Failure meaning: Cost/latency/model roles are unclear.
  - Fix guidance: Add model role table or provider capabilities.

- [ ] [Severity: High] Cohere Embed Multilingual v3 via Bedrock and chunk-size limits are reflected.
  - Expected in: 001 `plan.md`, `research.md`, `data-model.md`, `tasks.md`
  - Evidence to look for: 512 max tokens, 250-400 target, max about 450, chunking_config_version.
  - Failure meaning: Embedding quality may degrade from overlong chunks.
  - Fix guidance: Add chunking defaults and reindex rules.

- [ ] [Severity: High] Cohere Rerank via Bedrock is reflected.
  - Expected in: 001 `plan.md`, `research.md`, `tasks.md`
  - Evidence to look for: candidate limit, final context limit, cost/latency trace.
  - Failure meaning: Rerank may be too expensive or unbounded.
  - Fix guidance: Add bounded rerank settings to RetrievalProfile.

- [ ] [Severity: Critical] Aurora PostgreSQL Serverless v2 + pgvector + RLS is reflected.
  - Expected in: 001 `plan.md`, `research.md`, `data-model.md`, `tasks.md`
  - Evidence to look for: RLS, tenant context, no bypass role, partition/index planning, cross-tenant vector search tests.
  - Failure meaning: Tenant isolation and vector scaling are underspecified.
  - Fix guidance: Add RLS and query plan requirements.

- [ ] [Severity: Critical] Retrieval is metadata exact + identifier/code + vector + rerank, not vector-only.
  - Expected in: 001 `plan.md`, `research.md`, `data-model.md`, `tasks.md`
  - Evidence to look for: vector-only prohibited, identifier fields, exact/code matching, fallback hybrid.
  - Failure meaning: ID/code-heavy industry searches may fail.
  - Fix guidance: Add RetrievalProfile and identifier matching tasks.

- [ ] [Severity: High] Hybrid search fallback is evaluated later, not assumed.
  - Expected in: 001 `research.md`, `plan.md`, `tasks.md`
  - Evidence to look for: pg_bigm/pgroonga/OpenSearch evaluation or fallback criteria.
  - Failure meaning: Search complexity may be added prematurely or omitted entirely.
  - Fix guidance: Add PoC benchmark and fallback decision record.

- [ ] [Severity: High] Bedrock Guardrails are defense-in-depth only.
  - Expected in: 001 `plan.md`, `research.md`, `contracts/interfaces.md`, `tasks.md`
  - Evidence to look for: Guardrails cannot replace ACL, required evidence, groundedness, RiskGate.
  - Failure meaning: Safety controls may be delegated incorrectly.
  - Fix guidance: Add GuardrailsAdapter and tests.

- [ ] [Severity: High] Parser/OCR ProviderPolicy covers AWS-only, Azure DI opt-in, Google DI opt-in, customer-managed parser.
  - Expected in: 001 `plan.md`, `research.md`, `data-model.md`, `contracts`, `tasks.md`
  - Evidence to look for: parser_mode, allowed providers, opt-in, region, no-train/zero-retention, fallback.
  - Failure meaning: Data residency and external provider use are unsafe.
  - Fix guidance: Add ProviderPolicy controls and tests.

- [ ] [Severity: Medium] Cognito + SAML/OIDC, KMS, Secrets Manager, and future BYOK are reflected.
  - Expected in: 001 `plan.md`, `research.md`, `tasks.md`
  - Evidence to look for: Auth, encryption, secrets, future BYOK tasks/notes.
  - Failure meaning: B2B production readiness is incomplete.
  - Fix guidance: Add infra and governance tasks.

- [ ] [Severity: High] Langfuse self-host + CloudWatch/OpenTelemetry + LoggingPolicy are reflected.
  - Expected in: 001 `plan.md`, `research.md`, `data-model.md`, `contracts`, `tasks.md`
  - Evidence to look for: raw context default disabled, redaction/sampling, citation IDs/chunk IDs.
  - Failure meaning: Trace logging may leak customer data.
  - Fix guidance: Add LoggingPolicy and redaction tests.

- [ ] [Severity: High] Ragas + custom hard-gate evaluation is reflected.
  - Expected in: 001 `research.md`, `plan.md`, `tasks.md`, `contracts/openapi.md`
  - Evidence to look for: Ragas metrics plus custom security/governance gates.
  - Failure meaning: Evaluation may miss security and domain hard gates.
  - Fix guidance: Add PoC evaluation and benchmark tasks.

- [ ] [Severity: Medium] ECS Fargate + Aurora + SQS + CDK TypeScript are reflected.
  - Expected in: 001 `plan.md`, `research.md`, `tasks.md`
  - Evidence to look for: infra/cdk tasks, Fargate services, Aurora, SQS/DLQ.
  - Failure meaning: Infrastructure plan is not aligned with stack decision.
  - Fix guidance: Add CDK tasks and runtime diagram.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 8. Ingestion / Vectorization / Search Coverage

- [ ] [Severity: High] Ingestion supports PDF / DOCX / XLSX / CSV / HTML / images / scanned PDFs where required.
  - Expected in: 001, 003, 006 specs; 002 if applicable; tasks
  - Evidence to look for: Parser support, OCR/layout support, visual RAG.
  - Failure meaning: Industry MVP document types may not be ingestible.
  - Fix guidance: Add parser requirements and provider tasks.

- [ ] [Severity: High] Parser abstraction and provider policy are separated.
  - Expected in: 001 `contracts/interfaces.md`, `data-model.md`, `research.md`
  - Evidence to look for: Parser capability and ProviderPolicy enforcement.
  - Failure meaning: External cloud parsing may bypass governance.
  - Fix guidance: Add ProviderPolicy validation before parse.

- [ ] [Severity: High] Chunking is versioned and tuned to embedding limits.
  - Expected in: 001 `data-model.md`, `research.md`, `tasks.md`
  - Evidence to look for: chunking_config_version, target/max token sizes, table row/cell chunks.
  - Failure meaning: Reindex/backfill and citation accuracy may fail.
  - Fix guidance: Add chunk config version and migration tasks.

- [ ] [Severity: High] Embedding model version and embedding jobs are tracked.
  - Expected in: 001 `data-model.md`, `tasks.md`
  - Evidence to look for: embedding_model_version, EmbeddingJob, reembedding/backfill.
  - Failure meaning: Model migrations are not reproducible.
  - Fix guidance: Add EmbeddingJob and ReindexPlan linkage.

- [ ] [Severity: Critical] Search applies tenant, ACL, tombstone, approval/effective filters before rerank/LLM.
  - Expected in: 001 `plan.md`, `contracts/interfaces.md`, `tasks.md`; industry specs for approval rules
  - Evidence to look for: pre-filter pipeline and RequiredEvidencePolicy.
  - Failure meaning: Unauthorized or invalid evidence can reach answer generation.
  - Fix guidance: Add query plan and tests.

- [ ] [Severity: High] Identifier/code exact matching covers industry keys.
  - Expected in: 001 `plan.md`, `research.md`, `tasks.md`; 002/003/006 metadata
  - Evidence to look for: equipment_id, alarm_code, property_id, unit/room, contract_id, fund_id, ISIN.
  - Failure meaning: Operational lookup queries may fail.
  - Fix guidance: Add normalized identifier fields and matching tasks.

- [ ] [Severity: High] Rerank traces and candidate limits are tracked.
  - Expected in: 001 `data-model.md`, `tasks.md`
  - Evidence to look for: RerankTrace, candidate_count/final_count, cost/latency.
  - Failure meaning: Search cost/quality tuning is opaque.
  - Fix guidance: Add RerankTrace and observability.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 9. Orchestration / Sync / Reindex Coverage

- [ ] [Severity: High] SQS worker is MVP default while Dagster compatibility is preserved.
  - Expected in: 001 `plan.md`, `research.md`, `data-model.md`, `tasks.md`
  - Evidence to look for: SQS + DLQ, IngestionRun, SourceSyncState, DocumentProcessingState, ReindexPlan, optional Dagster.
  - Failure meaning: MVP execution and future control plane may diverge.
  - Fix guidance: Add queue_backend fields and compatible state model.

- [ ] [Severity: High] Source sync and manifest observation are modeled.
  - Expected in: 001 `data-model.md`, `contracts/openapi.md`, `tasks.md`
  - Evidence to look for: SourceSyncState, SourceDocumentManifest, sync-status API.
  - Failure meaning: Diff sync cannot be audited or retried.
  - Fix guidance: Add source state and status APIs.

- [ ] [Severity: Critical] Changed/deleted document detection and tombstone behavior are defined.
  - Expected in: 001 `data-model.md`, `plan.md`, `tasks.md`
  - Evidence to look for: checksum rules, deleted_in_source, immediate tombstone.
  - Failure meaning: Deleted documents may remain searchable.
  - Fix guidance: Add diff rules and deletion hard tests.

- [ ] [Severity: High] Reindex/backfill/embedding migration are planned.
  - Expected in: 001 `data-model.md`, `tasks.md`, `plan.md`
  - Evidence to look for: ReindexPlan, parser/chunking/embedding version change rules.
  - Failure meaning: Model or parser changes cannot be safely rolled out.
  - Fix guidance: Add migration/backfill tasks and state transitions.

- [ ] [Severity: Medium] Failed job visibility and retry orchestration are reflected.
  - Expected in: 001 `contracts/openapi.md`, `tasks.md`, `plan.md`
  - Evidence to look for: job status APIs, retry endpoint, DLQ, failure_reason, retry_count.
  - Failure meaning: Operations cannot recover failed documents.
  - Fix guidance: Add admin APIs and worker retry tasks.

- [ ] [Severity: Medium] Step Functions are limited to lightweight AWS-native workflows.
  - Expected in: 001 `plan.md`, `research.md`
  - Evidence to look for: Heavy parse/OCR/embedding moved to worker/ECS/Dagster executor.
  - Failure meaning: Long-running tasks may hit unsuitable runtime limits.
  - Fix guidance: Clarify orchestration boundary.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 10. Security / Governance / No-Train Coverage

- [ ] [Severity: Critical] No-train default is explicit across base and industry specs.
  - Expected in: 001, 010, 002, 003, 006 specs
  - Evidence to look for: Customer documents, queries, answers, citations, drafts, evaluations, logs not used for training without opt-in.
  - Failure meaning: Governance and sales/security commitments are unsafe.
  - Fix guidance: Add no-train policy and provider capability references.

- [ ] [Severity: Critical] Tenant isolation and ACL cover documents, metadata, DraftArtifacts, citations, admin APIs, and dashboards.
  - Expected in: all specs and tasks
  - Evidence to look for: Retrieval result, answer context, citation, dashboard, KPI access restrictions.
  - Failure meaning: Data leakage risk across tenants/users.
  - Fix guidance: Add ACL mapping and tests.

- [ ] [Severity: High] Approval/effective/obsolete controls are common and industry-specific.
  - Expected in: 010, 002, 003, 006 specs; 001 data model
  - Evidence to look for: approval_status, effective_date, obsolete_at, superseded_by, draft/obsolete exclusion.
  - Failure meaning: Outdated or draft evidence may be used as formal basis.
  - Fix guidance: Add approval policy and required evidence rules.

- [ ] [Severity: High] PII / secret redaction and personal/confidential data classifications are present.
  - Expected in: 001, 003, 006 specs; 002 if relevant
  - Evidence to look for: PII tags, secret tags, redaction policy, personal data categories, confidential financial data.
  - Failure meaning: Sensitive data may leak to logs, eval, prompts, dashboards.
  - Fix guidance: Add classification and redaction requirements.

- [ ] [Severity: High] Langfuse redaction/sampling and no raw context by default are present.
  - Expected in: 001 `plan.md`, `research.md`, `data-model.md`, `tasks.md`
  - Evidence to look for: LoggingPolicy, raw_retrieved_context_storage disabled.
  - Failure meaning: Observability stack may store customer secrets.
  - Fix guidance: Add LoggingPolicyEnforcer and tests.

- [ ] [Severity: Medium] KMS, Secrets Manager, and future BYOK are represented.
  - Expected in: 001 `plan.md`, `tasks.md`
  - Evidence to look for: encryption, secrets, future BYOK.
  - Failure meaning: Enterprise security readiness incomplete.
  - Fix guidance: Add infra/governance tasks.

- [ ] [Severity: Medium] ISMAP / financial AI governance is framed as readiness notes, not certification.
  - Expected in: governance overlay sections in 003/006/010
  - Evidence to look for: “readiness notes” or “governance explanation,” no certification claim.
  - Failure meaning: Overclaiming compliance risk.
  - Fix guidance: Reword as readiness/supporting documentation.

- [ ] [Severity: Critical] Security hard-gate tests exist.
  - Expected in: 001 `tasks.md`, industry tasks where present
  - Evidence to look for: ACL leakage = 0, tenant leakage = 0, deleted searchable = 0, no auto-approved drafts, logging violation = 0.
  - Failure meaning: Critical risks cannot be blocked before implementation.
  - Fix guidance: Add tests and CI gate.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 11. Audit / Observability / Evaluation Coverage

- [ ] [Severity: High] Audit coverage includes document upload, ingest/parse, metadata enrichment, approval transition, external approval import, search, answer, citation access, insufficient evidence, high-risk/regulated decisions, risk/safety gate decisions, DraftArtifact lifecycle, dashboard access, KPI export, ACL/tenant denied, no-train/provider changes, deletion/tombstone/cache invalidation.
  - Expected in: 001/010/002/003/006 specs, data models, tasks
  - Evidence to look for: AuditEventDefinition, AuditLog, industry audit event lists.
  - Failure meaning: Compliance traceability gaps.
  - Fix guidance: Add audit event inventory per layer.

- [ ] [Severity: High] Audit fields are defined.
  - Expected in: 001 `data-model.md`, 010 AuditEventDefinition, industry specs
  - Evidence to look for: tenant_id, actor_id, actor_role, app_id/api_client_id, action, resource_type/id, decision, reason, policy_version, approval_status at use, citation ids, timestamp, request_id/trace_id.
  - Failure meaning: Audit logs may not support investigations.
  - Fix guidance: Add required fields and redaction.

- [ ] [Severity: High] Observability includes self-host Langfuse, CloudWatch/OpenTelemetry, prompt template version, model metadata, latency, cost, redacted I/O, no raw context by default.
  - Expected in: 001 `plan.md`, `research.md`, `data-model.md`, `tasks.md`
  - Evidence to look for: LoggingPolicy and Langfuse/OTel tasks.
  - Failure meaning: Production debugging may conflict with privacy.
  - Fix guidance: Add observability policy and tests.

- [ ] [Severity: High] Evaluation includes Ragas plus custom hard gates.
  - Expected in: 001 `research.md`, `contracts/openapi.md`, `tasks.md`
  - Evidence to look for: Ragas, recall@5/10, MRR if required, citation accuracy, spreadsheet cell citation, groundedness, insufficient evidence rejection, high-risk gate compliance, tenant/ACL leakage zero, parser table accuracy, p95 latency, query cost, baseline regression.
  - Failure meaning: Quality/security evaluation is incomplete.
  - Fix guidance: Add evaluation metrics and PoC runs.

- [ ] [Severity: Medium] Evaluation datasets and baseline regression gates are planned.
  - Expected in: 001 `plan.md`, `research.md`, `tasks.md`
  - Evidence to look for: EvaluationSet, baseline comparison, PoC benchmark samples.
  - Failure meaning: Regression cannot be detected.
  - Fix guidance: Add evaluation set creation and baseline tasks.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 12. Product / PoC Readiness Coverage

- [ ] [Severity: High] PoC v0 or minimum vertical slice is defined.
  - Expected in: 001/002/003/006 specs or plans
  - Evidence to look for: Upload documents, metadata enrichment, Q&A with citation, insufficient evidence, high-risk gate, DraftArtifact, reviewer review, dashboard/KPI.
  - Failure meaning: Team may overbuild without a clear demo path.
  - Fix guidance: Add vertical slice and acceptance tests.

- [ ] [Severity: High] PoC supports PDF / DOCX / XLSX / CSV upload as needed.
  - Expected in: industry specs and 001 plan/tasks
  - Evidence to look for: Document type support and parser provider benchmark.
  - Failure meaning: Customer demo docs may not work.
  - Fix guidance: Add parser support scope and benchmark tasks.

- [ ] [Severity: High] Approved/draft/obsolete warnings and high-risk gates are demoable.
  - Expected in: 002/003/006 specs, 001/010 policy
  - Evidence to look for: RequiredEvidencePolicy, insufficient_evidence, warnings.
  - Failure meaning: Safety story is not demonstrable.
  - Fix guidance: Add demo scenarios and APIs.

- [ ] [Severity: High] Dashboard, KPI, audit view, and no-train explanation have minimum demo scope.
  - Expected in: industry specs, 001/010 plans/tasks
  - Evidence to look for: Dashboard/KPI lists, governance status APIs, audit access.
  - Failure meaning: B2B buyer readiness is weak.
  - Fix guidance: Add minimal admin/demo scope.

- [ ] [Severity: Medium] Teams integration is future, not MVP.
  - Expected in: specs/plan non-goals or roadmap if mentioned
  - Evidence to look for: Teams listed as future integration if present.
  - Failure meaning: MVP scope may expand.
  - Fix guidance: Move Teams to future roadmap.

- [ ] [Severity: High] Production adapter dependencies and blocking 001 production adapter items are identified.
  - Expected in: 001 `research.md`, `tasks.md`
  - Evidence to look for: Bedrock, Aurora, SQS, Cognito, KMS, Secrets, provider policies, Langfuse.
  - Failure meaning: Implementation may stop at mocks.
  - Fix guidance: Add production adapter tasks.

- [ ] [Severity: High] Industry-specific PoC KPI and success criteria are defined.
  - Expected in: 002/003/006 specs
  - Evidence to look for: KPI lists and success criteria per industry.
  - Failure meaning: PoC impact cannot be measured.
  - Fix guidance: Add KPI and SC sections.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 13. API / Contracts Coverage

- [ ] [Severity: High] Base generic APIs cover ingestion job status, sync status, provider policy, retrieval profile, evaluation run, governance status, and audit.
  - Expected in: `specs/001-rag-platform/contracts/openapi.md`
  - Evidence to look for: `/v1/admin/jobs`, sync-status, provider-policies, retrieval-profiles, evaluations, governance/audit endpoints if applicable.
  - Failure meaning: Admin/control plane may not be operable.
  - Fix guidance: Add API contracts or mark N/A with reason.

- [ ] [Severity: High] 010 generic industry APIs are defined.
  - Expected in: `specs/010-industry-solution-framework/spec.md`, contracts if present
  - Evidence to look for: `GET /industries`, profile, metadata validate, documents enrich, workflows run, drafts create/get/review, dashboard, KPI, governance status.
  - Failure meaning: Framework runtime/admin API is unclear.
  - Fix guidance: Add API design policy or contracts.

- [ ] [Severity: High] 002 manufacturing APIs cover metadata import, enrichment, trouble investigation, similar quality issues, checklist/report/training drafts, review, dashboard, KPI, audit, governance.
  - Expected in: 002 `contracts/`, `spec.md`, `plan.md`
  - Evidence to look for: Manufacturing endpoint candidates or OpenAPI.
  - Failure meaning: Manufacturing workflows lack API surface.
  - Fix guidance: Add contracts or endpoint candidates.

- [ ] [Severity: High] 003 real estate APIs cover metadata import/enrich, property/unit knowledge, contract question, repair investigation, occupant reply, owner report, move-out/restoration drafts, review, dashboard, KPI, audit, governance.
  - Expected in: 003 `spec.md`, contracts if present
  - Evidence to look for: `/real-estate/...` endpoint candidates.
  - Failure meaning: Real estate workflows lack API surface.
  - Fix guidance: Add API candidates or contracts.

- [ ] [Severity: High] 006 investment APIs cover metadata import/enrich, fund knowledge/question, RFP/DDQ/inquiry drafts, marketing material check, monthly commentary, compliance question, draft/compliance review, disclosure evidence, dashboard, KPI, audit, governance.
  - Expected in: 006 `spec.md`, contracts if present
  - Evidence to look for: `/investment/...` endpoint candidates.
  - Failure meaning: Investment workflows lack API surface.
  - Fix guidance: Add API candidates or contracts.

- [ ] [Severity: Medium] Each API includes request shape, response shape, errors, ACL behavior, audit event, no-train impact where applicable, and 001 dependency.
  - Expected in: contracts or spec API sections
  - Evidence to look for: Request/response schemas, error model, authorization notes.
  - Failure meaning: API First readiness is incomplete.
  - Fix guidance: Expand contracts before tasks/implementation.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 14. Data Model Coverage

- [ ] [Severity: High] 001 base data model includes Tenant, Collection, Document, DocumentElement or equivalent, Chunk, Embedding, Citation, VisualAsset, LayoutRegion, AuditEvent/AuditLog, CostEvent/CostRecord, ProviderPolicy, RetrievalProfile, LoggingPolicy, SourceSyncState, SourceDocumentManifest, DocumentProcessingState, IngestionRun, EvaluationRun.
  - Expected in: `specs/001-rag-platform/data-model.md`
  - Evidence to look for: Entity sections or explicit N/A/rationale for omitted entities.
  - Failure meaning: Base persistence is incomplete.
  - Fix guidance: Add missing entities or aliases.

- [ ] [Severity: Medium] Shared DraftArtifact base model is defined where the architecture chooses to share it.
  - Expected in: 001 or 010 data model/spec
  - Evidence to look for: DraftArtifact base, status lifecycle, industry payload.
  - Failure meaning: Draft state may fragment across industries.
  - Fix guidance: Add common model or explicitly mark industry-owned.

- [ ] [Severity: High] 010 framework data model includes all required industry abstractions.
  - Expected in: 010 `spec.md`, data model proposal
  - Evidence to look for: IndustryProfile, MetadataSchema, MetadataFieldDefinition, DocumentTypeDefinition, EntityTypeDefinition, WorkflowDefinition, RiskPolicy, RiskDecision, RequiredEvidencePolicy, ApprovalPolicy, ACLMappingPolicy, DraftArtifactTypeDefinition, DraftReviewPolicy, KPIDefinition, DashboardWidgetDefinition, GovernanceProfile, AuditEventDefinition, EvaluationProfile.
  - Failure meaning: Framework implementation cannot be planned.
  - Fix guidance: Add missing model objects.

- [ ] [Severity: High] 002 manufacturing data model includes required entities and fields.
  - Expected in: 002 `data-model.md`, `spec.md`
  - Evidence to look for: Factory, ProductionLine, Process, Equipment, AlarmCode, Product, Part, Customer, DefectType, FailureMode, TroubleCase, Countermeasure, WorkInstruction, InspectionChecklist, QualityIssue, TrainingMaterial, ManufacturingDocumentMetadata, measure_class, ManufacturingKPI.
  - Failure meaning: Manufacturing workflows lack persistence model.
  - Fix guidance: Add missing entities or mark N/A with rationale.

- [ ] [Severity: High] 003 real estate data model includes required entities and fields.
  - Expected in: 003 `spec.md`, data model if present
  - Evidence to look for: Property, Building, Unit, Owner, Occupant/Lessee, LeaseContract, RepairCase, MaintenanceRequest, InspectionReport, Vendor, Estimate, Invoice, MoveOutCase, RestorationCase, InquiryCase, OwnerReport, RealEstateDocumentMetadata, RealEstateKPI.
  - Failure meaning: Real estate workflows lack persistence model.
  - Fix guidance: Add missing entities in next plan/data-model.

- [ ] [Severity: High] 006 investment data model includes required entities and fields.
  - Expected in: 006 `spec.md`, data model if present
  - Evidence to look for: Fund, FundDocument, Prospectus, FundReport, MonthlyReport, MarketingMaterial, InvestmentGuideline, ComplianceRule, RFP, DDQ, InquiryCase, ResearchMemo, RiskReport, ESGDocument, DistributionPartner, InvestmentManagementDocumentMetadata, InvestmentDraftArtifact, DisclosureEvidence, ComplianceReviewEvent, InvestmentKPI.
  - Failure meaning: Investment workflows lack persistence model.
  - Fix guidance: Add missing entities in next plan/data-model.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 15. Tasks / Implementation Coverage

- [ ] [Severity: Critical] Every FR / SC has at least one mapped task.
  - Expected in: each feature `tasks.md` where present
  - Evidence to look for: Task IDs referencing user stories, FR/SC coverage, checklists.
  - Failure meaning: Requirements may never be implemented.
  - Fix guidance: Add requirement-to-task mapping.

- [ ] [Severity: High] Unmapped tasks are absent or justified.
  - Expected in: `tasks.md`
  - Evidence to look for: Tasks tie back to spec/plan/research decisions.
  - Failure meaning: Scope creep or orphan implementation.
  - Fix guidance: Remove, justify, or map tasks.

- [ ] [Severity: Critical] Security hard-gate tasks exist for tenant isolation, ACL pre-filter, tombstone deletion, insufficient evidence, no-train/provider config, audit coverage, RLS cross-tenant vector search, and Langfuse redaction.
  - Expected in: `tasks.md`
  - Evidence to look for: `tests/security`, hard gate wording, CI block.
  - Failure meaning: Critical controls not testable.
  - Fix guidance: Add hard-gate test tasks.

- [ ] [Severity: High] Parser, embedding, retrieval, and provider policy evaluation tasks exist.
  - Expected in: 001 `tasks.md`
  - Evidence to look for: parser benchmark, embedding benchmark, retrieval benchmark, ProviderPolicy tests.
  - Failure meaning: Technical stack choices are not validated.
  - Fix guidance: Add benchmark tasks and PoC run API.

- [ ] [Severity: High] High-risk gate and DraftArtifact no-auto-approval tasks exist.
  - Expected in: 002/003/006 tasks if present; 010 tasks if planned
  - Evidence to look for: RiskGate tests, DraftArtifact lifecycle tests.
  - Failure meaning: Domain safety requirements may be missed.
  - Fix guidance: Add tests per industry.

- [ ] [Severity: Medium] Industry metadata mapping and spreadsheet citation test tasks exist.
  - Expected in: tasks for relevant features
  - Evidence to look for: metadata mapping tests, cell_range tests.
  - Failure meaning: Retrieval filters/citations may break in real documents.
  - Fix guidance: Add integration/contract tasks.

- [ ] [Severity: Medium] PoC KPI calculation test tasks exist.
  - Expected in: 002/003/006 tasks or dashboard tasks
  - Evidence to look for: KPI calculation/export/dashboard tasks.
  - Failure meaning: PoC success cannot be measured.
  - Fix guidance: Add KPI materialization and dashboard tests.

- [ ] [Severity: Medium] Production adapter tasks are separated from solution-layer tasks.
  - Expected in: 001 and industry `tasks.md`
  - Evidence to look for: Base adapters in 001; domain workflows in 002/003/006.
  - Failure meaning: Base and industry implementation responsibilities are mixed.
  - Fix guidance: Move tasks to owning layer.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 16. Non-goals / Scope Control

- [ ] [Severity: Critical] Industry specs do not reimplement 001.
  - Expected in: 002/003/006 `spec.md`
  - Evidence to look for: “reuse 001” and no base RAG redefinitions.
  - Failure meaning: Architecture split is broken.
  - Fix guidance: Move base behavior to 001 references.

- [ ] [Severity: High] Global non-goals are preserved.
  - Expected in: 001/010/002/003/006 specs
  - Evidence to look for: full DMS, arbitrary version rollback, e-signature, core system replacement, automatic legal/medical/financial/credit decisions, unauthorized customer data training, audio/video RAG, external actions automation out of scope.
  - Failure meaning: Scope creep and compliance risk.
  - Fix guidance: Add/align Non-goals sections.

- [ ] [Severity: Critical] Manufacturing non-goals are preserved.
  - Expected in: 002 `spec.md`
  - Evidence to look for: No automatic dangerous work final instruction, no automatic final quality judgment.
  - Failure meaning: Safety-critical automation risk.
  - Fix guidance: Add manufacturing non-goals and risk gates.

- [ ] [Severity: Critical] Real estate non-goals are preserved.
  - Expected in: 003 `spec.md`
  - Evidence to look for: No automatic important explanation, screening, rent/price appraisal, accounting/payment/remittance.
  - Failure meaning: Legal/operational scope creep.
  - Fix guidance: Add real estate non-goals.

- [ ] [Severity: Critical] Investment non-goals are preserved.
  - Expected in: 006 `spec.md`
  - Evidence to look for: No automatic investment advice, trade recommendation, portfolio decision, order execution, suitability, marketing/disclosure approval, full compliance automation.
  - Failure meaning: Regulated activity boundary failure.
  - Fix guidance: Add investment non-goals and advice boundary controls.

- Covered:
- Partial:
- Missing:
- N/A:
- Notes:

## 17. Final Readiness Gates

### Plan Readiness

- [ ] [Severity: Critical] Critical gaps are zero.
  - Expected in: completed checklist and audit report
  - Evidence to look for: No Missing Critical items.
  - Failure meaning: Not ready for plan/tasks/implementation.
  - Fix guidance: Resolve all Critical gaps first.

- [ ] [Severity: High] High gaps are zero or explicitly accepted.
  - Expected in: completed checklist and audit report
  - Evidence to look for: Accepted risk notes for remaining High gaps.
  - Failure meaning: Planning may proceed with unowned risk.
  - Fix guidance: Fix or formally accept with owner/date.

- [ ] [Severity: Critical] Architecture responsibilities are clear and 001 is not redefined.
  - Expected in: all specs
  - Evidence to look for: Relationship/boundary sections.
  - Failure meaning: Implementation responsibilities may collide.
  - Fix guidance: Update relationship sections.

- [ ] [Severity: High] No open NEEDS CLARIFICATION beyond allowed items.
  - Expected in: specs/checklists
  - Evidence to look for: Max 5 open questions or defaults accepted.
  - Failure meaning: Plan may be blocked.
  - Fix guidance: Resolve or default clarification items.

- [ ] [Severity: High] Industry specs are mapped to 010 and technical stack is reflected.
  - Expected in: 010/002/003/006 and 001 docs
  - Evidence to look for: Mapping sections and stack tasks/contracts.
  - Failure meaning: Framework and implementation may diverge.
  - Fix guidance: Add mapping/stack coverage.

- [ ] [Severity: Critical] No-train, audit, governance, tenant isolation, ACL, and evaluation are reflected.
  - Expected in: all specs/plans/tasks where applicable
  - Evidence to look for: Governance sections, audit events, hard gates.
  - Failure meaning: Enterprise readiness insufficient.
  - Fix guidance: Add controls before next phase.

### Tasks Readiness

- [ ] [Severity: Critical] All FR / SC and hard gates map to tasks/tests.
  - Expected in: `tasks.md`
  - Evidence to look for: FR/SC coverage, security test tasks, eval tasks.
  - Failure meaning: Implementation plan incomplete.
  - Fix guidance: Generate/update tasks.

- [ ] [Severity: High] Industry workflows and provider/parser/retrieval evaluation map to tasks.
  - Expected in: 001/002/003/006 `tasks.md`
  - Evidence to look for: Workflow tasks, provider policy, parser benchmark, retrieval benchmark.
  - Failure meaning: PoC/design choices not executable.
  - Fix guidance: Add tasks before implementation.

- [ ] [Severity: High] No unmapped critical requirements remain.
  - Expected in: audit report
  - Evidence to look for: Requirements/task mapping matrix.
  - Failure meaning: Critical implementation gaps.
  - Fix guidance: Add tasks or remove invalid requirements.

### Implement Readiness

- [ ] [Severity: Critical] Security hard gate tests are defined.
  - Expected in: `tasks.md`, test strategy
  - Evidence to look for: RLS/tenant isolation, ACL pre-filter, no-train, audit, redaction, tombstone.
  - Failure meaning: Unsafe to implement against untested controls.
  - Fix guidance: Add hard-gate tests first.

- [ ] [Severity: High] Evaluation datasets and PoC vertical slice are planned.
  - Expected in: `research.md`, `tasks.md`, industry specs
  - Evidence to look for: 20-50 representative Japanese docs per industry, vertical slice.
  - Failure meaning: Quality and demo success cannot be verified.
  - Fix guidance: Add benchmark/eval dataset plan.

- [ ] [Severity: High] Production adapter dependencies are identified.
  - Expected in: 001 `tasks.md`, `research.md`
  - Evidence to look for: Bedrock, Aurora, SQS, Cognito, KMS, Secrets, Langfuse, parser providers.
  - Failure meaning: Implementation may stop at non-production mocks.
  - Fix guidance: Add production adapter tasks.

### Overall Readiness

- Critical gaps:
- High gaps:
- Medium gaps:
- Low gaps:
- Can proceed to /speckit-plan:
- Can proceed to /speckit-tasks:
- Can proceed to /speckit-implement:
- Required remediations before next phase:

## Execution Report Template

- Overall result:
- Coverage matrix:
- Critical findings:
- High findings:
- Medium findings:
- Low findings:
- Missing items:
- Partial items:
- Scope creep risks:
- 001 redefinition risks:
- Industry mapping gaps:
- Technical stack gaps:
- Security/governance gaps:
- Recommended next action:

