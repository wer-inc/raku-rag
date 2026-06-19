# Specification Quality Checklist: Industry Solution Framework

**Purpose**: Validate framework specification completeness before planning
**Created**: 2026-06-19
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] Creates `010-industry-solution-framework` as a common feature, not as a new RAG platform
- [x] Explains placement options A/B/C and recommends B: separate common feature
- [x] Defines the layer model: 001 Base RAG Platform, 010 Industry Solution Framework, Industry Solution Specs, Customer Configuration
- [x] Includes MVP in-scope and out-of-scope sections
- [x] Defines common abstractions requested by the brief
- [x] Provides data model proposal
- [x] Provides API design policy with `/industries/...` endpoints
- [x] Provides future industry spec template
- [x] Provides `/speckit.clarify` guidance
- [x] Provides `/speckit-plan` guidance
- [x] Lists open questions before `/speckit-plan` and limits them to 5

## Base Platform Discipline

- [x] 001-rag-platform is referenced and not redefined
- [x] 001 tenant isolation, ACL, ingestion, retrieval, answer, citation, groundedness, evaluation, cost, visual RAG, parser abstraction, audit, and no-train provider configuration remain base responsibilities
- [x] 010 is positioned as common solution-layer framework, not a replacement for 001
- [x] Vector store, parser, embedding, LLM provider, and core RAG behavior are not redefined by 010

## Existing Solution Compatibility

- [x] 002 manufacturing semantics remain in 002 and are only mapped to framework abstractions
- [x] 003 real estate semantics remain in 003 and are only mapped to framework abstractions
- [x] Industry-specific metadata, risk policy, workflows, draft artifact types, and KPI are not flattened into a single generic meaning
- [x] 004 construction and 005 customer support are presented only as future profile starting points

## Required Abstractions Coverage

- [x] IndustryProfile
- [x] MetadataSchema
- [x] MetadataFieldDefinition
- [x] DocumentTypeDefinition
- [x] EntityTypeDefinition
- [x] RiskPolicy
- [x] RiskDecision
- [x] RequiredEvidencePolicy
- [x] ApprovalPolicy
- [x] ACLMappingPolicy
- [x] DraftArtifact base model
- [x] DraftArtifactTypeDefinition
- [x] DraftReviewPolicy
- [x] WorkflowDefinition
- [x] WorkflowInputSchema
- [x] WorkflowOutputSchema
- [x] KPIDefinition
- [x] DashboardWidgetDefinition
- [x] PromptTemplateSet
- [x] EvaluationProfile
- [x] GovernanceProfile
- [x] NoTrainPolicy
- [x] NoTrainPolicyRef
- [x] AuditEventDefinition

## Common Rules Coverage

- [x] Industry metadata has schema version
- [x] Industry metadata can be flexible JSONB while frequently searched/filterable keys can be indexed
- [x] Common fields include tenant_id, collection_id, document_id, approval_status, effective_date, ACL, no_train_policy_ref, retention_policy_ref
- [x] High-risk detection is delegated to per-industry RiskPolicy
- [x] RequiredEvidencePolicy blocks definitive high-risk answers without approved/effective citation
- [x] Draft/obsolete evidence is disallowed for definitive answers by default
- [x] DraftArtifact is common-managed and industry-specific via artifact_type
- [x] DraftArtifact cannot auto-approve by default
- [x] Dashboard combines common KPI and industry-specific KPI
- [x] Audit log combines common and industry-specific events
- [x] No-train policy applies across industries
- [x] Unauthorized documents, metadata, DraftArtifacts, citations, answer context, admin API response, and dashboard KPI are filtered out through 001 tenant isolation and ACL

## Mapping Coverage

- [x] Manufacturing examples mapped: factory_id, line_id, process_id, equipment_id, alarm_code, product_id, part_number, defect_type, failure_mode
- [x] Manufacturing risks mapped: dangerous work, equipment operation, quality judgment, shipment decision
- [x] Manufacturing workflows/drafts/KPIs mapped: trouble investigation, similar quality issues, checklist draft, quality report draft, maintenance_checklist, trouble_report, quality_report, self_resolution_rate, expert_interruption_reduction, high_risk_query_count, safety_gate_block_count
- [x] Real estate examples mapped: property_id, building_id, unit_id, lease_contract_id, owner_id, occupant_id, repair_category, equipment_type
- [x] Real estate risks mapped: contract condition, cost responsibility, move-out settlement, restoration, legal risk
- [x] Real estate workflows/drafts/KPIs mapped: contract question, repair investigation, occupant_reply, owner_report, repair_report, move_out_checklist, restoration_explanation, inquiry_response_time_reduction, repair_case_lookup_count, owner_report_draft_count, risk_gate_block_count

