# raku-rag Web Client

This app is the Next.js admin/chat client for raku-rag. It consumes the shared API DTOs from
`@raku-rag/shared` and talks to the NestJS API through `NEXT_PUBLIC_API_BASE`.

## Vercel AI SDK Usage

The `ai` package is allowed for client-side chat ergonomics, streaming UI helpers, and provider-neutral
interaction patterns. It must not become the security boundary:

- Authorization, tenant isolation, ACL checks, ProviderPolicy checks, groundedness, and citation
  enforcement stay in the NestJS API and Python answer-service.
- Browser code must send only signed identity tokens and user requests to the API. It must not receive
  raw retrieved context unless a LoggingPolicy explicitly permits it.
- Any AI SDK telemetry or hosted-provider integration must be disabled or policy-gated unless the
  tenant contract permits that processor and region.

## Hosting Modes

The same Next.js app supports two hosting modes.

### Vercel-hosted Next.js

Use this only for tenants whose ProviderPolicy and contract allow Vercel regions, telemetry, logs, and
sub-processors. Vercel hosting is a convenience deployment, not the residency fallback. Configure:

- `NEXT_PUBLIC_API_BASE`
- allowed deployment regions
- telemetry/log retention settings
- customer approval reference for external frontend hosting

### AWS-hosted Next.js Fallback

Use this for strict residency, AWS-only, private-network, or customer-managed-key tenants. The fallback
deployment runs the Next.js app as an AWS-hosted container through the CDK stack:

- ECS Fargate service in the tenant-approved AWS region
- AWS load balancer or CloudFront/WAF ingress
- Cognito/API authentication against the same NestJS API
- KMS/Secrets Manager for runtime secrets
- CloudWatch/OpenTelemetry/Langfuse settings that keep raw prompts and retrieved context out of
  frontend telemetry by default

Promotion rule: when the tenant residency profile is stricter than the Vercel project configuration,
deploy this app with the AWS-hosted fallback.

## Local Development

```bash
npm run dev --workspace @raku-rag/web
```

Set `NEXT_PUBLIC_API_BASE=http://localhost:3000/v1` when running against the local API.

## Authentication

The browser supports two app-auth modes:

- `RAKU_AUTH_MODE=dev`: the web route `/api/dev-token` mints the local HMAC token used by demos.
- `RAKU_AUTH_MODE=cognito`: the login page accepts email/password and sends the returned JWT as the
  API bearer token.

Optional HTTP Basic auth is enforced by `apps/web/middleware.ts` when both
`RAKU_BASIC_AUTH_USER` and `RAKU_BASIC_AUTH_PASSWORD` are present. This protects the AWS-hosted web
entrypoint before the app login screen; it is separate from tenant identity and API authorization.
