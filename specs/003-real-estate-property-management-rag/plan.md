# Implementation Plan: Real Estate Property Management Knowledge RAG

**Feature**: `003-real-estate-property-management-rag`  
**Status**: Draft  
**Base dependency**: `001-rag-platform`  
**Framework dependency**: `010-industry-solution-framework`

## Summary

003 implements a real estate property management solution layer for PM and rental management work. It uses 001 for ingestion, retrieval, answer, citation, groundedness, ACL, tenant isolation, audit, cost, visual RAG, provider policy, and deletion. It uses 010 for IndustryProfile, MetadataSchema, RiskPolicy, RequiredEvidencePolicy, DraftArtifact, KPI, Dashboard, ACLMapping, and GovernanceProfile.

## MVP Scope

- RealEstateDocumentMetadata import/enrichment.
- Property/unit/lease/repair/inquiry knowledge retrieval.
- Contract question workflow with high-risk gate.
- Repair investigation workflow.
- Occupant reply, owner report, move-out checklist, and restoration explanation DraftArtifacts.
- Admin dashboard and PoC KPI.
- Personal data handling, redaction, audit, and no-train governance display.

## Architecture Boundary

003 does not implement a new RAG engine, vector store, parser, auth system, ACL source of truth, or audit source of truth. It adds real estate domain metadata, workflows, risk policy, draft/review policies, and KPI/dashboard views on top of 001/010.

## Services

- `RealEstateMetadataService`: imports and validates property/unit/contract/repair metadata using 010 MetadataSchema.
- `RealEstateKnowledgeService`: builds authorized property/unit knowledge views via 001 retrieval and citations.
- `RealEstateRiskGateService`: evaluates contract/legal/financial/personal-data high-risk queries using 010 RiskPolicy and RequiredEvidencePolicy.
- `RealEstateWorkflowService`: orchestrates contract question, repair investigation, reply draft, owner report, move-out checklist, and restoration draft workflows.
- `RealEstateDraftService`: creates DraftArtifacts with real estate artifact types; no automatic approval.
- `RealEstateDashboardService`: exposes KPI widgets with branch/property/role filters.
- `RealEstateGovernanceService`: exposes no-train/audit/risk/draft/provider governance status.

## Data Model Strategy

Core real estate entities can be normalized where they are used in workflows and ACL filters. RealEstateDocumentMetadata remains document/chunk metadata and maps to 010 MetadataSchema. Frequently filtered fields such as `property_id`, `building_id`, `unit_id`, `lease_contract_id`, `owner_id`, `occupant_id`, `branch_id`, `document_type`, `approval_status`, and `personal_data_category` should be indexable.

## API Strategy

Expose domain-friendly `/real-estate/...` APIs while mapping internally to 010 generic profile/workflow/draft/dashboard services and 001 retrieval/answer/citation/audit services.

## Testing Strategy

- Contract condition high-risk gate requires approved/effective citation.
- Draft/obsolete documents are not formal evidence.
- Unauthorized property/unit/contract/occupant data does not appear in retrieval, answer, citation, draft, dashboard, or admin response.
- Occupant personal data is redacted from logs/traces/evaluation/error output.
- AI-generated artifacts are always draft and require review.
- KPI/dashboard values are tenant and ACL isolated.

## Risks

- Platform tenant vs occupant naming confusion. Mitigation: always use Occupant/Lessee/Renter for residents.
- Contract/legal/cost answers can be overconfident. Mitigation: high-risk gate and human review notice.
- Personal data leakage through dashboard or drafts. Mitigation: ACL filters, redaction, minimal display, audit.

## Readiness Gates

- 001 is not redefined.
- 010 mapping is explicit.
- 002 is not changed.
- High-risk real estate queries fail closed without approved/effective citations.
- DraftArtifacts cannot auto-approve.
