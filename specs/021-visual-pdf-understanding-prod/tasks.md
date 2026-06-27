# Tasks: 021 Visual PDF Understanding

## M1 Planning

- [x] T001 Create implementation plan.
- [x] T002 Create task checklist.
- [x] T003 Keep spec, plan, and task scope aligned after implementation changes.

## M2 Provider-Neutral Foundation

- [x] T010 Add `raku_rag.interfaces.visual` with neutral visual protocols and async analysis models.
- [x] T011 Re-export visual protocols from `raku_rag.interfaces.base`.
- [x] T012 Add visual provider settings to `Settings`.
- [x] T013 Parse visual provider env vars in `settings_from_env()`.
- [x] T014 Add visual provider factories with deterministic defaults.
- [x] T015 Add tests proving production profile does not auto-upgrade visual providers.

## M3 Fake Provider Vertical Slice

- [x] T020 Add fake async document analyzer returning neutral `DocumentAnalysis`.
- [x] T021 Add fake VLM/captioning provider for deterministic local tests.
- [x] T022 Add page-aware visual chunk ids.
- [x] T023 Add executor assembly from neutral page analysis to `VisualIngestionResult`.
- [x] T024 Add tests for multi-page chunk id uniqueness and fake analysis normalization.

## M4 Production Storage And Worker Path

- [x] T030 Add additive Postgres migration for async visual job state and extractor provenance.
- [x] T031 Add production content-type dispatch for PDF/image visual ingestion.
- [x] T032 Add worker branch for async visual jobs.
- [x] T033 Add RLS/deletion/tombstone tests for visual chunks and crops.

## M5 Safety, Audit, And Evaluation

- [x] T040 Extend visual citation metadata fields through Python, TS DTOs, and OpenAPI.
- [x] T041 Keep visual citations reference-only while `visual_evidence_promotion=False`.
- [x] T042 Add grounding subset verifier for visual promotion.
- [x] T043 Add independent VLM verifier quorum.
- [x] T044 Add audit records for denied and approved visual promotion decisions.
- [x] T045 Add eval metrics/fixtures for visual recall, citation accuracy, bbox IoU, and grounding.

## M6 Live AWS Opt-In

- [ ] T050 Add AWS Textract OCR/layout/structured adapters.
- [ ] T051 Add AWS Textract async document analyzer.
- [ ] T052 Add Bedrock vision VLM/captioning adapters.
- [ ] T053 Gate all real provider calls with ProviderPolicy before bytes egress.
- [ ] T054 Wire CDK env/IAM for explicit provider opt-in.
- [ ] T055 Add live smoke runbook and keep live calls human-approved.
