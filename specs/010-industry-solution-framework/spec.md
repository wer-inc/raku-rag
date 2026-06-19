# Feature Specification: Industry Solution Framework

**Feature Branch**: `010-industry-solution-framework`

**Created**: 2026-06-19

**Status**: Draft

**Input**: 既存の `001-rag-platform`, `002-manufacturing-field-knowledge-rag`, `003-real-estate-property-management-rag` を前提に、製造業、不動産管理、建設、カスタマーサポート、産業機械サポートなど複数業界向けの RAG solution layer を増やしやすくするための共通フレームワークを定義する。

## Summary

`010-industry-solution-framework` は、`001-rag-platform` の上で業界別 RAG アプリケーションを作るための共通型・拡張規約である。新しい RAG 基盤ではなく、業界別 solution layer が差し替えるべき metadata、risk policy、workflow、DraftArtifact、KPI、dashboard、governance、audit の contract を定義する。

業界固有の意味論は `002-manufacturing-field-knowledge-rag`, `003-real-estate-property-management-rag`, 将来の `004-construction-site-knowledge-rag`, `005-customer-support-knowledge-rag`, `006-investment-management-mutual-fund-rag` などの個別 spec に残す。010 は、それらを同じ基盤の上で追加・運用しやすくする framework である。

## Placement Decision

### Options

- **A. 001 の extension framework として追加**
  - Pros: base platform に近く、実装共通化しやすい。
  - Cons: 001 が industry semantics を背負い始め、汎用 RAG 基盤の境界が曖昧になる。

- **B. `010-industry-solution-framework` という共通 feature として分離**
  - Pros: 001 を再定義せず、002/003 の意味論を壊さず、共通 contract と registry を独立管理できる。
  - Cons: 001 と solution spec の間に追加の governance / compatibility layer が増える。

- **C. 各 solution spec の共通テンプレートとして運用**
  - Pros: 最も軽量。初期導入は速い。
  - Cons: DraftArtifact、RiskPolicy、KPI、AuditEvent の contract が実装時に分散しやすい。

### Recommendation

推奨は **B. `010-industry-solution-framework` という共通 feature として分離**。

理由:
- 001 の責務を守り、base RAG platform を industry 非依存に保てる。
- 002/003 の既存要件を変更せず、mapping により framework に乗せられる。
- 004 construction / 005 customer support 追加時に、共通抽象・API 方針・評価・audit の型を再利用できる。
- C のテンプレート運用だけでは、共通 runtime、registry、versioning、policy evaluation が必要になった時に後追い統合が難しい。

## Relationship

### 1. `001-rag-platform` = Base RAG Platform

`001-rag-platform` は業界共通の RAG 基盤であり、以下を提供する。

- tenant isolation
- ACL / authorization pre-filter
- ingestion
- retrieval
- answer generation
- citation
- groundedness
- evaluation
- cost tracking
- audit log
- visual RAG
- parser abstraction
- no-train provider configuration

010 はこれらを再定義しない。010 は 001 の API、data model、policy、audit、cost、citation、groundedness、evaluation、provider governance を利用する solution-layer framework である。

### 2. `010-industry-solution-framework` = Industry Solution Framework

010 は業界別 solution layer を作るための共通抽象を提供する。

- IndustryProfile
- MetadataSchema
- DocumentTypeDefinition
- EntityTypeDefinition
- RiskPolicy
- RequiredEvidencePolicy
- WorkflowDefinition
- DraftArtifact
- DraftReviewPolicy
- KPIDefinition
- DashboardWidgetDefinition
- ACLMappingPolicy
- GovernanceProfile
- NoTrainPolicy
- AuditEventDefinition
- EvaluationProfile

### 3. Industry Solution Specs

`002-manufacturing`, `003-real-estate`, `004-construction`, `005-customer-support`, `006-investment-management` などの individual solution specs は、業界ごとの具体的な metadata、document types、risk categories、workflows、draft artifact types、KPI、dashboard、screen language、domain templates を定義する。

010 は各業界の意味を 1 つの巨大 spec に統合しない。仕組みは共通化し、意味は業界別 spec に残す。

### 4. Customer Configuration

Customer Configuration は、顧客ごとの文書種別、用語、部署、権限、テンプレート、KPI 目標値、risk policy threshold、metadata index settings などを設定する layer である。

Customer Configuration は IndustryProfile を上書きしすぎない。業界共通 profile の互換性を保ちながら、顧客固有の用語・権限・KPI 目標・テンプレートを調整する。

## MVP Scope

### In Scope

- IndustryProfile を定義できる。
- 業界ごとの MetadataSchema を定義できる。
- 業界ごとの DocumentTypeDefinition を定義できる。
- 業界ごとの EntityTypeDefinition を定義できる。
- 業界ごとの WorkflowDefinition を定義できる。
- 業界ごとの RiskPolicy を定義できる。
- high-risk query に対する RequiredEvidencePolicy を定義できる。
- 業界ごとの ApprovalPolicy を定義できる。
- AI 生成物を DraftArtifact として共通管理できる。
- 業界ごとの DraftArtifactTypeDefinition を定義できる。
- DraftReviewPolicy を定義できる。
- 業界ごとの KPI と DashboardWidget を定義できる。
- 業界ごとの ACLMappingPolicy を定義できる。
- no-train、audit、governance の共通方針を industry solution に適用できる。
- 002 manufacturing と 003 real estate のような industry profile を、この framework にマッピングできる。
- 004 construction / 005 customer support / 006 investment management を追加するための spec template を提供できる。
- 金融・規制業界向けに regulated activity、advice boundary、disclosure evidence、compliance review、marketing material review、record retention の共通拡張を定義できる。

