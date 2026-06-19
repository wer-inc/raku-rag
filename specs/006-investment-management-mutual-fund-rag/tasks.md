# Tasks: Investment Management / Mutual Fund Knowledge RAG

## Phase 1 - Profile and Metadata

- [ ] IM-T001 Define 010 Investment Management IndustryProfile seed with financial/regulated extensions.
- [ ] IM-T002 Define InvestmentManagement MetadataSchema and alias normalization rules.
- [ ] IM-T003 Implement metadata import/enrichment API.
- [ ] IM-T004 Add validation tests for fund/document aliases and required fields.

## Phase 2 - Domain Data Model

- [ ] IM-T010 Add migrations for Fund, FundShareClass, DistributionPartner, FundDocument, Prospectus, FundReport, MonthlyReport, MarketingMaterial, InvestmentGuideline, ComplianceRule, RFP, DDQ, InquiryCase, ResearchMemo, RiskReport, ESGDocument.
- [ ] IM-T011 Add ACL mapping for department, role, fund, share class, asset class, strategy, distribution partner, document type, approval status, confidential data category, personal data category, regulated activity category.
- [ ] IM-T012 Add tenant/fund/role isolation tests.

## Phase 3 - Regulated Risk and Evidence

- [ ] IM-T020 Implement InvestmentRiskGateService using RiskPolicy, AdviceBoundaryPolicy, RegulatedActivityPolicy, RequiredEvidencePolicy.
- [ ] IM-T021 Add tests blocking investment advice, buy/sell recommendation, suitability judgment, and legal/regulatory final judgment.
- [ ] IM-T022 Add tests requiring approved/effective citations for regulated queries.
- [ ] IM-T023 Implement DisclosureEvidenceService.
- [ ] IM-T024 Implement contradiction check result generation for marketing materials.

## Phase 4 - Workflows

- [ ] IM-T030 Implement fund-question workflow.
- [ ] IM-T031 Implement RFP response draft workflow.
- [ ] IM-T032 Implement DDQ response draft workflow.
- [ ] IM-T033 Implement inquiry reply draft workflow.
- [ ] IM-T034 Implement marketing material check workflow.
- [ ] IM-T035 Implement monthly commentary draft workflow.
- [ ] IM-T036 Implement compliance rule question workflow.

## Phase 5 - Draft and Compliance Review

- [ ] IM-T040 Implement InvestmentDraftArtifact payload schemas and artifact types.
- [ ] IM-T041 Implement draft review API.
- [ ] IM-T042 Implement compliance review API and state machine.
- [ ] IM-T043 Add no-auto-approval and no-auto-compliance-approval tests.
- [ ] IM-T044 Add audit tests for draft, compliance review, DisclosureEvidence, and contradiction checks.

## Phase 6 - Dashboard / KPI / Governance

- [ ] IM-T050 Implement InvestmentKPI calculations from audit/feedback/draft/evaluation/compliance review sources.
- [ ] IM-T051 Implement investment dashboard widgets.
- [ ] IM-T052 Implement governance status API for no-train, audit, advice boundary, regulated activity, disclosure evidence, compliance review, retention, provider governance.
- [ ] IM-T053 Add dashboard/data leakage tests for funds, customer data, internal memos, DraftArtifacts, and KPI.

## Phase 7 - Contracts / PoC

- [ ] IM-T060 Add OpenAPI contract tests for all `/investment/...` endpoints.
- [ ] IM-T061 Build PoC dataset and acceptance tests for fund question, RFP/DDQ draft, marketing material check, monthly commentary draft, compliance rule question, and KPI dashboard.

## Requirement Traceability

- IM-T001 to IM-T004 cover FR-IM-001 to FR-IM-015, 010 profile reuse, metadata alias normalization, document type aliases, and metadata validation.
- IM-T010 to IM-T012 cover Fund, FundShareClass, DistributionPartner, FundDocument, Prospectus, FundReport, MarketingMaterial, ComplianceRule, RFP, DDQ, InquiryCase, ResearchMemo, RiskReport, ESGDocument, ACL mapping, and tenant/fund isolation.
- IM-T020 to IM-T024 cover FR-IM-020 to FR-IM-034, advice boundary, regulated activity, RequiredEvidencePolicy, DisclosureEvidence, MarketingMaterialPolicy, contradiction checks, and approved/effective citation requirements.
- IM-T030 to IM-T036 cover fund-question, RFP response, DDQ response, inquiry reply, marketing material check, monthly commentary, and compliance rule workflows.
- IM-T040 to IM-T044 cover InvestmentDraftArtifact, InvestmentDraftReview, InvestmentComplianceReview, no auto approval, compliance review transitions, DisclosureEvidence audit, and contradiction audit.
- IM-T050 to IM-T053 cover InvestmentKPI, dashboard, governance status, no-train, audit, retention, provider governance, and leakage tests.
- IM-T060 to IM-T061 cover API contracts and PoC acceptance scenarios for the investment vertical slice.
