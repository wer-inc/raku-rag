# Tasks: Industry Solution Framework

## Phase 1 - Foundations

- [X] ISF-T001 Define database migrations for IndustryProfile, MetadataSchema, DocumentTypeDefinition, EntityTypeDefinition, WorkflowDefinition, RiskPolicy, RequiredEvidencePolicy, ApprovalPolicy, ACLMappingPolicy, DraftArtifactTypeDefinition, DraftReviewPolicy, KPIDefinition, DashboardWidgetDefinition, GovernanceProfile, AuditEventDefinition, EvaluationProfile.
- [X] ISF-T002 Implement `IndustryProfileService` with tenant/collection scoped profile resolution.
- [X] ISF-T003 Implement `MetadataSchemaService` with JSON schema validation, schema versioning, and indexed field declaration.
- [X] ISF-T004 Add seed profiles for manufacturing, real estate, and investment management without changing their domain semantics.

## Phase 2 - Policy and Workflow

- [X] ISF-T010 Implement `IndustryRiskPolicyService` with rule-based matching and optional LLM classifier hook.
- [X] ISF-T011 Implement `RequiredEvidencePolicyService` using 001 citations, approval metadata, effective_date, obsolete/draft state.
- [X] ISF-T012 Implement `IndustryWorkflowService` that calls 001 retrieval/answer/citation/audit/cost services.
- [X] ISF-T013 Add uncertain-case behavior tests: high-risk by default where configured.

## Phase 3 - Drafts and Reviews

- [X] ISF-T020 Implement common DraftArtifact storage with industry-specific payload schema validation.
- [X] ISF-T021 Implement DraftReviewPolicy allowed transition enforcement.
- [X] ISF-T022 Add tests proving AI-created artifacts cannot be auto-approved.
- [X] ISF-T023 Add audit events for draft generation, assignment, review transition, and archive.

## Phase 4 - KPI / Dashboard / Governance

- [X] ISF-T030 Implement KPIDefinition calculation adapter from audit/feedback/evaluation/draft sources.
- [X] ISF-T031 Implement DashboardWidgetDefinition rendering API with tenant/ACL filtering.
- [X] ISF-T032 Implement GovernanceProfile status API delegating provider/no-train/audit facts to 001.
- [X] ISF-T033 Add dashboard/KPI leakage tests across tenant, role, and industry filters.

## Phase 5 - Regulated Extensions

- [X] ISF-T040 Implement RegulatedActivityPolicy and AdviceBoundaryPolicy contracts.
- [X] ISF-T041 Implement DisclosureEvidencePolicy and ComplianceReviewPolicy definitions.
- [X] ISF-T042 Implement RecordRetentionPolicy contract hooks to 001 retention/audit/export controls.
- [X] ISF-T043 Add 006 investment management compatibility tests.

## Phase 6 - Contracts and Compatibility

- [X] ISF-T050 Implement generic `/industries` APIs and contract tests.
- [X] ISF-T051 Add mapping tests for 002 manufacturing profile.
- [X] ISF-T052 Add mapping tests for 003 real estate profile.
- [X] ISF-T053 Add mapping tests for 006 investment management profile.
- [X] ISF-T054 Add migration/versioning tests ensuring profile changes do not break existing industries.

## Requirement Traceability

- ISF-T001 to ISF-T004 cover spec MVP concepts for IndustryProfile, MetadataSchema, DocumentTypeDefinition, EntityTypeDefinition, versioning, indexed fields, and profile mapping SC-ISF-001/002/003/010.
- ISF-T010 to ISF-T013 cover RiskPolicy, RiskDecision, RequiredEvidencePolicy, high-risk detection, uncertain-case behavior, and SC-ISF-004/005.
- ISF-T020 to ISF-T023 cover DraftArtifact, DraftArtifactTypeDefinition, DraftReviewPolicy, no-auto-approval, and SC-ISF-006.
- ISF-T030 to ISF-T033 cover KPIDefinition, DashboardWidgetDefinition, GovernanceProfile, ACL/no-train/audit inheritance, and SC-ISF-007/008.
- ISF-T040 to ISF-T043 cover financial/regulated extensions used by 006.
- ISF-T050 to ISF-T054 cover generic APIs, 002/003/006 mapping, version migration, and future industry compatibility.

## Gap Remediation Backlog — design-vs-implementation audit (2026-06-20)
- [ ] GAP-F13 [func] financial/regulated extension policies declared but NOT applied at runtime (FR-IM-025/026/030/032/054): RegulatedActivityPolicy / AdviceBoundaryPolicy / DisclosureEvidencePolicy / ComplianceReviewPolicy are attached to the investment profile (framework.py:437-494,1640) but never read/evaluated; MarketingMaterialPolicy is not even defined; the investment runtime returns hardcoded text and gates advice via a 4-keyword heuristic. A coarse net still exists (advice blocked, drafts forced to review, generic RequiredEvidence/Risk policies), but the declared policy logic does not govern the FRs. → drive the workflow from the policy objects + behavioral tests; or mark these tasks not-done. **PARTIAL 2026-06-20**: `MarketingMaterialPolicy` defined and now GOVERNS the per-statement marketing check (with GAP-F12); `AdviceBoundaryPolicy` now governs advice gating — OR-merged with the keyword net (FR-IM-025) so the policy applies WITHOUT narrowing coverage (the risk-category check is narrower than the keywords, so replacing would have weakened the advice boundary). REMAINING (kept open): (a) `ComplianceReviewPolicy.review_states` vocab (`changes_requested`/`compliance_approved`) differs from the runtime states (`changes_required`/`approved`) — reconcile before clamping (a naive clamp forces valid states to `pending` and breaks tests); (b) `RegulatedActivityPolicy` restricted/prohibited-action enforcement + full `DisclosureEvidencePolicy` application (the coarse net already forces draft + human review).