### Out of Scope

- 001-rag-platform の再実装。
- vector store / parser / embedding / LLM provider の再定義。
- 各業界の完全な業務アプリ実装。
- フル DMS。
- 電子署名。
- 法的判断、医療判断、金融判断、与信判断などの自動確定。
- 業界ごとの個別 UI の詳細設計。
- 全業界を最初から網羅すること。

## Design Principles

- `tenant_id`, `collection_id`, `document_id`, `approval_status`, `effective_date`, ACL, `no_train_policy_ref`, `retention_policy_ref` は全業界共通項目とする。
- 業界固有 metadata は JSONB など柔軟な構造で保持できるが、検索・filter で多用する項目は index 化できる設計にする。
- 業界ごとの metadata schema は version を持つ。
- high-risk query は業界ごとの RiskPolicy で判定する。
- high-risk query では RequiredEvidencePolicy に従い、承認済み・有効な文書引用がない場合は断定回答しない。
- AI 生成物は DraftArtifact として共通管理する。
- DraftArtifact は自動 approved にならないことを原則とする。
- 業界固有の draft type は DraftArtifactTypeDefinition で定義する。
- dashboard は共通 KPI と業界固有 KPI を組み合わせる。
- audit log は共通イベントと業界固有イベントを扱える。
- no-train policy は全業界 solution に共通適用する。
- 権限のない文書、metadata、DraftArtifact、dashboard KPI は retrieval result、answer context、citation、API response に含めない。
- 001 の ACL pre-filter、tenant isolation、groundedness、citation、audit、cost を必ず利用する。

## Key Concepts

### IndustryProfile

IndustryProfile は、特定業界 solution layer の root configuration である。

- `industry_id`
- `name`
- `description`
- `enabled_document_types`
- `metadata_schema_id`
- `risk_policy_id`
- `approval_policy_id`
- `acl_mapping_policy_id`
- `draft_artifact_types`
- `workflow_definitions`
- `kpi_definitions`
- `dashboard_widgets`
- `governance_profile_id`
- `evaluation_profile_id`

### MetadataSchema

MetadataSchema は、業界固有 metadata の schema と index 方針を定義する。

- `schema_id`
- `industry_id`
- `version`
- `fields`
- `required_fields`
- `indexed_fields`
- `pii_fields`
- `retention_fields`
- `validation_rules`

全業界共通 fields:
- `tenant_id`
- `collection_id`
- `document_id`
- `approval_status`
- `effective_date`
- `access_scope`
- `acl_tags`
- `no_train_policy_ref`
- `retention_policy_ref`

### MetadataFieldDefinition

MetadataFieldDefinition は、MetadataSchema の個別 field 定義である。

- `field_name`
- `display_name`
- `field_type`
- `required`
- `searchable`
- `filterable`
- `facetable`
- `pii_category`
- `validation_rule`
- `allowed_values`
- `default_value`

### DocumentTypeDefinition

DocumentTypeDefinition は、業界ごとの文書種別と evidence/citation の扱いを定義する。

- `document_type`
- `industry_id`
- `display_name`
- `required_metadata_fields`
- `default_approval_policy`
- `default_retention_policy`
- `default_access_scope`
- `citation_policy`

### EntityTypeDefinition

EntityTypeDefinition は、業界 domain entity と metadata の関係を定義する。

- `entity_type`
- `industry_id`
- `display_name`
- `id_field`
- `label_field`
- `relationship_fields`
- `metadata_fields`

### WorkflowDefinition

WorkflowDefinition は、業界ごとの業務 workflow を定義する。Workflow は solution service から実行され、AWS MVP では NestJS API の IndustryWorkflowService が 001 の retrieval / answer / citation / audit / cost / groundedness を利用する。

- `workflow_id`
- `industry_id`
- `name`
- `description`
- `input_schema`
- `retrieval_profile`
- `risk_policy_id`
- `required_evidence_policy_id`
- `output_schema`
- `draft_artifact_type` optional
- `review_required`
- `audit_events`
- `kpi_events`

### WorkflowInputSchema

- `schema_id`
- `industry_id`
- `workflow_id`
- `version`
- `json_schema`
- `required_fields`
- `pii_fields`
- `validation_rules`

### WorkflowOutputSchema

- `schema_id`
- `industry_id`
- `workflow_id`
- `version`
- `json_schema`
- `citation_fields`
- `draft_payload_fields`
- `pii_fields`
- `validation_rules`

### RiskPolicy

RiskPolicy は、業界ごとの high-risk 判定を定義する。

- `risk_policy_id`
- `industry_id`
- `risk_categories`
- `metadata_rules`
- `keyword_rules`
- `intent_classification_rules`
- `llm_classifier_prompt` optional
- `default_action`
- `escalation_policy`
- `uncertain_case_action`

