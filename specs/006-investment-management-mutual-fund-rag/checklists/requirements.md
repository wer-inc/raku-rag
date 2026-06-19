# Specification Quality Checklist: Investment Management / Mutual Fund Knowledge RAG

**Purpose**: Validate 006 solution-layer specification completeness before planning
**Created**: 2026-06-19
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] Creates `006-investment-management-mutual-fund-rag` as an industry solution spec
- [x] Defines MVP as internal operations support, not direct retail investor advice
- [x] Defines target users for investment management / mutual fund operations
- [x] Includes in-scope and out-of-scope sections
- [x] Includes regulatory context references without turning the spec into legal interpretation
- [x] Includes user scenarios for fund questions, RFP/DDQ drafts, marketing material checks, monthly commentary drafts, compliance/guideline questions, and dashboard
- [x] Includes edge cases
- [x] Includes success criteria
- [x] Includes non-goals
- [x] Includes no blocking NEEDS CLARIFICATION and max 5 planning questions

## Base / Framework Discipline

- [x] 001-rag-platform is used as base platform and not redefined
- [x] 001 tenant isolation, ACL, ingestion, retrieval, answer, citation, groundedness, evaluation, cost, audit, visual RAG, parser abstraction, and no-train provider config remain base responsibilities
- [x] 010-industry-solution-framework is used as industry solution framework
- [x] 010 financial/regulated extension abstractions are reused
- [x] 002 manufacturing is not modified or referenced as a dependency
- [x] 003 real estate is not modified or referenced as a dependency

## Required Document / Metadata Coverage

- [x] Supports PDF / DOCX / XLSX / CSV / HTML / images / scanned PDFs
- [x] Covers prospectuses, delivered/requested prospectuses, reports, monthly/weekly reports, marketing materials, product summaries, trust deeds, investment guidelines, compliance/internal policies, meeting memos, research memos, RFP, DDQ, inquiry histories, risk reports, and ESG materials
- [x] Defines InvestmentManagementDocumentMetadata
- [x] Includes fund_id, fund_name, ISIN, association_code, asset_class, investment target, benchmark, currency hedge, trust fee, risk classification, distributor, document type, approval status, effective date, no_train_policy_ref, retention_policy_ref
- [x] Includes document_type examples
- [x] Supports spreadsheet/table citation references

## Regulated / High-Risk Coverage

- [x] Treats investment advice, trade recommendation, suitability judgment, legal/regulatory judgment, disclosure approval, and marketing material approval as high-risk / regulated
- [x] Requires approved and effective citations for definitive high-risk / regulated answers
- [x] Blocks definitive answers when evidence is insufficient
- [x] Does not use draft/obsolete documents as formal evidence for definitive answers
- [x] Uses AdviceBoundaryPolicy
- [x] Uses RegulatedActivityPolicy
- [x] Uses DisclosureEvidencePolicy
- [x] Uses ComplianceReviewPolicy
- [x] Uses MarketingMaterialPolicy
- [x] Uses RecordRetentionPolicy
- [x] Defines FinancialRiskDecision usage

## DraftArtifact / Review Coverage

- [x] Requires AI-generated sales material, monthly commentary, fund report commentary, RFP/DDQ response, inquiry reply, customer-facing explanation, FAQ, and internal note to be DraftArtifact
- [x] DraftArtifact starts as draft
- [x] DraftArtifact cannot auto-approve
- [x] Compliance review cannot be fully automated
- [x] Defines InvestmentDraftArtifact required fields
- [x] Requires audit for draft generation, review assignment, status transition, and compliance review transition

## ACL / PII / Governance Coverage

- [x] Maps investment metadata to 001 ACL / metadata filter
- [x] Prevents unauthorized fund, internal memo, customer data, DraftArtifact, citation, answer context, dashboard KPI, and admin API leakage
- [x] Classifies customer attributes, transaction data, account data, suitability data, inquiry history, complaint history as personal/confidential financial data
- [x] Applies redaction policy to logs, traces, evaluation data, and errors
- [x] Applies no-train by default
- [x] Prevents cross-tenant/customer-data training or improvement without opt-in
- [x] Includes RecordRetentionPolicy concerns

## API Coverage

- [x] POST /investment/metadata/import
- [x] POST /investment/documents/enrich
- [x] GET /investment/funds/{fund_id}/knowledge
- [x] POST /investment/workflows/fund-question
- [x] POST /investment/workflows/rfp-response-draft
- [x] POST /investment/workflows/ddq-response-draft
- [x] POST /investment/workflows/inquiry-reply-draft
- [x] POST /investment/workflows/marketing-material-check
- [x] POST /investment/workflows/monthly-commentary-draft
- [x] POST /investment/workflows/compliance-rule-question
- [x] GET /investment/drafts/{artifact_id}
- [x] POST /investment/drafts/{artifact_id}/review
- [x] POST /investment/drafts/{artifact_id}/compliance-review
- [x] GET /investment/disclosure-evidence/{artifact_id}
- [x] GET /investment/dashboard
- [x] GET /investment/kpi
- [x] GET /investment/audit
- [x] GET /investment/governance/status

## Success Criteria Coverage

- [x] AI does not finalize investment advice, trade recommendations, or suitability judgments
- [x] Marketing material, monthly report, and RFP/DDQ DraftArtifacts do not auto-approve
- [x] High-risk / regulated queries require approved and effective citations for definitive answers
- [x] Drafts conflicting with prospectus, trust deed, investment policy, fees, or risk disclosure can be detected
- [x] Unauthorized fund, internal memo, customer data, DraftArtifact does not appear in search, answers, citations, or dashboard
- [x] Insufficient evidence returns insufficient_evidence
- [x] Obsolete/draft documents are not formal evidence for definitive answers
- [x] No-train policy is enabled by default
- [x] Dashboard covers unanswered, low rating, frequent questions, obsolete candidates, regulated query count, advice boundary trigger count, compliance review pending count
- [x] PoC KPI are measurable

## Feature Readiness

- [x] Ready for `/speckit.clarify` if the team wants to resolve the 5 listed planning questions
- [x] Ready for `/speckit-plan` after those questions are resolved or defaults are accepted

## Confirmation

- [x] 001 was not redefined
- [x] 010 is used
- [x] 002 was not changed
- [x] 003 was not changed
