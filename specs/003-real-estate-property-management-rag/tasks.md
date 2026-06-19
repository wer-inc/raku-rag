# Tasks: Real Estate Property Management Knowledge RAG

## Phase 1 - Profile and Metadata

- [ ] RE-T001 Define 010 Real Estate IndustryProfile seed.
- [ ] RE-T002 Define RealEstate MetadataSchema and indexed fields.
- [ ] RE-T003 Implement real estate metadata import/enrichment API.
- [ ] RE-T004 Add validation tests for property/unit/lease/repair metadata.

## Phase 2 - Domain Data Model

- [ ] RE-T010 Add migrations for Property, Building, Unit, Owner, Occupant, LeaseContract, LeaseTerm, PropertyManagementAgreement, RepairCase, MaintenanceRequest, InspectionReport, Vendor, Estimate, Invoice, MoveOutCase, RestorationCase, InquiryCase, OwnerReport.
- [ ] RE-T011 Add ACL mapping for branch, department, property, building, unit, owner, document type, approval status, and personal data category.
- [ ] RE-T012 Add tenant isolation tests for property/unit/contract/occupant data.

## Phase 3 - Risk and Evidence

- [ ] RE-T020 Implement RealEstateRiskGateService using 010 RiskPolicy and RequiredEvidencePolicy.
- [ ] RE-T021 Add high-risk tests for contract conditions, cost responsibility, move-out settlement, restoration, legal risk, personal data disclosure, official customer response.
- [ ] RE-T022 Add tests requiring approved/effective citations and blocking draft/obsolete formal evidence.

## Phase 4 - Workflows

- [ ] RE-T030 Implement contract-question workflow.
- [ ] RE-T031 Implement repair-investigation workflow.
- [ ] RE-T032 Implement occupant-reply-draft workflow.
- [ ] RE-T033 Implement owner-report-draft workflow.
- [ ] RE-T034 Implement move-out-checklist-draft and restoration-explanation-draft workflows.

## Phase 5 - Draft Review

- [ ] RE-T040 Implement RealEstateDraftArtifact payload schemas and artifact types.
- [ ] RE-T041 Implement review assignment and status transition APIs.
- [ ] RE-T042 Add no-auto-approval tests for AI-generated artifacts.
- [ ] RE-T043 Add audit tests for draft generation, review assignment, and status transition.

## Phase 6 - Dashboard / KPI / Governance

- [ ] RE-T050 Implement RealEstateKPI calculations from audit/feedback/draft/evaluation sources.
- [ ] RE-T051 Implement real estate dashboard widgets.
- [ ] RE-T052 Implement governance status API.
- [ ] RE-T053 Add dashboard ACL leakage tests and personal-data minimal-display tests.

## Phase 7 - Contracts / PoC

- [ ] RE-T060 Add OpenAPI contract tests for all `/real-estate/...` endpoints.
- [ ] RE-T061 Build PoC dataset and acceptance tests for property contract question, repair lookup, occupant reply draft, owner report draft, and dashboard KPI.

## Requirement Traceability

- RE-T001 to RE-T004 cover FR-RE-001a, FR-RE-010 to FR-RE-015, RealEstateDocumentMetadata, 010 profile mapping, and metadata validation.
- RE-T010 to RE-T012 cover Property, Building, Unit, Owner, Occupant/Lessee, LeaseContract, RepairCase, InquiryCase, OwnerReport, ACL mapping, tenant isolation, and personal data boundaries.
- RE-T020 to RE-T022 cover FR-RE-020 to FR-RE-030, high-risk categories, approved/effective citation requirements, obsolete/draft evidence restrictions, and insufficient evidence behavior.
- RE-T030 to RE-T034 cover contract question, repair investigation, occupant reply draft, owner report draft, move-out checklist draft, and restoration explanation draft workflows.
- RE-T040 to RE-T043 cover RealEstateDraftArtifact, RealEstateDraftReview, no auto approval, review transition, and audit events.
- RE-T050 to RE-T053 cover dashboard, KPI, governance status, personal data redaction, ACL leakage prevention, and PoC KPI.
- RE-T060 to RE-T061 cover API contracts and PoC acceptance scenarios for the real estate vertical slice.