`uncertain_case_action` は、判定が曖昧な場合に high-risk として扱うか、review_required にするか、insufficient_evidence にするかを定義する。

### RiskDecision

RiskDecision は、query / workflow / draft generation に対して RiskPolicy を適用した結果である。

- `risk_decision_id`
- `query_id`
- `industry_id`
- `risk_categories`
- `matched_rules`
- `confidence`
- `decision`
- `reason`
- `policy_version`

### RequiredEvidencePolicy

RequiredEvidencePolicy は、high-risk query や draft workflow が必要とする evidence 条件を定義する。

- `policy_id`
- `industry_id`
- `required_approval_status`
- `require_effective_date_valid`
- `allow_obsolete_as_reference`
- `allow_draft_as_reference`
- `minimum_citation_count`
- `citation_types_allowed`
- `insufficient_evidence_behavior`

Default behavior:
- `required_approval_status = approved`
- `require_effective_date_valid = true`
- `allow_obsolete_as_reference = false` for definitive answers
- `allow_draft_as_reference = false` for definitive answers
- insufficient evidence の場合は断定回答せず `insufficient_evidence` または `review_required` を返す。

### ApprovalPolicy

ApprovalPolicy は、文書や metadata が正式根拠として利用可能になる条件を定義する。

- `policy_id`
- `industry_id`
- `approval_statuses`
- `external_approval_source_allowed`
- `lightweight_workflow_allowed`
- `effective_date_required`
- `obsolete_warning_required`

### ACLMappingPolicy

ACLMappingPolicy は、業界固有 metadata を 001 の ACL / metadata filter / resource scope に mapping する。

- `policy_id`
- `industry_id`
- `metadata_fields_to_acl`
- `role_mappings`
- `department_mappings`
- `resource_scope_rules`
- `deny_by_default`
- `pre_filter_required`

### DraftArtifact

DraftArtifact は、AI が生成する返信、報告書、checklist、FAQ、internal note などを共通管理する base model である。AI が生成した artifact は必ず draft として作成し、自動 approved にしてはならない。

- `artifact_id`
- `industry_id`
- `artifact_type`
- `status`
- `created_by`
- `reviewer_id` or `reviewer_group`
- `source_citations`
- `source_document_ids`
- `generated_at`
- `template_id`
- `audit_log_ref`

Common statuses:
- `draft`
- `in_review`
- `approved`
- `rejected`
- `archived`

Storage guidance:
- common fields は shared table の first-class column とする。
- 業界固有 payload は schema validation 済み JSONB として保持できる。
- 必要に応じて業界別 extension table を追加できるが、status transition と audit は共通 DraftArtifact contract に従う。

### DraftArtifactTypeDefinition

- `artifact_type`
- `industry_id`
- `display_name`
- `output_schema`
- `required_citations`
- `review_required`
- `auto_approve_allowed` false by default
- `retention_policy`
- `export_formats`

### DraftReviewPolicy

- `policy_id`
- `industry_id`
- `allowed_transitions`
- `reviewer_roles`
- `required_review_fields`
- `audit_required`
- `multi_step_review_supported` optional

### KPIDefinition

- `kpi_id`
- `industry_id`
- `name`
- `description`
- `formula`
- `event_sources`
- `aggregation_window`
- `dashboard_visibility`
- `target_value` optional

### DashboardWidgetDefinition

- `widget_id`
- `industry_id`
- `name`
- `kpi_ids`
- `filters`
- `required_role`
- `data_source`

### PromptTemplateSet

PromptTemplateSet は、業界 workflow ごとの prompt template と citation/risk notice を定義する。Prompt は 001 の provider abstraction と no-train / audit 方針に従う。

- `template_set_id`
- `industry_id`
- `workflow_id`
- `version`
- `system_prompt_ref`
- `task_prompt_ref`
- `citation_policy_text`
- `risk_notice_text`
- `language`
- `status`

### EvaluationProfile

- `profile_id`
- `industry_id`
- `metrics`
- `baseline_strategy`
- `hard_gates`
- `regression_gates`
- `evaluation_dataset_requirements`

### GovernanceProfile

- `governance_profile_id`
- `industry_id`
- `no_train_policy_ref`
- `audit_event_definitions`
- `retention_policy_refs`
- `pii_policy_refs`
- `provider_governance_requirements`
- `ai_governance_notes`
- `ismap_readiness_notes`

### NoTrainPolicy

NoTrainPolicy は、業界 solution に共通適用される customer data usage policy を定義する。Provider の no-train capability と contract mode は 001 の provider configuration に依存する。

- `policy_id`
- `default_no_train`
- `opt_in_required`
- `applies_to`
- `provider_capability_source`
- `customer_visible_description`
- `audit_required`
- `governance_status_ref`

Default:
- 顧客がアップロードした文書、metadata、query、answer、citation、DraftArtifact、feedback、evaluation data、log は opt-in なしにモデル学習・横断改善・別テナント向け改善へ利用しない。

### NoTrainPolicyRef

- `policy_ref`
- `default_no_train`
- `opt_in_required`
- `provider_capability_source`
- `applies_to`

### AuditEventDefinition

- `event_type`
- `industry_id`
- `required_fields`
- `pii_redaction_required`
- `retention_policy`
- `exportable`
- `tenant_isolated`

