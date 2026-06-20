# Tasks: Real Estate Property Management Knowledge RAG

## Phase 1 - Profile and Metadata

- [X] RE-T001 Define 010 Real Estate IndustryProfile seed.
- [X] RE-T002 Define RealEstate MetadataSchema and indexed fields.
- [X] RE-T003 Implement real estate metadata import/enrichment API.
- [X] RE-T004 Add validation tests for property/unit/lease/repair metadata.

## Phase 2 - Domain Data Model

- [X] RE-T010 Add migrations for Property, Building, Unit, Owner, Occupant, LeaseContract, LeaseTerm, PropertyManagementAgreement, RepairCase, MaintenanceRequest, InspectionReport, Vendor, Estimate, Invoice, MoveOutCase, RestorationCase, InquiryCase, OwnerReport.
- [X] RE-T011 Add ACL mapping for branch, department, property, building, unit, owner, document type, approval status, and personal data category.
- [X] RE-T012 Add tenant isolation tests for property/unit/contract/occupant data.

## Phase 3 - Risk and Evidence

- [X] RE-T020 Implement RealEstateRiskGateService using 010 RiskPolicy and RequiredEvidencePolicy.
- [X] RE-T021 Add high-risk tests for contract conditions, cost responsibility, move-out settlement, restoration, legal risk, personal data disclosure, official customer response.
- [X] RE-T022 Add tests requiring approved/effective citations and blocking draft/obsolete formal evidence.

## Phase 4 - Workflows

- [X] RE-T030 Implement contract-question workflow.
- [X] RE-T031 Implement repair-investigation workflow.
- [X] RE-T032 Implement occupant-reply-draft workflow.
- [X] RE-T033 Implement owner-report-draft workflow.
- [X] RE-T034 Implement move-out-checklist-draft and restoration-explanation-draft workflows.

## Phase 5 - Draft Review

- [X] RE-T040 Implement RealEstateDraftArtifact payload schemas and artifact types.
- [X] RE-T041 Implement review assignment and status transition APIs.
- [X] RE-T042 Add no-auto-approval tests for AI-generated artifacts.
- [X] RE-T043 Add audit tests for draft generation, review assignment, and status transition.

## Phase 6 - Dashboard / KPI / Governance

- [X] RE-T050 Implement RealEstateKPI calculations from audit/feedback/draft/evaluation sources.
- [X] RE-T051 Implement real estate dashboard widgets.
- [X] RE-T052 Implement governance status API.
- [X] RE-T053 Add dashboard ACL leakage tests and personal-data minimal-display tests.

## Phase 7 - Contracts / PoC

- [X] RE-T060 Add OpenAPI contract tests for all `/real-estate/...` endpoints.
- [X] RE-T061 Build PoC dataset and acceptance tests for property contract question, repair lookup, occupant reply draft, owner report draft, and dashboard KPI.

## Requirement Traceability

- RE-T001 to RE-T004 cover FR-RE-001a, FR-RE-010 to FR-RE-015, RealEstateDocumentMetadata, 010 profile mapping, and metadata validation.
- RE-T010 to RE-T012 cover Property, Building, Unit, Owner, Occupant/Lessee, LeaseContract, RepairCase, InquiryCase, OwnerReport, ACL mapping, tenant isolation, and personal data boundaries.
- RE-T020 to RE-T022 cover FR-RE-020 to FR-RE-030, high-risk categories, approved/effective citation requirements, obsolete/draft evidence restrictions, and insufficient evidence behavior.
- RE-T030 to RE-T034 cover contract question, repair investigation, occupant reply draft, owner report draft, move-out checklist draft, and restoration explanation draft workflows.
- RE-T040 to RE-T043 cover RealEstateDraftArtifact, RealEstateDraftReview, no auto approval, review transition, and audit events.
- RE-T050 to RE-T053 cover dashboard, KPI, governance status, personal data redaction, ACL leakage prevention, and PoC KPI.
- RE-T060 to RE-T061 cover API contracts and PoC acceptance scenarios for the real estate vertical slice.

## Gap Remediation Backlog — design-vs-implementation audit (2026-06-20)
- [ ] GAP-F14 [func] domain-table RLS UNTESTED across 003/004/005/006 (FR-RE-062/063, FR-IM-071/072, SC-RE-003/SC-IM-005): no live-Postgres cross-tenant test exercises real_estate_*/investment_*/industry_profile RLS; the only CI-wired live-DB gate (gate.sh b) applies ONLY 0001_core_rls.sql; postgres-migration-smoke.sh applies 0003-0006 but is not CI-wired and asserts isolation only on `documents`. FORCE RLS on the domain tables is verified only by SQL-text grep. → add a Tier-B cross-tenant test over the domain tables (apply 0003-0005, set current_tenant_id=A, assert tenant B sees 0 rows).
