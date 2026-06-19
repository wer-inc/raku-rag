# Security and Governance Plan

## No-Train Default

Customer documents, chunks, prompts, answers, citations, DraftArtifacts, evaluations, feedback, logs, and traces are not used for model training, model improvement, cross-tenant improvement, or another tenant's benefit without explicit opt-in.

## Provider No-Train Verification

ProviderPolicy records provider capability, contract mode, zero-retention/no-train support, region, opt-in status, and fallback behavior. If a capability cannot satisfy required no-train/residency controls, the capability fails closed.

## Tenant Opt-In and Opt-Out

Default is opt-out of training and cross-tenant improvement. External parser/OCR provider usage requires explicit tenant/collection opt-in where policy requires it.

## ProviderPolicy

ProviderPolicy controls parser/OCR/LLM/embedding/rerank/observability provider usage by tenant and collection. It must be evaluated before sending raw files, text, images, prompts, embeddings, or logs to external providers.

## LoggingPolicy

LoggingPolicy controls raw query, raw retrieved context, model input, model output, citation IDs, chunk IDs, prompt template versions, model metadata, latency, cost, sampling rate, and retention.

Default:

- raw retrieved context storage disabled
- raw model input/output redacted or disabled unless policy allows
- citation IDs, chunk IDs, template version, model metadata, latency, and cost stored

## Audit Coverage

Audit events include:

- document upload, ingest, parse, metadata enrichment
- approval transition and external approval import
- search query, answer generation, citation access
- insufficient evidence response
- high-risk/regulated/safety/risk gate decision
- DraftArtifact generation, review assignment, review transition
- dashboard access and KPI export
- ACL denied and tenant isolation denied
- no-train, retention, provider policy changes
- deletion, tombstone, cache invalidation

Audit records include tenant_id, actor_id, actor_role, app_id/api_client_id, action, resource_type, resource_id, decision, reason, policy_version, approval_status_at_use, citation_ids, timestamp, request_id/trace_id.

## Redaction and Data Classes

- Personal data: names, addresses, phone, email, workplace, guarantor, emergency contact, ID documents, account info, payment history, customer attributes.
- Confidential financial data: account data, transaction data, holdings, suitability attributes, complaints, RFP/DDQ confidential answers, internal research and risk memos.
- Secrets: credentials, tokens, API keys, private documents, signatures, high-risk EXIF.

Logs, traces, evaluation data, and error output must avoid raw personal, secret, and confidential financial data.

## Bedrock Guardrails

Guardrails are defense-in-depth only. They do not replace tenant isolation, ACL pre-filter, RequiredEvidencePolicy, GroundednessGate, RiskGate/SafetyGate, DraftReviewPolicy, or compliance review.

## Data Residency and External Providers

Strict AWS-only tenants must not send raw files or raw content to Azure/Google or other external providers. External provider use must record region, opt-in, capability snapshot, and audit event.

## Encryption and Access

- KMS encryption for storage and secrets.
- Secrets Manager for credentials.
- Future BYOK support should be designed but not required for MVP.
- IAM least privilege for API, worker, admin, and observability roles.
- Cognito/SAML/OIDC for B2B authentication where needed.

## RLS Tenant Context

Application and worker DB sessions must set tenant context. Admin and background jobs require explicit tenant scoping. No application path should use a broad bypass role.

## Admin Role Boundaries

Operational admins may see job status and internal run IDs where authorized. End users do not see Dagster UI, internal traces, raw audit exports, or cross-tenant provider settings.

## Audit Export and Retention

Audit export is tenant-scoped, redacted, access-controlled, and tamper-evident where required. Retention is governed by tenant policy and industry policies, with legal hold support for regulated industries as future-compatible.

## ISMAP and AI Governance Notes

The product should provide readiness notes, not claim certification by default. Governance explanations should describe no-train default, human review, insufficient evidence, citation, audit, risk gates, provider policy, and redaction controls.