## Data Model Proposal

```text
IndustryProfile 1--1 MetadataSchema
IndustryProfile 1--N MetadataFieldDefinition
IndustryProfile 1--N DocumentTypeDefinition
IndustryProfile 1--N EntityTypeDefinition
IndustryProfile 1--N RiskPolicy
IndustryProfile 1--N RequiredEvidencePolicy
IndustryProfile 1--N ApprovalPolicy
IndustryProfile 1--N ACLMappingPolicy
IndustryProfile 1--N WorkflowDefinition
IndustryProfile 1--N DraftArtifactTypeDefinition
IndustryProfile 1--N DraftReviewPolicy
IndustryProfile 1--N KPIDefinition
IndustryProfile 1--N DashboardWidgetDefinition
IndustryProfile 1--N PromptTemplateSet
IndustryProfile 1--N EvaluationProfile
IndustryProfile 1--N GovernanceProfile
IndustryProfile 1--N AuditEventDefinition
GovernanceProfile N--1 NoTrainPolicy

DocumentMetadataExtension N--1 IndustryProfile
DocumentMetadataExtension N--1 MetadataSchema
DocumentMetadataExtension N--1 001 Document

RiskDecision N--1 RiskPolicy
RiskDecision N--1 001 Query or WorkflowRun

DraftArtifact N--1 IndustryProfile
DraftArtifact N--1 DraftArtifactTypeDefinition
DraftArtifact N--N 001 Citation via source_citations
DraftArtifact N--N 001 Document via source_document_ids

WorkflowRun N--1 WorkflowDefinition
WorkflowRun N--1 RiskDecision
WorkflowRun N--1 DraftArtifact optional
WorkflowRun N--N AuditEventDefinition

KPIValue N--1 KPIDefinition
DashboardWidget N--N KPIDefinition
```

### Suggested Tables / Objects

- `industry_profiles`
- `metadata_schemas`
- `metadata_field_definitions`
- `document_type_definitions`
- `entity_type_definitions`
- `risk_policies`
- `risk_decisions`
- `required_evidence_policies`
- `approval_policies`
- `acl_mapping_policies`
- `workflow_definitions`
- `workflow_runs`
- `draft_artifacts`
- `draft_artifact_type_definitions`
- `draft_review_policies`
- `kpi_definitions`
- `kpi_values`
- `dashboard_widget_definitions`
- `prompt_template_sets`
- `evaluation_profiles`
- `governance_profiles`
- `no_train_policies`
- `audit_event_definitions`
- `document_metadata_extensions`

### Storage Guidance

- Common fields should be first-class columns where they are queried across industries: `tenant_id`, `collection_id`, `document_id`, `industry_id`, `approval_status`, `effective_date`, `artifact_type`, `status`, `no_train_policy_ref`, `retention_policy_ref`.
- Industry metadata should be stored in `industry_metadata` JSONB or equivalent.
- `MetadataSchema.indexed_fields` controls managed indexes for frequently searched/filterable keys.
- Customer-specific indexed fields may be allowed, but they must be versioned and migration-aware.
- Every industry object must remain tenant-scoped and must use 001 ACL / metadata pre-filter before retrieval and answer context construction.
- PII fields must be marked in MetadataFieldDefinition and governed by 001 audit/redaction policies.

## API Design Policy

Framework APIs may be exposed as internal/admin APIs or product APIs where appropriate. Industry-specific readable APIs can still be defined in each solution spec.

Common framework APIs:

```text
GET  /industries
GET  /industries/{industry_id}/profile
POST /industries/{industry_id}/metadata/validate
POST /industries/{industry_id}/documents/enrich
POST /industries/{industry_id}/workflows/{workflow_id}/run
POST /industries/{industry_id}/drafts/{artifact_type}
GET  /industries/{industry_id}/drafts/{artifact_id}
POST /industries/{industry_id}/drafts/{artifact_id}/review
GET  /industries/{industry_id}/dashboard
GET  /industries/{industry_id}/kpi
GET  /industries/{industry_id}/governance/status
```

Industry-facing APIs remain allowed and should be defined in each solution spec where they improve readability:

```text
/manufacturing/...
/real-estate/...
/construction/...
/customer-support/...
```

Rules:
- All APIs inherit 001 authentication, tenant isolation, ACL, audit, citation, cost, and groundedness behavior.
- Common `/industries/...` APIs should not replace domain-friendly industry APIs when those APIs improve operator usability.
- Workflow APIs must evaluate RiskPolicy and RequiredEvidencePolicy before giving definitive answers.
- Draft-producing workflow APIs must create `DraftArtifact(status=draft)` and must not auto-approve.
- Dashboard/KPI APIs must apply tenant isolation and ACL/role restrictions before returning metrics.
- Governance status APIs may summarize no-train, retention, audit coverage, and provider governance status, but provider capability source remains 001.

## Workflow Execution Flow

