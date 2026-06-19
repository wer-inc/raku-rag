# Risk Register

| ID | Severity | Area | Risk | Mitigation | Owner | Phase | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R-001 | Critical | Security | Cross-tenant data appears in retrieval, answer, citation, dashboard, or audit export | RLS, tenant_id on all records, ACL pre-filter, zero-leakage tests, worker/admin tenant context tests | Platform | Phase 1 | Open |
| R-002 | Critical | Security | ACL is enforced only after retrieval | RetrievalProfile requires pre-filter, contract tests reject post-filter-only behavior | Platform | Phase 1 | Open |
| R-003 | Critical | Deletion | Tombstoned document appears through cache, vector index, citation, or dashboard | Tombstone immediate exclusion, cache invalidation, deleted documents not searchable hard gate | Platform | Phase 1 | Open |
| R-004 | High | Governance | External parser/OCR violates data residency or no-train assumptions | ProviderPolicy opt-in, provider region/capability audit, AWS-only default | Platform | Phase 1/6 | Open |
| R-005 | High | Observability | Raw RAG context or personal data stored in traces | LoggingPolicy default raw context off, redaction, sampling, Langfuse tests | Platform | Phase 1 | Open |
| R-006 | High | Retrieval | Vector-only misses identifiers such as alarm codes, unit IDs, fund codes, ISINs | Metadata exact filter, identifier match, vector search, bounded rerank, benchmark | Platform | Phase 1/6 | Open |
| R-007 | High | Orchestration | Dagster becomes required before MVP or enters online answer path | SQS default, Dagster-compatible state only, ADR-003, boundary tests | Platform | Phase 0/1 | Open |
| R-008 | High | 010 | Over-abstraction hides industry semantics | Keep semantics in 002/003/006, 010 only defines contracts, compatibility tests | Framework | Phase 2 | Open |
| R-009 | High | Drafts | AI-generated artifacts become approved automatically | DraftReviewPolicy, no-auto-approval tests, audit status transition | Framework | Phase 2 | Open |
| R-010 | High | Manufacturing | Dangerous work answer is given without approved safety citation | Safety RiskPolicy, RequiredEvidencePolicy, human review notice, hard-gate tests | 002 | Phase 3 | Open |
| R-011 | High | Real Estate | Contract/cost/restoration answer is overconfident or uses obsolete/draft evidence | RealEstateRiskGate, approved/effective citations, review-required behavior | 003 | Phase 4 | Open |
| R-012 | High | Real Estate | Occupant personal data leaks to unauthorized staff or dashboard | ACLMappingPolicy, redaction, minimal dashboard display, audit | 003 | Phase 4 | Open |
| R-013 | Critical | Investment | Output becomes investment advice, buy/sell recommendation, or suitability judgment | AdviceBoundaryPolicy, prohibited output block, review_required, non-goal tests | 006 | Phase 5 | Open |
| R-014 | High | Investment | Marketing material contradicts prospectus or disclosure documents | DisclosureEvidencePolicy, contradiction checks, compliance review | 006 | Phase 5 | Open |
| R-015 | Medium | Cost | Rerank/OCR/VLM costs exceed PoC budget | CostService, budgets, bounded candidates, OCR/captioning options | Platform | Phase 1/6 | Open |
| R-016 | Medium | Quality | Evaluation datasets are too small or not representative | 20-50 representative docs per industry, baseline regression gates | Product | Phase 6 | Open |
| R-017 | Medium | Operations | SQS-only workflow is hard for backfill/reindex at scale | Keep Dagster-compatible state, introduce Dagster when thresholds are hit | Platform | Phase 6/7 | Open |
| R-018 | Medium | Frontend | Vercel hosting conflicts with residency requirements | Keep Vercel AI SDK optional, AWS-hosted Next.js fallback | Product/Infra | Phase 7 | Open |
| R-019 | Medium | Audit | Base audit model omits industry decision context | AuditLog fields include policy_version, approval_status_at_use, citation_ids; industry AuditEventDefinition extends | Platform/Framework | Phase 1/2 | Open |
| R-020 | Low | DX | Local dev diverges from AWS staging | LocalStack, deterministic mocks, contract tests, staging quality benchmarks | Platform | Phase 0/7 | Open |

## Critical and High Risk Policy

Critical risks must have automated hard-gate tests before implementation is considered releasable. High risks must have an owner, mitigation task, and explicit acceptance criteria before industry vertical slice launch.
