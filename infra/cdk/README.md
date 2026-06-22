# raku-rag CDK infrastructure

This TypeScript CDK app defines the AWS production scaffold for raku-rag:

- VPC with public, private-egress, and private-isolated subnets.
- KMS customer data key shared by S3, SQS, Secrets Manager, and Aurora.
- S3 document bucket with KMS encryption, SSL enforcement, public access block, and versioning.
- SQS ingestion queue plus DLQ.
- Aurora PostgreSQL Serverless v2 cluster for the pgvector-backed store. The application migrations
  apply `CREATE EXTENSION IF NOT EXISTS vector;`.
- Cognito User Pool and web client.
- Secrets Manager secrets for the NestJS API, Aurora credentials, and Langfuse.
- ECS Fargate services for NestJS API, Python ingestion worker, and Langfuse.
- AWS WAF WebACL on the public NestJS API load balancer with managed common protections,
  IP-based rate limiting, and `x-user-token`-based rate limiting.
- Optional AWS-hosted Next.js fallback service for strict residency tenants.
- CloudWatch dashboard for ECS, Aurora, SQS, WAF, and API target 5xx metrics.
- CloudWatch alarms for API target 5xx, ingestion DLQ visibility, stale ingestion queue age,
  Aurora CPU pressure, and API WAF rate-limit blocks.

```bash
cd infra/cdk
npm install
npm run build
npm run synth
```

Useful context:

```bash
npm run synth -- -c stage=dev -c frontendHosting=external-vercel
npm run synth -- -c stage=prod -c frontendHosting=aws-nextjs
```

The container images are registry placeholders for infrastructure synthesis. Deployment pipelines
should replace them with ECR images produced from `apps/api`, `workers/ingest`, and `apps/web`.

## Frontend Residency Fallback

The web client can use the Vercel AI SDK for chat UI state, streaming helpers, and provider-neutral
client ergonomics, but Vercel hosting is not the default compliance boundary. Hosting is selected by
tenant residency and telemetry requirements:

- Standard tenants may use Vercel-hosted Next.js when the ProviderPolicy and customer contract allow
  the required regions, telemetry, logs, and sub-processors.
- Strict residency, AWS-only, private-network, or customer-managed-key tenants must use the AWS-hosted
  Next.js fallback.
- The fallback target is a Next.js container deployed through this CDK app on ECS Fargate behind an
  AWS load balancer or CloudFront, with logs/traces retained in the customer-approved AWS region.
- The fallback must use the same NestJS API, Cognito, KMS, Secrets Manager, WAF, and CloudWatch
  controls as the rest of the stack; no raw retrieved context or prompt payload may leave the approved
  region through frontend telemetry.

The CDK implementation for T101 should therefore expose two frontend deployment modes:

1. `frontendHosting=external-vercel`: documents the Vercel project, allowed regions, env vars, and
   contract approval reference, but does not treat Vercel as the residency fallback.
2. `frontendHosting=aws-nextjs`: builds and runs `apps/web` as an ECS Fargate service in the selected
   AWS region and routes traffic through AWS-controlled networking.

Promotion rule: if a tenant's ProviderPolicy or residency profile is stricter than the Vercel project
configuration, use `aws-nextjs`.