1. NestJS API receives an industry workflow request under either a common `/industries/...` endpoint or an industry-specific endpoint.
2. IndustryWorkflowService loads IndustryProfile, WorkflowDefinition, MetadataSchema, RiskPolicy, RequiredEvidencePolicy, ACLMappingPolicy, and GovernanceProfile.
3. Request input is validated with WorkflowInputSchema.
4. ACLMappingPolicy maps industry metadata filters to 001 ACL / metadata pre-filter.
5. 001 retrieval returns tenant-isolated, ACL-filtered candidate citations.
6. RiskPolicy creates RiskDecision.
7. RequiredEvidencePolicy checks approval status, effective date, obsolete/draft eligibility, citation count, and citation type.
8. If evidence is insufficient, response is `insufficient_evidence` or `review_required` according to policy.
9. If workflow produces AI content, DraftArtifact is created with `status=draft`.
10. Audit events, cost events, KPI events, and governance/no-train records are written through 001-compatible services.

## Industry Profile Examples

### Manufacturing Profile Example

```text
IndustryProfile.industry_id = manufacturing
```

Metadata examples:
- `factory_id`
- `line_id`
- `process_id`
- `equipment_id`
- `alarm_code`
- `product_id`
- `part_number`
- `defect_type`
- `failure_mode`

Risk examples:
- dangerous work
- equipment operation
- quality judgment
- shipment decision

Workflow examples:
- trouble investigation
- similar quality issues
- checklist draft
- quality report draft

DraftArtifact types:
- `maintenance_checklist`
- `trouble_report`
- `quality_report`
- `training_material`
- `faq`

KPI examples:
- `self_resolution_rate`
- `expert_interruption_reduction`
- `high_risk_query_count`
- `safety_gate_block_count`

Mapping to framework:
- Manufacturing-specific metadata fields remain in 002 and are registered through MetadataSchema / MetadataFieldDefinition.
- Safety and quality gates remain in 002 and are expressed as RiskPolicy + RequiredEvidencePolicy.
- Trouble reports, maintenance checklists, and quality reports remain 002 draft types registered through DraftArtifactTypeDefinition.
- PoC metrics remain 002 KPI semantics registered through KPIDefinition / DashboardWidgetDefinition.

### Real Estate Property Management Profile Example

```text
IndustryProfile.industry_id = real_estate_pm
```

Metadata examples:
- `property_id`
- `building_id`
- `unit_id`
- `lease_contract_id`
- `owner_id`
- `occupant_id`
- `repair_category`
- `equipment_type`

Risk examples:
- contract condition
- cost responsibility
- move-out settlement
- restoration
- legal risk

Workflow examples:
- contract question
- repair investigation
- occupant reply draft
- owner report draft

DraftArtifact types:
- `occupant_reply`
- `owner_report`
- `repair_report`
- `move_out_checklist`
- `restoration_explanation`
- `faq`

KPI examples:
- `inquiry_response_time_reduction`
- `repair_case_lookup_count`
- `owner_report_draft_count`
- `risk_gate_block_count`

Mapping to framework:
- Real estate-specific metadata fields remain in 003 and are registered through MetadataSchema / MetadataFieldDefinition.
- Contract, cost, move-out, restoration, legal, and personal data risk remain in 003 and are expressed as RiskPolicy + RequiredEvidencePolicy.
- Occupant replies, owner reports, repair reports, move-out checklists, and restoration explanations remain 003 draft types registered through DraftArtifactTypeDefinition.
- Dashboard and PoC metrics remain 003 KPI semantics registered through KPIDefinition / DashboardWidgetDefinition.


## Financial / Regulated Industry Extension

### Change Request Summary

この拡張は、投資運用会社・投資信託会社・証券・保険・銀行など、規制が強く、助言・勧誘・説明責任・監査が重要な業界 profile を 010 上で安全に定義するための共通抽象である。

010 は金融業界専用 spec ではない。具体的な投資信託会社向け業務、metadata、workflow、KPI は `006-investment-management-mutual-fund-rag` のような industry solution spec に残す。

Regulatory context references:
- 金融庁「AIディスカッションペーパー（第1.1版）の公表について」(2026-03-03): https://www.fsa.go.jp/news/r7/sonota/20260303/aidp.html
- 金融庁「金融商品取引業者等向けの総合的な監督指針」(2026-05): https://www.fsa.go.jp/common/law/guide/kinyushohin.pdf
- 金融庁「顧客本位の業務運営について」: https://www.fsa.go.jp/policy/kokyakuhoni/kokyakuhoni.html

This framework records these as product/regulatory context only. It does not provide legal interpretation or guarantee regulatory compliance by itself.

### Additional Scope

Financial / regulated industry profiles may use 010 for:
- internal knowledge search
- compliance-oriented evidence retrieval
- marketing material consistency checks
- RFP / DDQ / inquiry response drafts
- reporting commentary drafts
- disclosure evidence packaging
- compliance review routing
- audit and record retention controls

Financial / regulated industry profiles must avoid using 010 to automate:
- investment advice
- trade recommendations
- suitability decisions for individual customers
- final legal or regulatory judgments
- final approval of disclosure or marketing materials
- order execution, fund transfer, or account operations

### RegulatedActivityPolicy

RegulatedActivityPolicy defines how an industry profile identifies and constrains regulated activity.

- `policy_id`
- `industry_id`
- `regulated_activity_categories`
- `allowed_ai_actions`
- `restricted_ai_actions`
- `prohibited_ai_actions`
- `human_review_required`
- `escalation_roles`
- `disclaimer_policy`
- `audit_required`

