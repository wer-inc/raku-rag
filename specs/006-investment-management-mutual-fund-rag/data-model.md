# Data Model: Investment Management / Mutual Fund Knowledge RAG

006 adds investment management domain entities and regulated workflow artifacts on top of 001 and 010.

## Core Entities

### Fund
- `fund_id`, `fund_name`, `fund_code?`, `isin?`, `association_code?`
- `asset_class`, `investment_region?`, `investment_target?`, `strategy_id?`, `benchmark?`
- `currency_hedge_policy?`, `currency_hedge?`, `risk_category?`, `risk_classification?`, `status`

### FundShareClass
- `share_class_id`, `fund_id`, `currency`, `hedged_flag`, `distribution_policy`, `fee_class`, `effective_date`

### DistributionPartner
- `distribution_partner_id`, `distributor_id?`, `partner_name`, `access_scope`, `status`

### FundDocument
- `document_id`, `tenant_id`, `fund_id?`, `share_class_id?`, `document_type`, `document_period?`, `report_date?`, `approval_status`, `effective_date`, `as_of_date`, `source_uri`

### Prospectus
- `prospectus_id`, `fund_id`, `document_id`, `document_type`, `effective_date`, `approval_status`, `superseded_by?`

### FundReport / MonthlyReport
- `report_id`, `fund_id`, `document_id`, `report_date`, `document_period`, `performance_period?`, `approval_status`

### MarketingMaterial
- `marketing_material_id`, `fund_id?`, `document_id`, `marketing_material_category`, `approval_status`, `review_status`

### InvestmentGuideline
- `guideline_id`, `fund_id`, `restriction_type`, `limit_value`, `effective_date`, `approval_status`, `source_document_id`

### ComplianceRule
- `rule_id`, `category`, `source_document_id`, `effective_date`, `owner_department`, `review_required`

### RFP / DDQ
- `rfp_id` or `ddq_id`, `fund_id?`, `distribution_partner_id?`, `question_set`, `response_artifacts[]`, `status`

### InquiryCase
- `inquiry_id`, `source_type`, `fund_id?`, `distribution_partner_id?`, `question`, `response_artifact_id?`, `status`

### ResearchMemo / RiskReport / ESGDocument
- `memo_id` or `report_id`, `fund_id?`, `document_id`, `confidential_data_category`, `approval_status`, `as_of_date`

## InvestmentManagementDocumentMetadata

Minimum fields:

- `fund_id`, `fund_name`, `fund_code`, `share_class_id`, `isin`, `association_code`
- `asset_class`, `investment_region`, `investment_target`, `investment_strategy`, `benchmark`
- `currency_hedge_policy`, `currency_hedge`, `fee_type`, `trust_fee`
- `risk_category`, `risk_classification`, `target_investor_category`
- `distribution_partner_id`, `distributor_id`
- `document_type`, `document_period`, `report_date`, `as_of_date`, `performance_period`
- `approval_status`, `approval_source`, `approved_by`, `approved_at`, `effective_date`, `obsolete_at`, `superseded_by`
- `disclosure_category`, `compliance_risk_category`, `compliance_category`, `marketing_material_category`, `advice_boundary_category`, `legal_risk_category`, `regulated_activity_category`
- `confidential_data_category`, `personal_data_category`, `owner_department`, `access_scope`, `no_train_policy_ref`, `retention_policy_ref`

Alias pairs:

- `association_code` / `fund_code`
- `currency_hedge` / `currency_hedge_policy`
- `risk_classification` / `risk_category`
- `distributor_id` / `distribution_partner_id`

## Regulated Artifacts

### InvestmentDraftArtifact
Extends 010 DraftArtifact / RegulatedDraftArtifact. Artifact types include `rfp_response`, `ddq_response`, `inquiry_reply`, `marketing_material_comment`, `monthly_commentary`, `fund_report_commentary`, `compliance_check_memo`, `fund_condition_summary`, `faq`, `internal_note`.

### InvestmentDraftReview
- `review_id`, `artifact_id`, `reviewer_id`, `review_state`, `review_comment`, `reviewed_at`, `audit_log_ref`

### InvestmentComplianceReview
- `compliance_review_id`, `artifact_id`, `reviewer_group`, `review_state`, `required_changes`, `decision`, `audit_log_ref`

### DisclosureEvidence
- `evidence_id`, `artifact_id`, `statement_id`, `source_citations[]`, `source_document_ids[]`, `source_as_of_date`, `source_effective_date`, `evidence_status`

### ContradictionCheckResult
- `result_id`, `artifact_id?`, `statement`, `matched_source`, `contradiction_type`, `severity`, `recommended_action`, `audit_log_ref`

### FinancialRiskDecision
Extends 010 RiskDecision with `advice_boundary_triggered`, `regulated_activity_triggered`, `marketing_material_triggered`, `compliance_review_required`, `decision`, `reason`, `policy_version`.

### InvestmentKPI
- `kpi_id`, `tenant_id`, `collection_id?`, `fund_id?`, `department_id?`, `metric_name`, `metric_value`, `time_range`, `calculated_at`, `source_audit_log_range`, `export_ref?`
