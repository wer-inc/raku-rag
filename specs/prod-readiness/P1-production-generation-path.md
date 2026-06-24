# P1-0 Decision — where production generation/rerank/guardrail run

**Status**: Decided (P1-0, design-only — no behaviour change). Unblocks P1-1..P1-5.
**Context**: the audit found the deployed answer path generates in the **Python** answer-service
(`ProductionSystem.answer` → `AnswerService` → `self.llm.generate`, `src/raku_rag/production.py:82`
hardcodes `ExtractiveLLMProvider`), while the NestJS `BedrockClaudeService` /
`BedrockCohereRerankService` / `BedrockGuardrailsAdapter` (`apps/api/src/...`, registered in
`app.module.ts:48-56`) are **dead-wired** (no controller injects them; runtime invokers unbound).

## Decision

Production **text generation, rerank, and the output guardrail run in the Python composition root**
(`ProductionSystem`), selected by settings — NOT moved into NestJS. The NestJS controllers stay thin
proxies; generation logic is not duplicated across the TS/Python boundary.

Concretely, mirror the **existing** `embedding_provider_from_settings(settings)` factory pattern
(`src/raku_rag/providers/embeddings.py`) for the other seams:

| Seam | Deterministic default (today) | Production (profile=production) | New factory |
| --- | --- | --- | --- |
| LLM generation | `ExtractiveLLMProvider` (`production.py:82`) | `BedrockClaudeLLMProvider` (impl of `LLMProvider`, `interfaces/base.py:75`) — Bedrock Converse over the authorized context chunks, model id from env (Japan CRIS `jp.anthropic.claude-…`) | `llm_provider_from_settings(settings)` (new) |
| Rerank | `ScoreOrderReranker` (`production.py:81`) | `BedrockCohereReranker` (impl of `Reranker`) — `cohere.rerank-v3-5:0` | `reranker_from_settings(settings)` (new) |
| Output guardrail | none (stdlib `PromptInjectionGuard` still fires) | `BedrockGuardrailProvider` invoked post-generation, pre-return | `guardrail_from_settings(settings)` (new) |
| Embeddings | `HashingEmbeddingProvider` 256 | `CohereEmbedMultilingualV3Provider` 1024 (already exists under `workers/ingest/...`) | `embedding_provider_from_settings` (exists) |

Selection key: `RAKU_RUNTIME_PROFILE = deterministic | production` (default `deterministic`) plus the
already-present `RAKU_EMBEDDING_PROVIDER`. Under `production`, each factory returns the real adapter and
**fails closed** if its runtime/credentials are unconfigured (never silently returns a stub).

## Rationale

- **Layering / ADR-006 (no logic split):** retrieval → ACL pre-filter → grounding gate → generation →
  citation → safety overlay is composed in Python. Moving generation into NestJS would duplicate that
  orchestration across the boundary and split the safety-bearing path. The audit explicitly said to
  preserve the "production-architected" contracts and reach production by **wiring + config**.
- **The NestJS Bedrock services are in the wrong layer for *answer generation*.** They are retained
  only for NestJS-side helper tasks (the `BedrockClaudeService` already routes by `task` —
  classification/enrichment/summarization/high_risk_assistance) and as a secondary boundary; they are
  **not** the answer generator. The answer generator is the Python `LLMProvider`.
- **Pluggable (Constitution IV):** new providers sit behind the existing `LLMProvider` / `Reranker`
  interfaces; the deterministic providers remain the offline default so Tier-A stays stdlib-fast.

## Consequences / what P1-1..P1-5 implement

- **P1-1**: add `RAKU_RUNTIME_PROFILE` to `core/config.py` + `llm_provider_from_settings` /
  `reranker_from_settings` / `guardrail_from_settings`; `production.py` uses the factories instead of the
  hardcoded `ExtractiveLLMProvider()` / `ScoreOrderReranker()`. Deterministic default ⇒ no Tier-A change.
- **P1-2**: `BedrockClaudeLLMProvider` (Python, boto3 bedrock-runtime Converse; `anthropic_version`
  `bedrock-2023-05-31`; image/text content; cost+trace records). verify_live needs real Bedrock ⇒
  `blocked-needs-infra` in this environment; offline unit test uses a mock invoker.
- **P1-3/P1-4**: `BedrockCohereReranker` + `BedrockGuardrailProvider` (Python) behind the same seams;
  offline mock-invoker tests; live ⇒ `blocked-needs-infra`.
- **P1-5**: emit a Langfuse trace per answer from the Python answer flow (the tracer seam already
  exists: `production.py` `self.tracer`/`self.telemetry_exporter`); live needs a Langfuse endpoint.
- **P1-6**: embedding switch + reindex — **billed, human gate**.

## Non-goals
- No behaviour change in this decision; deterministic profile and Tier-A remain the default and untouched.
- Not deleting the NestJS Bedrock services (kept for helper tasks / boundary), just not making them the
  answer generator.