Default behavior:
- AI may retrieve, summarize, compare, draft, and flag evidence for internal users.
- AI must not automatically finalize regulated advice, solicitation, disclosure approval, suitability judgment, legal conclusion, regulatory conclusion, order, trade, or payment action.
- Restricted activity must create audit events and, when configured, route to compliance or responsible manager review.

### AdviceBoundaryPolicy

AdviceBoundaryPolicy defines the boundary between permitted internal assistance and prohibited advice-like output.

- `policy_id`
- `industry_id`
- `advice_like_intent_categories`
- `prohibited_outputs`
- `allowed_outputs`
- `required_response_behavior`
- `human_review_required`
- `user_facing_disclaimer`
- `internal_only_flag`

Default advice-like intent categories:
- buy / sell / hold recommendation
- product recommendation for a specific investor
- suitability assessment for an individual customer
- portfolio allocation instruction
- investment judgment finalization
- promise of return, risk, or loss avoidance

Default permitted outputs:
- cite source documents
- explain what approved source documents state
- produce internal draft language
- list missing evidence
- route to human review
- return `insufficient_evidence` or `review_required`

### DisclosureEvidencePolicy

DisclosureEvidencePolicy defines required evidence for customer-facing, sales-facing, or regulator-facing materials.

- `policy_id`
- `industry_id`
- `required_source_document_types`
- `require_latest_approved`
- `require_effective_date_valid`
- `allowed_draft_sources`
- `obsolete_source_behavior`
- `contradiction_check_required`
- `citation_requirement`

Default behavior:
- Customer-facing or sales-facing drafts must cite latest approved and effective source documents where required.
- Obsolete documents cannot be used as formal evidence for definitive statements.
- Draft sources may be used only as reference/candidate material unless explicitly allowed by the policy.
- Contradiction checks should compare draft statements against required source document types.

### ComplianceReviewPolicy

ComplianceReviewPolicy defines review requirements for regulated artifacts.

- `policy_id`
- `industry_id`
- `review_required_artifact_types`
- `reviewer_roles`
- `review_states`
- `auto_approve_allowed` false by default
- `required_review_fields`
- `audit_required`
- `retention_required`

Default review states:
- `draft`
- `in_review`
- `changes_requested`
- `compliance_approved`
- `business_approved`
- `rejected`
- `archived`

### MarketingMaterialPolicy

MarketingMaterialPolicy defines consistency and prohibited-expression checks for marketing or sales materials.

- `policy_id`
- `industry_id`
- `applicable_document_types`
- `source_consistency_required`
- `risk_disclosure_required`
- `prohibited_expression_rules`
- `performance_claim_rules`
- `review_required`
- `citation_required`

Default check areas:
- consistency with prospectus, product disclosure, terms, fees, risks, investment policy, benchmark, and performance period
- risk disclosure presence
- performance claim source and time period
- prohibited or unsupported expressions
- latest approved source usage

### RecordRetentionPolicy

RecordRetentionPolicy defines retention and export requirements for regulated workflows and artifacts.

- `policy_id`
- `industry_id`
- `event_types`
- `artifact_types`
- `retention_period`
- `export_required`
- `tamper_evidence_required`
- `pii_redaction_policy`
- `legal_hold_supported` optional

Record retention must integrate with 001 audit and storage controls. 010 defines the policy contract; implementation details are handled in plan and platform services.

### RegulatedDraftArtifact

RegulatedDraftArtifact is an extension pattern over the common DraftArtifact model. It does not replace DraftArtifact.

- `artifact_id`
- `industry_id`
- `artifact_type`
- `status`
- `compliance_review_status`
- `reviewer_id` or `reviewer_group`
- `source_citations`
- `source_document_ids`
- `disclosure_evidence_ids`
- `generated_at`
- `template_id`
- `audit_log_ref`
- `retention_policy_ref`

Rules:
- RegulatedDraftArtifact must start as `draft`.
- `auto_approve_allowed` is false by default.
- Compliance review transitions must be audited.
- Disclosure evidence must remain traceable to source citations and source documents.

### FinancialRiskDecision

FinancialRiskDecision is a financial/regulatory extension example for RiskDecision. It does not replace the common RiskDecision model.

- `risk_decision_id`
- `query_id`
- `industry_id`
- `risk_categories`
- `advice_boundary_triggered`
- `regulated_activity_triggered`
- `marketing_material_triggered`
- `compliance_review_required`
- `decision`
- `reason`
- `policy_version`

### Financial / Regulated Hard Rules

- 投資助言、売買推奨、個別顧客への適合性判断、法令判断、規制判断、契約・開示文書の自動確定は、デフォルトで禁止または人間レビュー必須とする。
- AI 生成物は DraftArtifact として作成し、自動 approved にしない。
- 顧客向け資料、販売用資料、運用報告書、RFP / DDQ 回答、照会回答などは、DisclosureEvidencePolicy と ComplianceReviewPolicy の対象にできる。
- high-risk / regulated query では、approved かつ `effective_date` が有効な文書引用がない限り断定回答しない。
- 過去実績、利回り、リスク、手数料、投資方針、運用体制、ESG、パフォーマンス要因に関する記述は、根拠文書と時点を必須にする。
- no-train、audit、ACL、tenant isolation、PII / secret handling は全金融業界 profile に適用する。
- 個人情報、顧客属性、取引情報、口座情報、適合性情報は PII / confidential financial data として扱う。
- 顧客データは opt-in なしにモデル学習・横断改善・別テナント向け改善に使わない。

