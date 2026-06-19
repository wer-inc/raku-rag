# Data Model: Industry Solution Framework

010 stores common solution-layer definitions. It does not store embeddings, parser artifacts, raw files, tenant ACL source of truth, or audit source of truth; those remain in 001.

## IndustryProfile

- `industry_id` (PK)
- `name`, `description`, `status`
- `enabled_document_types[]`
- `metadata_schema_id`, `risk_policy_id`, `approval_policy_id`, `acl_mapping_policy_id`
- `workflow_definition_ids[]`, `draft_artifact_type_ids[]`
- `kpi_definition_ids[]`, `dashboard_widget_ids[]`
- `governance_profile_id`, `evaluation_profile_id`
- `version`, `created_at`, `updated_at`

## MetadataSchema

- `schema_id` (PK), `industry_id`, `version`, `status`
- `fields` JSONB of MetadataFieldDefinition
- `required_fields[]`, `indexed_fields[]`, `pii_fields[]`, `retention_fields[]`
- `validation_rules` JSONB

## MetadataFieldDefinition

- `field_name`, `display_name`, `field_type`
- `required`, `searchable`, `filterable`, `facetable`
- `pii_category?`, `validation_rule?`, `allowed_values[]?`, `default_value?`

## DocumentTypeDefinition

- `document_type`, `industry_id`, `display_name`
- `required_metadata_fields[]`
- `default_approval_policy`, `default_retention_policy`, `default_access_scope`
- `citation_policy`

## EntityTypeDefinition

- `entity_type`, `industry_id`, `display_name`
- `id_field`, `label_field`
- `relationship_fields` JSONB
- `metadata_fields[]`

## WorkflowDefinition

- `workflow_id`, `industry_id`, `name`, `description`, `version`, `status`
- `input_schema_id`, `retrieval_profile`, `risk_policy_id`, `required_evidence_policy_id`
- `output_schema_id`, `draft_artifact_type?`, `review_required`
- `audit_events[]`, `kpi_events[]`

## WorkflowInputSchema / WorkflowOutputSchema

- `schema_id`, `industry_id`, `workflow_id`, `version`
- `json_schema` JSONB
- `required_fields[]`, `pii_fields[]`

## RiskPolicy

- `risk_policy_id`, `industry_id`, `version`
- `risk_categories[]`
- `metadata_rules` JSONB, `keyword_rules` JSONB, `intent_classification_rules` JSONB
- `llm_classifier_prompt?`
- `default_action`, `escalation_policy`, `uncertain_case_action`

## RiskDecision

- `risk_decision_id`, `tenant_id`, `query_id?`, `industry_id`
- `risk_categories[]`, `matched_rules[]`, `confidence`, `decision`, `reason`, `policy_version`
- `created_at`, `audit_log_ref`

## RequiredEvidencePolicy

- `policy_id`, `industry_id`, `version`
- `required_approval_status`, `require_effective_date_valid`
- `allow_obsolete_as_reference`, `allow_draft_as_reference`
- `minimum_citation_count`, `citation_types_allowed[]`
- `insufficient_evidence_behavior`

## ApprovalPolicy

- `policy_id`, `industry_id`, `approval_statuses[]`
- `external_approval_source_allowed`, `lightweight_workflow_allowed`
- `effective_date_required`, `obsolete_warning_required`

## ACLMappingPolicy

- `policy_id`, `industry_id`
- `metadata_fields_to_acl[]`, `role_mappings` JSONB, `department_mappings` JSONB
- `resource_scope_rules` JSONB
- `deny_by_default`, `pre_filter_required`

## DraftArtifact

- `artifact_id`, `tenant_id`, `collection_id?`, `industry_id`, `artifact_type`
- `status`: `draft | in_review | approved | rejected | archived`
- `created_by`, `reviewer_id?`, `reviewer_group?`
- `source_citations[]`, `source_document_ids[]`, `payload` JSONB
- `generated_at`, `template_id?`, `audit_log_ref`, `retention_policy_ref?`

## DraftArtifactTypeDefinition

- `artifact_type`, `industry_id`, `display_name`
- `output_schema_id`, `required_citations`, `review_required`
- `auto_approve_allowed` default false
- `retention_policy`, `export_formats[]`

## DraftReviewPolicy

- `policy_id`, `industry_id`, `allowed_transitions` JSONB
- `reviewer_roles[]`, `required_review_fields[]`
- `audit_required`, `multi_step_review_supported?`

## KPIDefinition

- `kpi_id`, `industry_id`, `name`, `description`
- `formula`, `event_sources[]`, `aggregation_window`
- `dashboard_visibility`, `target_value?`

## DashboardWidgetDefinition

- `widget_id`, `industry_id`, `name`
- `kpi_ids[]`, `filters` JSONB, `required_role`, `data_source`

## PromptTemplateSet

- `template_set_id`, `industry_id`, `workflow_id`, `version`
- `system_template_ref`, `user_template_ref`, `risk_notice_template_ref?`
- `citation_instruction`, `no_train_policy_ref`

## EvaluationProfile

- `profile_id`, `industry_id`, `metrics[]`
- `baseline_strategy`, `hard_gates[]`, `regression_gates[]`
- `evaluation_dataset_requirements` JSONB

## GovernanceProfile

- `governance_profile_id`, `industry_id`
- `no_train_policy_ref`, `audit_event_definition_ids[]`
- `retention_policy_refs[]`, `pii_policy_refs[]`
- `provider_governance_requirements` JSONB
- `ai_governance_notes`, `ismap_readiness_notes`

## AuditEventDefinition

- `event_type`, `industry_id`, `required_fields[]`
- `pii_redaction_required`, `retention_policy`, `exportable`, `tenant_isolated`

## Financial / Regulated Extensions

- `RegulatedActivityPolicy`
- `AdviceBoundaryPolicy`
- `DisclosureEvidencePolicy`
- `ComplianceReviewPolicy`
- `MarketingMaterialPolicy`
- `RecordRetentionPolicy`
- `RegulatedDraftArtifact` extension payload
- `FinancialRiskDecision` extension payload

These are optional 010 extension definitions used by 006 and future regulated industries.
