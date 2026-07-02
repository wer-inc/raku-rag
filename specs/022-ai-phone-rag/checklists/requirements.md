# Requirements Checklist: AI Phone RAG Contact Center

**Feature**: `022-ai-phone-rag`

**Date**: 2026-06-28

## Spec Completeness

- [x] Primary user value is described in one sentence.
- [x] MVP scope is explicitly bounded.
- [x] Out-of-scope / later phases are identified.
- [x] User stories are independently testable and prioritized.
- [x] Acceptance scenarios cover answerable calls, insufficient evidence, human handoff, scenario operation, call history, QA, and metrics.
- [x] Edge cases include low ASR confidence, barge-in, human request, stale evidence, provider failure, PII, and high-risk inquiries.
- [x] Requirements are written as product behavior, not implementation tasks.
- [x] Success criteria are measurable.

## Constitution Alignment

- [x] Groundedness-first behavior is explicit.
- [x] Traceability fields are required for AI answers.
- [x] Tenant/ACL security is required before retrieval, answer, history, export, and handoff.
- [x] Telephony/ASR/TTS/CRM/handoff are pluggable provider interfaces.
- [x] Evaluation and KPI gates are part of the feature.
- [x] Observability and correlation IDs are required across all stages.
- [x] API-first contract is drafted.
- [x] Data lifecycle covers retention, deletion, versioning, and rollback scope.

## Clarifications / Open Questions

- [x] Choose first production telephony provider target. (Amazon Connect — decided 2026-07-02, see `specs/024-phone-live-telephony/research.md` Decision 1.)
- [x] Decide whether MVP persists audio recording or transcript-only history: product MVP is transcript-first; recording is optional by tenant policy.
- [x] Decide initial operator console target: product MVP uses built-in handoff queue/detail stub.
- [x] Decide first CRM/order/reservation lookup integration for MVP: deterministic stub or existing demo data only.
- [x] Decide whether identity verification is excluded from MVP or included as a limited scripted flow: complex verification is excluded; identity-required cases hand off when scripted hints are insufficient.
- [ ] Choose first production CRM/order/reservation integration target, if any.

## Risk Notes

- [x] Live/billed provider calls are not required for Tier A.
- [x] High-risk inquiries are transfer/block, not self-service in MVP.
- [x] Card/payment handling is out of MVP unless PCI-specific design is added.
- [x] Human-requested handoff is a hard rule.
- [x] Provider failure has fail-closed fallback semantics.
