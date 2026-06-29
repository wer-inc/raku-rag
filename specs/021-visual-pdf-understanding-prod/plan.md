# Implementation Plan: 021 Visual PDF Understanding

## Goal

Ship a production-ready visual/PDF ingestion path that can turn PDFs and images into searchable,
citable visual chunks without weakening tenant isolation, deletion, audit, or manufacturing safety
rules.

The first implementation milestone is deliberately fake-provider first:

`PDF/image input -> provider-neutral visual analysis -> visual chunks -> retrieval/citation`

Live AWS Textract/Bedrock wiring is opt-in and comes only after the fake-provider path proves the
contracts, safety behavior, and storage shape.

## Delivery Strategy

1. **Foundation first.** Add provider-neutral visual interfaces, settings, and factories while keeping
   deterministic providers as the default in every runtime profile unless an explicit provider is set.
2. **Fake-provider vertical slice.** Use fake async document analysis and fake vision/captioning so the
   PDF path can be tested locally without network, Docker, or AWS.
3. **Production storage path.** Add async ingestion state, page-aware chunk ids, and metadata/index
   shape for structured visual evidence.
4. **Safety and audit.** Keep `visual_evidence_promotion` default-off. Visual citations remain
   reference-only until grounding, verifier quorum, and audit coverage are implemented together.
5. **Live AWS adapters.** Add Textract/Bedrock only behind explicit settings and ProviderPolicy gates.

## Milestones

### M1 Planning Artifacts

- Add this `plan.md` and a task checklist.
- Freeze Milestone 1 scope to fake providers and deterministic local verification.
- Explicitly defer live AWS, Google/Azure/OSS adapters, and visual primary-evidence promotion.

### M2 Provider-Neutral Foundation

- Add `raku_rag.interfaces.visual` for `IngestContext`, OCR/layout/caption/VLM protocols, and
  async document-analysis contracts.
- Extend `Settings` and `settings_from_env()` with visual provider settings and
  `visual_evidence_promotion`.
- Add factory selectors for OCR/layout/captioning/VLM that preserve deterministic defaults.
- Re-export visual protocols from `interfaces.base` for compatibility.

### M3 Fake PDF/Image Vertical Slice

- Add fake async document analyzer and fake vision/captioning provider.
- Add page-aware visual chunk ids to avoid multi-page collisions.
- Add executor helpers that can assemble page-scoped `VisualIngestionResult` values from neutral
  document analysis.
- Keep image ingestion compatible with the existing deterministic `execute_image` path.

### M4 Production Storage And Worker Path

- Add additive migration for async job state and visual extractor provenance.
- Route `application/pdf` to queued async visual ingestion and `image/*` to visual ingestion.
- Ensure RLS, tenant isolation, deletion/tombstone behavior, and crop cleanup remain enforced.

### M5 Safety, Audit, And Evaluation

- Extend citation/audit metadata for visual evidence IDs, page, bbox, crop URI, and verifier verdicts.
- Record denied visual promotion attempts without logging raw OCR, caption text, or crop bytes.
- Add high-risk gates proving unverified visual evidence cannot satisfy approved/effective evidence.
- Extend eval fixtures for visual recall, citation accuracy, bbox IoU, and grounding subset rate.

### M6 Live AWS Opt-In

- Add AWS Textract sync-image and async-document adapters.
- Add Bedrock vision caption/VLM adapters.
- Enforce ProviderPolicy before raw bytes leave the system.
- Wire CDK env/IAM for explicitly enabled tenants only.

## Non-Goals For Milestone 1

- No live AWS calls.
- No Google/Azure/OSS implementation.
- No visual evidence promotion to primary evidence.
- No weakening of Tier A gate speed or stdlib-only behavior.