### Financial / Regulated Non-Goals

- 投資助言の自動提供。
- 売買推奨の自動確定。
- 個別顧客への適合性判断。
- 入出金・発注・売買執行。
- 法令・規制判断の最終判断。
- 開示文書・販売用資料の自動承認。
- コンプライアンスレビューの完全自動化。
- 金融商品取引業務そのものの置き換え。

### Reusable Abstractions for 006

`006-investment-management-mutual-fund-rag` should reuse:
- IndustryProfile
- MetadataSchema
- MetadataFieldDefinition
- DocumentTypeDefinition
- EntityTypeDefinition
- RiskPolicy
- RiskDecision / FinancialRiskDecision
- RequiredEvidencePolicy
- RegulatedActivityPolicy
- AdviceBoundaryPolicy
- DisclosureEvidencePolicy
- ComplianceReviewPolicy
- MarketingMaterialPolicy
- RecordRetentionPolicy
- ApprovalPolicy
- ACLMappingPolicy
- DraftArtifact / RegulatedDraftArtifact
- DraftArtifactTypeDefinition
- DraftReviewPolicy
- WorkflowDefinition
- WorkflowInputSchema
- WorkflowOutputSchema
- KPIDefinition
- DashboardWidgetDefinition
- PromptTemplateSet
- EvaluationProfile
- GovernanceProfile
- NoTrainPolicy / NoTrainPolicyRef
- AuditEventDefinition

### Financial Extension Clarifications

No blocking NEEDS CLARIFICATION for this spec-level extension. Before `/speckit-plan`, confirm at most:

1. Whether regulated policy objects are global financial templates, per-industry profiles, or both.
2. Whether compliance review states are unified across financial profiles or configurable per customer.
3. Whether marketing material contradiction checks are deterministic rule checks, LLM-assisted checks, or hybrid.
4. Whether record retention periods are configured by industry profile, customer policy, or document type.
5. Whether customer-facing outputs are entirely out of MVP or allowed only as reviewed exports.

## Future Industry Spec Template

```markdown
# Feature Specification: <industry-name> Knowledge RAG

## Relationship to 001 and 010

This spec uses `001-rag-platform` and `010-industry-solution-framework`.
It does not redefine 001 or 010.

## Target Industry

<業界名>

## Business Scope

<業務範囲>

## Target Users

<ユーザー>

## Main Documents

<文書種別>

## Main Metadata

<metadata>

## Entity Types

<entities>

## High-Risk Categories

<リスク分類>

## Required Evidence Policy

<承認済み・有効文書引用、draft/obsolete扱い、根拠不足時挙動>

## Main Workflows

<workflow>

## DraftArtifact Types

<draft types>

## KPI and Dashboard

<KPI>

## ACL Mapping

<業界metadataを001 ACL / metadata filterへmapping>

## PII / Governance / No-Train / Audit

<個人情報、no-train、監査、保持、provider governance>

## API Candidates

<industry-specific APIs>

## Success Criteria

<SC>

## Non-goals

<非ゴール>

## Open Questions Before /speckit-plan

最大5件。
```

## Example: 004 Construction Starting Points

- `industry_id`: `construction`
- metadata examples: `project_id`, `site_id`, `contractor_id`, `drawing_id`, `rfi_id`, `change_order_id`, `inspection_category`, `safety_category`
- document examples: drawing, specification, RFI, inspection report, safety instruction, daily report, change order, meeting minutes
- risk examples: safety instruction, structural decision, change order cost, regulatory compliance, official client response
- workflow examples: RFI investigation, drawing/spec question, site report draft, inspection checklist draft, change order summary draft
- draft examples: `rfi_reply`, `site_report`, `inspection_checklist`, `change_order_summary`, `safety_notice`
- KPI examples: `rfi_response_time_reduction`, `site_report_draft_count`, `safety_query_count`, `change_order_lookup_count`

## Example: 005 Customer Support Starting Points

- `industry_id`: `customer_support`
- metadata examples: `product_id`, `account_id`, `ticket_id`, `issue_category`, `sla_tier`, `region`, `language`, `escalation_level`
- document examples: knowledge base article, ticket history, release note, troubleshooting guide, policy, incident report, escalation memo
- risk examples: refund commitment, legal complaint, security incident, privacy disclosure, enterprise SLA breach
- workflow examples: customer reply draft, escalation summary, KB article draft, incident update draft, similar ticket investigation
- draft examples: `customer_reply`, `escalation_summary`, `kb_article_draft`, `incident_update`, `refund_explanation`
- KPI examples: `first_contact_resolution_rate`, `average_handle_time_reduction`, `deflection_rate`, `escalation_rate`, `kb_gap_topics`

## Success Criteria

