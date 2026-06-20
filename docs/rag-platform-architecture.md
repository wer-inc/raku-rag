# Raku RAG Platform Architecture

This document summarizes the current implementation shape for the Speckit 001 RAG platform.

## Runtime Shape

- `apps/api`: NestJS product facade. It authenticates the API key and signed user token, then forwards tenant and principal identity to the Python answer-service.
- `apps/answer-service`: internal HTTP boundary over the Python RAG core. Retrieval, ACL, ranking, deletion, assets, evaluation, and admin state live here.
- `src/raku_rag`: reusable Python core. In-memory MVP and Postgres production compositions share the same services and security invariants.
- `workers/ingest`: ingestion orchestration, queue status projection, visual ingestion, provider policy seams, and Dagster-compatible helpers.
- `packages/shared`: TypeScript DTOs shared by API and client code.
- `infra/db/migrations`: database schema and RLS migrations.

## Request Flow

1. The API receives `/v1/search`, `/v1/answer`, `/v1/assets/{asset_id}`, ingest/admin/eval requests.
2. Auth middleware verifies `Authorization` and `X-User-Token`, then attaches `req.principal`.
3. Controllers forward only the signed principal identity to the answer-service.
4. The Python core applies tenant, tombstone, and ACL filters before retrieval scoring.
5. Answer generation cites only evidence that supports the answer. If evidence is weak or unsupported, the result is `insufficient_evidence`.
6. Deletion tombstones documents/chunks immediately and cascades to visual crops/assets/caches.

## Security Invariants

- Tenant identity comes from signed tokens or trusted internal headers, not from user request bodies.
- Retrieval applies tenant + tombstone + ACL visibility before scoring.
- Rerank, LLM, VLM, citations, thumbnails, crops, and assets receive only authorized evidence.
- Deleted documents and visual artifacts do not reappear through search, answer, citations, assets, VLM input, or caches.
- Raw retrieved context and raw user queries are not stored by default.
- PII/secrets are redacted in text, OCR, captions, EXIF, logs, audit metadata, and eval registration.

## Visual RAG

Visual ingestion creates `VisualAsset`, OCR text regions, layout regions, optional generated captions, visual embeddings, and visual chunks. Captions are retrieval aids only. The VLM uses OCR/layout region text as primary evidence and returns visual citations with asset, page, region, bbox, and crop URI.

## Verification

The local gate is `scripts/gate.sh all`. It runs the Python hard gates and full unit/integration suite. `scripts/gate.sh separation` verifies architecture separation. Node checks are `npm run build:shared`, `npm run typecheck`, and `npm run test:api`.
