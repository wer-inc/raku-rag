# Local Development Plan

## Goals

Core product logic must be testable locally without cloud credentials. Cloud services are used for quality and integration validation, not for every developer loop.

## Local Services

- PostgreSQL + pgvector
- MinIO as S3-compatible object storage
- LocalStack SQS
- optional local Redis only if needed by adapters
- local trace sink REQUIRED in Phase 0 (local Langfuse self-host OR deterministic mock trace sink; real-vs-mock choice is open) — raw retrieved context stays disabled by default per OD-008
- deterministic mock auth and signed claim generator

## Local Mock Providers

- mock LLM with deterministic answer fixtures
- mock embedding provider with stable vectors
- mock rerank provider with deterministic ordering
- mock guardrail provider
- mock OCR/layout provider using parser fixtures
- mock VLM provider for visual citation tests
- mock ProviderPolicy capability registry

## Fixtures

- parser fixtures for PDF, DOCX, XLSX, CSV, image, scanned PDF
- evaluation fixtures with expected evidence and expected rejections
- ACL fixtures for tenant, collection, document, group, role
- industry fixtures for equipment, property/unit, fund/share class

## Local Test Coverage

CI must run locally with deterministic mocks for:

- tenant isolation and RLS tenant context
- ACL pre-filter and no post-filter-only behavior
- tombstone and cache invalidation behavior
- insufficient evidence behavior
- no-train ProviderPolicy enforcement
- external provider opt-in blocking
- RiskPolicy and RequiredEvidencePolicy behavior
- DraftArtifact no-auto-approval
- audit event coverage and redaction
- LoggingPolicy raw context disabled by default

## Cloud-Assisted Validation

Use staging or controlled PoC environments for:

- Bedrock Claude Sonnet/Haiku quality and latency
- Cohere Embed/Rerank quality and cost
- Azure Document Intelligence, Google Document AI, Textract quality
- Cognito/SAML/OIDC integration
- KMS/Secrets Manager integration
- Aurora performance and RLS query plans
- Langfuse ECS integration

## Logging Rule

Raw retrieved context is not stored in local or staging traces by default. Tests should assert citation IDs and chunk IDs are stored instead of raw content unless explicit opt-in is configured.