- **SC-ISF-001**: 002 manufacturing の主要要件を IndustryProfile / MetadataSchema / RiskPolicy / WorkflowDefinition / DraftArtifactTypeDefinition / KPIDefinition にマッピングできる。
- **SC-ISF-002**: 003 real estate の主要要件を同じ framework にマッピングできる。
- **SC-ISF-003**: 新しい業界を追加する時、001-rag-platform を変更せずに industry profile を定義できる。
- **SC-ISF-004**: high-risk query は業界ごとの RiskPolicy により判定できる。
- **SC-ISF-005**: RequiredEvidencePolicy により、承認済み文書引用がない場合の断定回答を防げる。
- **SC-ISF-006**: DraftArtifact は業界ごとの `artifact_type` を持ち、自動 approved にならない。
- **SC-ISF-007**: dashboard は共通 KPI と業界固有 KPI を表示できる。
- **SC-ISF-008**: no-train、audit、ACL、tenant isolation は全業界で適用できる。
- **SC-ISF-009**: 業界固有 metadata の schema versioning ができる。
- **SC-ISF-010**: 業界 profile の変更が既存 industry profile を壊さない。

## Non-Goals

- 全業界の完全な業務仕様をこの framework で定義すること。
- 001-rag-platform の再実装。
- 業界固有 UI の詳細実装。
- 法的判断、医療判断、金融判断、与信判断の自動確定。
- 電子署名。
- フル DMS。
- 顧客の基幹システム置き換え。
- 業界固有の規制準拠をこの framework だけで保証すること。

## Clarify Prompt Guidance

`/speckit-plan` 前に `/speckit.clarify` を行う場合は、次の論点から最大 5 件に絞って確認する。

1. IndustryProfile をコード設定として持つか、DB 上の設定として持つか、または両方にするか。
2. 業界固有 metadata を JSONB 中心にするか、正規化テーブル中心にするか、ハイブリッドにするか。
3. 業界別 workflow を汎用 API で実行するか、業界別専用 API を作るか。
4. RiskPolicy を rule-based 中心にするか、LLM 分類を含めるか、両方にするか。
5. DraftArtifact を全業界共通テーブルにするか、業界ごとに拡張テーブルを持つか。
6. KPI 定義を設定可能にするか、コード実装中心にするか。
7. 002 manufacturing と 003 real estate を 010 に移行する範囲はどこまでにするか。
8. 010 は runtime framework として実装するのか、solution spec template として扱うのか。
9. 業界 profile の schema version migration を MVP でどこまで扱うか。
10. no-train / audit / governance を 010 で共通定義する範囲と、001 に委譲する範囲。

## Plan Prompt Guidance

`/speckit-plan` では、010 を業界別 solution layer の共通 framework として実装計画化する。001 を再実装せず、002 manufacturing と 003 real estate がこの framework に乗ることを前提にする。

Plan で必ず扱うこと:

1. 001 との境界。
2. 010 の service composition。
3. data model。
4. API contracts。
5. 002 manufacturing mapping。
6. 003 real estate mapping。
7. industry profile 追加手順。
8. schema versioning。
9. risk policy evaluation flow。
10. draft artifact review flow。
11. dashboard / KPI flow。
12. audit / no-train / governance flow。
13. testing strategy。
14. migration strategy。
15. MVP 範囲と将来拡張。

Suggested services:
- IndustryProfileService
- MetadataSchemaService
- IndustryDocumentEnrichmentService
- IndustryRiskPolicyService
- RequiredEvidencePolicyService
- IndustryWorkflowService
- DraftArtifactService
- DraftReviewService
- IndustryKPIService
- IndustryDashboardService
- IndustryGovernanceService

## Open Questions Before /speckit-plan

1. **Profile storage**: IndustryProfile / RiskPolicy / WorkflowDefinition / KPI definitions は DB-managed runtime config と seed data の hybrid にするか。
   - Recommended default: seed data で初期 profile を提供し、DB 上で versioned active profile として管理する。
2. **Metadata storage**: 業界固有 metadata は JSONB + schema validation を基本にし、検索頻度の高い fields を index 化する hybrid でよいか。
   - Recommended default: JSONB + promoted indexed columns / generated indexes。
3. **Workflow API shape**: MVP では common `/industries/...` API を内部/admin向けに提供し、業界 spec では domain-friendly API を別途定義するか。
   - Recommended default: 両方を許容し、外部 UX は業界別 API を優先する。
4. **Risk classification**: RiskPolicy は rule-based を必須、LLM classifier を optional にするか。
   - Recommended default: rule-based + optional LLM classification。曖昧な場合は high-risk または review_required。
5. **DraftArtifact storage**: DraftArtifact は共通テーブル + industry payload JSONB を基本にし、必要時だけ業界 extension table を追加するか。
   - Recommended default: shared table + schema-validated JSONB payload。

## Confirmation

- 010 は `001-rag-platform` を再定義しない。001 は Base RAG Platform のまま、tenant isolation、ACL、ingestion、retrieval、answer、citation、groundedness、evaluation、cost、audit、visual RAG、parser abstraction、no-train provider config を提供する。
- 010 は `002-manufacturing-field-knowledge-rag` を壊さない。製造業の意味論は 002 に残し、010 は mapping 可能な共通型だけを提供する。
- 010 は `003-real-estate-property-management-rag` を壊さない。不動産管理の意味論は 003 に残し、010 は mapping 可能な共通型だけを提供する。
