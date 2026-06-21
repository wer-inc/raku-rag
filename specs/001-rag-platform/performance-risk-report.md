# RAG Performance Risk Report

## Summary

- Overall risk: MEDIUM
- Biggest bottleneck: multi-step synchronous LLM calls if query rewrite, HyDE, answer generation, citation validation, and LLM judge are chained in one request.
- Most urgent fix: add request-level hot-path observability before optimizing behavior.

This report is scoped to `specs/001-rag-platform` and the current Python/NestJS contracts. The first patch intentionally records latency/count/token metrics only; rerank/context enforcement and load-test gates are separate follow-up tasks.

## Architecture Hot Path

1. API verifies tenant/app and signed end-user claims.
2. Budget gate checks tenant/collection/query allowance.
3. Query embedding is generated for retrieval.
4. Vector store searches with tenant, ACL, tombstone, and metadata pre-filtering.
5. RetrievalService reasserts ACL as a fail-closed double check.
6. Optional reranker reranks a bounded candidate set.
7. Groundedness pre-gate checks score threshold and minimum evidence count.
8. Prompt/context is built from authorized evidence only.
9. LLM or VLM generates the answer.
10. Post-generation evidence check rejects unsupported claims.
11. Citations, cost, audit, trace, stage metrics, and hot-path metrics are recorded.

Estimated external work per normal text answer: one query embedding call, one vector DB call, zero or one reranker call, one generation LLM call, and no synchronous LLM judge by default. Token pressure comes mainly from context construction and generation.

## Findings

| Priority | Finding | Evidence | Why it is slow | Verification | Fix |
|---|---|---|---|---|---|
| P0 | Missing request-level RAG metric | Stage metrics exist, but request hot path lacked retrieval/rerank/generation/token breakdown | A single total/stage metric cannot identify bottlenecks | Assert request metrics include required fields per correlation ID | Add RagHotPathMetric and answer-path recording |
| P0 | Multi-step synchronous LLM calls remain a design risk | QueryProfile exposes query rewrite/self-eval flags and design mentions post-check/judge | LLM calls compound p95/p99 and provider rate-limit failures | Track llm_call_count per request and load-test profile variants | Default max_synchronous_llm_calls=1; make extra calls conditional or async |
| P0 | Rerank/context caps need to be explicit contracts | RetrievalProfile had candidate/final limits; QueryProfile lacked context/LLM call budget | Reranker and prompt token growth can dominate latency/cost | Record rerank_input_count/context_tokens and test profile fields | Add max_context_tokens/chunks and rerank candidate limit to contracts |
| P0 | ACL/tenant/metadata filter pushdown is performance and security critical | Spec already requires ACL pre-filter and vector-only default is forbidden | Post-filter-only search fetches and discards large candidate sets | EXPLAIN/query plan, filtered_out_count, tenant/RLS tests | Keep DB/index pre-filter as production readiness gate |
| P1 | Ingestion/embedding must stay out of answer request path | Design separates asynchronous ingestion, but regression risk remains | Embedding/reindex work in hot path blocks users | Trace API handler calls and job boundaries | Keep ingestion/reindex in workers/control plane only |
| P1 | Caching needs tenant/user/permission/index-version keys | Cost strategy mentions cache, but unsafe keys can leak or serve stale context | Bad cache keys create security bugs or stale answers | Cache hit metrics plus security cache tests | Include tenant, user/permission scope, profile, and index/document version in keys |
| P2 | Load tests must use tail latency, not average only | Existing gates mention p95; p99 and queue time need explicit coverage | Average latency hides rate-limit and long-tail failures | k6/Locust/Python synthetic scenarios | Add p50/p95/p99, queue time, error rate gates |

## Required Metrics

- request_id
- hashed tenant_id and user_id
- profile_id and status
- llm_call_count
- retrieval_ms
- rerank_ms
- generation_ms
- total_ms
- retrieved_chunks
- rerank_input_count
- context_tokens
- prompt_tokens
- completion_tokens
- cache_hit
- p50/p95/p99 rollups by tenant/profile/status
- provider rate-limit/error counters
- cache hit rate keyed by tenant/profile/index version

## Spec Kit Updates

- Add CR `RAG performance guardrails` to `spec.md`.
- Add FR-010a, FR-011a, FR-017a-c, and FR-029a-c.
- Add QueryProfile caps: `max_synchronous_llm_calls`, `max_context_tokens`, `max_context_chunks`.
- Add RetrievalProfile cap: `max_context_tokens`.
- Add RAG performance budget defaults to `plan.md`.
- Add `RagHotPathMetric` payload to `data-model.md`.
- Add admin API contract fields for QueryProfile/RetrievalProfile.
- Add P0/P1 tasks T112-T120.

## Implementation Tasks

| Priority | Task |
|---|---|
| P0 | Add request-level hot-path metric recording in MetricsRecorder and AnswerService. |
| P0 | Split retrieval_ms and rerank_ms in RetrievalService spans. |
| P0 | Add performance budget fields to QueryProfile, Settings, shared DTOs, and OpenAPI. |
| P0 | Add max_context_tokens to RetrievalProfile contract and defaults. |
| P1 | Add unit/integration/contract tests for metrics and schema fields. |
| P1 | Add load-test scenario for p50/p95/p99 and high concurrency. |
| P1 | Verify filter pushdown and ANN/metadata indexes before production readiness. |
| P1 | Move LLM judge/deep citation validation out of default synchronous hot path. |

## First Patch

The first patch prioritizes observability, not feature expansion. It records:

- request_id
- user_id/tenant_id hash
- llm_call_count
- retrieval_ms
- rerank_ms
- generation_ms
- total_ms
- retrieved_chunks
- rerank_input_count
- context_tokens
- prompt_tokens
- completion_tokens
- cache_hit