## API Coverage

- [x] GET /industries
- [x] GET /industries/{industry_id}/profile
- [x] POST /industries/{industry_id}/metadata/validate
- [x] POST /industries/{industry_id}/documents/enrich
- [x] POST /industries/{industry_id}/workflows/{workflow_id}/run
- [x] POST /industries/{industry_id}/drafts/{artifact_type}
- [x] GET /industries/{industry_id}/drafts/{artifact_id}
- [x] POST /industries/{industry_id}/drafts/{artifact_id}/review
- [x] GET /industries/{industry_id}/dashboard
- [x] GET /industries/{industry_id}/kpi
- [x] GET /industries/{industry_id}/governance/status
- [x] Allows industry-specific readable APIs in solution specs

## Success Criteria Coverage

- [x] 002 manufacturing can map to IndustryProfile / MetadataSchema / RiskPolicy / WorkflowDefinition / DraftArtifactTypeDefinition / KPIDefinition
- [x] 003 real estate can map to the same framework
- [x] New industries can be added without changing 001-rag-platform
- [x] High-risk query can be determined by per-industry RiskPolicy
- [x] RequiredEvidencePolicy prevents definitive answers without approved citations
- [x] DraftArtifact has industry-specific artifact_type and cannot auto-approve
- [x] Dashboard can show common KPI and industry-specific KPI
- [x] No-train, audit, ACL, and tenant isolation apply across industries
- [x] Industry-specific metadata schema versioning is supported
- [x] Industry profile changes do not break existing industry profiles

## Non-Goals Coverage

- [x] Does not define complete business requirements for all industries in this framework
- [x] Does not reimplement 001-rag-platform
- [x] Does not detail industry-specific UI implementation
- [x] Does not automate final legal, medical, financial, or credit decisions
- [x] Does not implement electronic signature
- [x] Does not implement full DMS
- [x] Does not replace customer core systems
- [x] Does not guarantee industry-specific regulatory compliance by framework alone


## Financial / Regulated Extension Coverage

- [x] Adds RegulatedActivityPolicy for regulated activity categories, allowed/restricted/prohibited AI actions, human review, escalation, disclaimer, and audit
- [x] Adds AdviceBoundaryPolicy for advice-like intents, prohibited outputs, allowed outputs, required behavior, review, disclaimer, and internal-only handling
- [x] Adds DisclosureEvidencePolicy for latest approved/effective source documents, draft/obsolete behavior, contradiction checks, and citation requirements
- [x] Adds ComplianceReviewPolicy for regulated artifact review states, reviewer roles, required review fields, audit, and retention
- [x] Adds MarketingMaterialPolicy for source consistency, risk disclosure, prohibited expressions, performance claims, review, and citation
- [x] Adds RecordRetentionPolicy for regulated events/artifacts, retention period, export, tamper evidence, redaction, and legal hold support
- [x] Defines RegulatedDraftArtifact as an extension of DraftArtifact without replacing the common model
- [x] Defines FinancialRiskDecision as a financial/regulatory extension example of RiskDecision
- [x] States financial hard rules: no automatic investment advice, trade recommendation, suitability judgment, final legal/regulatory judgment, or disclosure approval
- [x] States no-train, audit, ACL, tenant isolation, PII, and confidential financial data handling for financial profiles
- [x] Lists financial/regulated non-goals
- [x] Lists abstractions that 006-investment-management-mutual-fund-rag should reuse

## Feature Readiness

- [x] Ready for `/speckit.clarify` using the listed clarification guidance
- [x] Ready for `/speckit-plan` after resolving the 5 listed open questions

## Confirmation

- [x] 001 was not redefined by this feature
- [x] 002 was not changed or broken by this feature
- [x] 003 was not changed or broken by this feature
