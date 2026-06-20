# Provider Replacement Guide

The platform has 13 provider abstractions. Replacements must preserve the security and evidence contracts below.

## The 13 Abstractions

1. `Connector`: fetches source bytes from upload, object storage, or SaaS sources.
2. `Parser`: converts bytes into normalized text.
3. `Chunker`: splits normalized text and returns source offsets.
4. `EmbeddingProvider`: embeds text queries and chunks.
5. `VectorStore`: stores vectors and searches with tenant/tombstone/ACL pre-filtering.
6. `Reranker`: reorders already-authorized candidates.
7. `LLMProvider`: generates grounded text answers from authorized chunks.
8. `TaskQueue`: queues ingestion or background jobs.
9. `OcrEngine`: extracts OCR text regions from images/scanned PDFs.
10. `LayoutExtractor`: creates page/region/bbox layout regions.
11. `CaptioningProvider`: optionally enriches regions for retrieval only.
12. `VisualEmbeddingProvider`: embeds visual regions in the same retrieval path.
13. `VLMProvider`: generates visual answers from authorized visual regions.

## Required Invariants

- Providers must never bypass tenant, ACL, deletion, groundedness, risk, or required-evidence checks.
- `VectorStore.search` must apply tenant, tombstone, and visibility filters before returning candidates.
- Rerankers must accept and return only authorized candidates.
- LLM/VLM providers must not receive unauthorized chunks, crops, thumbnails, OCR, or captions.
- Captions are search aids, not primary evidence.
- Providers that log, trace, or persist payloads must use redacted or reference-only data by default.
- Provider failures must fail closed into `insufficient_evidence`, retry, or dead-letter behavior.

## Replacement Checklist

1. Implement the interface behind `src/raku_rag/interfaces/base.py`.
2. Add unit tests for deterministic behavior and failure handling.
3. Add integration tests that exercise the provider through the service, not only directly.
4. Add security tests for ACL, tenant isolation, deletion reappearance, and logging/redaction.
5. Record cost and latency using the existing `CostService` and `MetricsRecorder` surfaces.
6. Update provider policy allowlists and audit records when the provider is externally managed.
7. Run `scripts/gate.sh all`, `scripts/gate.sh separation`, and the Node checks if API contracts change.
