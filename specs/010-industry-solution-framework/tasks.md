# Tasks: Industry Solution Framework

## Phase 1 - Foundations

- [ ] ISF-T001 Define database migrations for IndustryProfile, MetadataSchema, DocumentTypeDefinition, EntityTypeDefinition, WorkflowDefinition, RiskPolicy, RequiredEvidencePolicy, ApprovalPolicy, ACLMappingPolicy, DraftArtifactTypeDefinition, DraftReviewPolicy, KPIDefinition, DashboardWidgetDefinition, GovernanceProfile, AuditEventDefinition, EvaluationProfile.
- [ ] ISF-T002 Implement `IndustryProfileService` with tenant/collection scoped profile resolution.
- [ ] ISF-T003 Implement `MetadataSchemaService` with JSON schema validation, schema versioning, and indexed field declaration.
- [ ] ISF-T004 Add seed profiles for manufacturing, real estate, and investment management without changing their domain semantics.

## Phase 2 - Policy and Workflow

- [ ] ISF-T010 Implement `IndustryRiskPolicyService` with rule-based matching and optional LLM classifier hook.
- [ ] ISF-T011 Implement `RequiredEvidencePolicyService` using 001 citations, approval metadata, effective_date, obsolete/draft state.
- [ ] ISF-T012 Implement `IndustryWorkflowService` that calls 001 retrieval/answer/citation/audit/cost services.
- [ ] ISF-T013 Add uncertain-case behavior tests: high-risk by default where configured.

## Phase 3 - Drafts and Reviews

- [ ] ISF-T020 Implement common DraftArtifact storage with industry-specific payload schema validation.
- [ ] ISF-T021 Implement DraftReviewPolicy allowed transition enforcement.
- [ ] ISF-T022 Add tests proving AI-created artifacts cannot be auto-approved.
- [ ] ISF-T023 Add audit events for draft generation, assignment, review transition, and archive.

## Phase 4 - KPI / Dashboard / Governance

- [ ] ISF-T030 Implement KPIDefinition calculation adapter from audit/feedback/evaluation/draft sources.
- [ ] ISF-T031 Implement DashboardWidgetDefinition rendering API with tenant/ACL filtering.
- [ ] ISF-T032 Implement GovernanceProfile status API delegating provider/no-train/audit facts to 001.
- [ ] ISF-T033 Add dashboard/KPI leakage tests across tenant, role, and industry filters.

## Phase 5 - Regulated Extensions

- [ ] ISF-T040 Implement RegulatedActivityPolicy and AdviceBoundaryPolicy contracts.
- [ ] ISF-T041 Implement DisclosureEvidencePolicy and ComplianceReviewPolicy definitions.
- [ ] ISF-T042 Implement RecordRetentionPolicy contract hooks to 001 retention/audit/export controls.
- [ ] ISF-T043 Add 006 investment management compatibility tests.

## Phase 6 - Contracts and Compatibility

- [ ] ISF-T050 Implement generic `/industries` APIs and contract tests.
- [ ] ISF-T051 Add mapping tests for 002 manufacturing profile.
- [ ] ISF-T052 Add mapping tests for 003 real estate profile.
- [ ] ISF-T053 Add mapping tests for 006 investment management profile.
- [ ] ISF-T054 Add migration/versioning tests ensuring profile changes do not break existing industries.

## Requirement Traceability

- ISF-T001 to ISF-T004 cover spec MVP concepts for IndustryProfile, MetadataSchema, DocumentTypeDefinition, EntityTypeDefinition, versioning, indexed fields, and profile mapping SC-ISF-001/002/003/010.
- ISF-T010 to ISF-T013 cover RiskPolicy, RiskDecision, RequiredEvidencePolicy, high-risk detection, uncertain-case behavior, and SC-ISF-004/005.
- ISF-T020 to ISF-T023 cover DraftArtifact, DraftArtifactTypeDefinition, DraftReviewPolicy, no-auto-approval, and SC-ISF-006.
- ISF-T030 to ISF-T033 cover KPIDefinition, DashboardWidgetDefinition, GovernanceProfile, ACL/no-train/audit inheritance, and SC-ISF-007/008.
- ISF-T040 to ISF-T043 cover financial/regulated extensions used by 006.
- ISF-T050 to ISF-T054 cover generic APIs, 002/003/006 mapping, version migration, and future industry compatibility.
