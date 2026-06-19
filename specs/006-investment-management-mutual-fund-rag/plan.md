# Implementation Plan: Investment Management / Mutual Fund Knowledge RAG

**Feature**: `006-investment-management-mutual-fund-rag`  
**Status**: Draft  
**Base dependency**: `001-rag-platform`  
**Framework dependency**: `010-industry-solution-framework`

## Summary

006 implements an internal knowledge, drafting, disclosure-evidence, and compliance-support solution layer for investment management and mutual fund companies. It is not an investment advice, recommendation, suitability, execution, or automatic compliance approval system.

## MVP Scope

- Fund and document metadata enrichment.
- Fund knowledge question workflow.
- RFP/DDQ/inquiry reply/monthly commentary DraftArtifacts.
- Marketing material consistency check.
- Compliance rule question workflow.
- Regulated/high-risk gate using 010 financial extensions.
- DisclosureEvidence and contradiction check outputs.
- Dashboard, KPI, audit, governance status.

## Architecture Boundary

006 uses 001 for ingestion, parser abstraction, retrieval, answer, citation, groundedness, visual RAG, ACL, tenant isolation, audit, cost, ProviderPolicy, RetrievalProfile, LoggingPolicy, tombstone, and evaluation. 006 uses 010 for IndustryProfile, MetadataSchema, RiskPolicy, RequiredEvidencePolicy, RegulatedActivityPolicy, AdviceBoundaryPolicy, DisclosureEvidencePolicy, ComplianceReviewPolicy, DraftArtifact, KPI, Dashboard, ACLMapping, GovernanceProfile, and RecordRetentionPolicy.

006 does not implement trade execution, suitability decisions, legal/regulatory final judgment, disclosure document approval, portfolio decision automation, or customer-facing investment advice.

## Services

- `InvestmentMetadataService`: import and normalize fund/document metadata and aliases.
- `FundKnowledgeService`: authorized fund/document retrieval using 001.
- `InvestmentRiskGateService`: evaluate advice boundary, regulated activity, marketing material, and compliance review requirements.
- `DisclosureEvidenceService`: attach approved/effective evidence and source consistency results.
- `MarketingMaterialCheckService`: compare draft statements against prospectus/trust deed/product documents/risk disclosures.
- `InvestmentWorkflowService`: run fund question, RFP/DDQ draft, inquiry reply draft, marketing check, monthly commentary, and compliance rule workflows.
- `InvestmentDraftService`: manage InvestmentDraftArtifact and compliance review state.
- `InvestmentDashboardService`: calculate regulated query/compliance/DraftArtifact KPI.
- `InvestmentGovernanceService`: explain no-train, audit, retention, provider governance, and financial AI governance notes.

## Data Model Strategy

Use normalized Fund / FundShareClass / DistributionPartner records for high-frequency ACL and filtering. Store InvestmentManagementDocumentMetadata on document/chunk metadata through 010 MetadataSchema. Keep aliases such as `association_code`/`fund_code`, `currency_hedge`/`currency_hedge_policy`, and `distributor_id`/`distribution_partner_id` for data import compatibility.

## API Strategy

Expose domain-friendly `/investment/...` APIs while internally using 010 generic services and 001 retrieval/answer/citation/audit. Regulated workflows return `review_required`, `risk_decision`, `disclosure_evidence`, and `contradiction_results` where applicable.

## Testing Strategy

- Advice/recommendation/suitability intent must not produce final advice or recommendation.
- Regulated query requires approved/effective citations.
- Marketing material check identifies contradictions with source documents.
- DraftArtifacts never auto-approve or compliance-approve.
- Fund/customer/internal memo ACL leakage is zero.
- No raw confidential financial data is stored in logs/traces/evaluation/error output.
- Dashboard and KPI are tenant/role/fund isolated.

## Risks

- AI output may look like investment advice. Mitigation: AdviceBoundaryPolicy, prohibited output block, human review, disclaimers.
- Source inconsistency in sales material can be missed. Mitigation: DisclosureEvidencePolicy and contradiction checks.
- Confidential financial data leakage. Mitigation: ACL, redaction, LoggingPolicy, audit, no-train default.

## Readiness Gates

- 001 and 010 are reused, not redefined.
- 002/003 are not changed.
- High-risk/regulated query fails closed without approved/effective citations.
- DraftArtifacts cannot auto-approve.
- Compliance review state is explicit for regulated artifacts.
