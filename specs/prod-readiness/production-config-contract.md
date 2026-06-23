# Production Config Contract (frozen, 015) — deterministic ⇄ production switch

**Status**: Frozen (P0). Drives `specs/prod-readiness/ledger.json`.
**Principle (audit guardrail)**: keep the production-architected contracts/abstractions; reach production by
**wiring + config**, not rewrite. The **deterministic profile stays the default** so the Tier-A inner loop
(`scripts/gate.sh a`, ~3ms, stdlib-first) never regresses.

## The one switch

`RAKU_RUNTIME_PROFILE = deterministic | production` (default: `deterministic`).

- `deterministic` — current behavior. In-memory/extractive/hashing stack. No cloud calls. Tier-A fast loop.
- `production` — selects the real adapters below. Requires real credentials; absence ⇒ fail-closed (never
  silently fall back to a stub in production profile).

## Switch table (deterministic default → production token)

| Concern | Audit | Deterministic default (today) | Production token to set / bind | Lands as unit |
|---|---|---|---|---|
| Generation (LLM) | AF-1 | `ExtractiveLLMProvider` (`production.py:82`, model `extractive-mvp`) | bind the Bedrock Claude runtime invoker (`BEDROCK_CLAUDE_RUNTIME_INVOKER`) + inject real LLM into the production generation path; model id via `BEDROCK_CLAUDE_SONNET_MODEL_ID` (e.g. Japan CRIS `jp.anthropic.claude-sonnet-4-5-…`) | P1-0, P1-2 |
| Embeddings | AF-2 | `HashingEmbeddingProvider` dim 256 (`RAKU_EMBEDDING_PROVIDER=hashing`, `RAKU_EMBEDDING_DIM=256`) | `RAKU_EMBEDDING_PROVIDER=bedrock_cohere_multilingual_v3` + `RAKU_EMBEDDING_DIM=1024` + reindex | P1-6 (BILLED, human gate) |
| Rerank | AF-3 | `ScoreOrderReranker` (`production.py:81`) | bind `BEDROCK_RUNTIME_INVOKER` for `BedrockCohereRerankService` (`cohere.rerank-v3-5:0`) and invoke in retrieval | P1-3 |
| Output guardrail | AF-4, AF-7 | none live (stdlib `PromptInjectionGuard` still fires) | bind `BEDROCK_GUARDRAILS_RUNTIME` + invoke `BedrockGuardrailsAdapter` on answer output | P1-4 |
| Observability | AF-5 | Langfuse disabled (`LANGFUSE_ENABLED=false`) | `LANGFUSE_ENABLED=true` + host/keys; emit one trace per answer via `LangfuseExporter` | P1-5 |
| Danger classifier | AF-7 | keyword/rule table; stage-3 tie-break = ExtractiveLLM (never clears ⇒ fail-safe high-risk) | real LLM/guardrail danger classification behind the same classifier interface (production profile) | P1-4, P5-1 |
| API↔answer-service trust | AF-9 | loopback plaintext `127.0.0.1:8088`, identity in `x-raku-*` headers | mTLS (or shared secret); answer-service rejects requests without the client cert | P4-4 |
| Embedding/store dim parity | AF-2 | pgvector `vector(256)` | reindex to `vector(1024)` paired with the Cohere switch (fail-fast on mismatch) | P1-6 |

## Invariants that must hold in BOTH profiles (audit "production-architected", do not weaken)

- Deny-by-default ACL pre-filter + tenant isolation (`core/security/acl.py`, `providers/vectorstores.py`).
- Signed-token identity is server-derived; the browser/body never carries tenant/user identity.
- AI output is always `draft`; AI cannot self-approve (`drafts/review.py` `PermissionError`).
- High-risk ⇒ require approved+effective citation or no assertion (`manufacturing/safety/gate.py`).
- No-train opt-in, block-not-degrade (`governance/no_train.py`).
- Tamper-evident SHA-256 hash-chain audit on every safety-bearing decision **including the answer route**
  (P2-1 closes the current gap).
- Tombstoned/ACL-revoked chunks never resurface.

## Fail-closed rule

Under `RAKU_RUNTIME_PROFILE=production`, if a required real adapter is unconfigured (invoker unbound, no
creds), the system MUST fail closed (error/refuse), never silently serve a deterministic stub. The
deterministic stack is only legitimate under `RAKU_RUNTIME_PROFILE=deterministic`.

## Consumption surface

`apps/raku-rag (standalone).html` is the intended product UI (UI-1). It reads its API base from config and
authenticates via the signed dev/real token through the API facade; it is CORS-allowlisted (`RAKU_CORS_ORIGIN`).
It must work against the deterministic local API offline and against the deployed staging API live.

## Secrets

No secret is hardcoded. All credentials (`AWS_*`, Bedrock invoker config, `RAKU_TOKEN_SIGNING_SECRET`,
Langfuse keys) come from env / secret store. Billed or destructive steps (Bedrock reindex P1-6, real-LLM
eval P5-3, load tests) are flagged and gated.
