# Data Model: Real Estate Property Management Knowledge RAG

003 adds real estate domain entities and metadata on top of 001 documents/chunks/citations/audit and 010 profile/policy/draft/KPI definitions.

## Core Entities

### Property
- `property_id`, `tenant_id`, `property_name`, `address_ref`, `branch_id`, `owner_id?`, `management_scope`, `status`

### Building
- `building_id`, `tenant_id`, `property_id`, `building_name`, `address_ref`, `status`

### Unit
- `unit_id`, `tenant_id`, `property_id`, `building_id?`, `room_number`, `unit_type`, `status`

### Owner
- `owner_id`, `tenant_id`, `owner_name_ref`, `contact_ref?`, `personal_data_category`, `access_scope`

### Occupant / Lessee
- `occupant_id`, `tenant_id`, `property_id`, `unit_id`, `occupant_name_ref`, `contact_ref?`, `personal_data_category`, `status`

### LeaseContract
- `lease_contract_id`, `tenant_id`, `property_id`, `unit_id`, `occupant_id?`, `contract_start_date`, `contract_end_date`, `renewal_date`, `approval_status`, `effective_date`

### LeaseTerm
- `lease_term_id`, `tenant_id`, `lease_contract_id`, `term_type`, `term_value`, `effective_date`, `source_citation_id`, `approval_status_at_use`

### PropertyManagementAgreement
- `management_contract_id`, `tenant_id`, `property_id`, `owner_id`, `effective_date`, `approval_status`, `source_document_id`

### RepairCase
- `repair_case_id`, `tenant_id`, `property_id`, `unit_id?`, `repair_category`, `equipment_type`, `incident_type`, `status`, `opened_at`, `closed_at?`

### MaintenanceRequest
- `maintenance_request_id`, `tenant_id`, `property_id`, `unit_id?`, `occupant_id?`, `owner_id?`, `received_at`, `channel`, `symptom`, `status`, `repair_case_id?`

### InspectionReport
- `inspection_report_id`, `tenant_id`, `property_id`, `unit_id?`, `inspection_date`, `vendor_id?`, `source_document_id`

### Vendor
- `vendor_id`, `tenant_id`, `vendor_name`, `service_category`, `access_scope`

### Estimate / Invoice
- `estimate_id` or `invoice_id`, `tenant_id`, `repair_case_id?`, `vendor_id?`, `amount`, `currency`, `document_id`, `approval_status`

### MoveOutCase / RestorationCase
- `move_out_case_id` or `restoration_case_id`, `tenant_id`, `property_id`, `unit_id`, `occupant_id?`, `move_out_date`, `status`, `source_document_ids[]`

### InquiryCase
- `inquiry_id`, `tenant_id`, `property_id?`, `unit_id?`, `occupant_id?`, `owner_id?`, `channel`, `question`, `status`, `response_artifact_id?`

### OwnerReport
- `owner_report_id`, `tenant_id`, `property_id`, `owner_id`, `artifact_id`, `status`, `report_period`

## RealEstateDocumentMetadata

Minimum fields:

- `property_id`, `building_id`, `unit_id`, `room_number`
- `owner_id`, `occupant_id`, `lease_contract_id`, `management_contract_id`
- `document_type`, `contract_start_date`, `contract_end_date`, `renewal_date`, `move_out_date`
- `repair_category`, `incident_type`, `equipment_type`, `vendor_id`
- `approval_status`, `approval_source`, `approved_by`, `approved_at`, `effective_date`, `obsolete_at`, `superseded_by`
- `legal_risk_category`, `contract_risk_category`, `financial_risk_category`, `personal_data_category`
- `owner_department`, `branch_id`, `access_scope`, `no_train_policy_ref`, `retention_policy_ref`

## Draft / Review / Risk / KPI

### RealEstateDraftArtifact
Extends 010 DraftArtifact. Artifact types include `occupant_reply`, `owner_report`, `repair_report`, `move_out_checklist`, `restoration_explanation`, `renewal_checklist`, `contract_condition_summary`, `faq`, `internal_note`.

### RealEstateDraftReview
- `review_id`, `tenant_id`, `artifact_id`, `reviewer_id?`, `reviewer_group?`, `assigned_at`, `reviewed_at`, `review_comment`, `approval_decision`, `audit_log_ref`

### RealEstateRiskDecision
- `risk_decision_id`, `tenant_id`, `query_id?`, `is_high_risk`, `risk_categories[]`, `reason_codes[]`, `classification_source`, `policy_version`, `created_at`, `audit_log_ref`

### RealEstateGateDecision
- `gate_decision_id`, `tenant_id`, `risk_decision_id`, `blocked`, `block_reason`, `approved_effective_citation_present`, `review_required`, `obsolete_warning`, `draft_warning`, `source_citation_ids[]`, `audit_log_ref`

### RealEstateKPI
- `kpi_id`, `tenant_id`, `collection_id?`, `branch_id?`, `property_id?`, `metric_name`, `metric_value`, `time_range`, `calculated_at`, `source_audit_log_range`, `export_ref?`
