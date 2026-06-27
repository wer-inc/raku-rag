# Production Spec: Visual & PDF-Image Understanding

**Textract OCR/structured extraction + Bedrock Claude vision VLM, with first-class (high-risk-admissible) visual evidence**

> Status: DRAFT for review · Owner: CTO/platform · Provenance: authored from a 15-agent grounding→draft→adversarial-review→synthesis workflow, then **hardened by hand to fold in every blocking safety/correctness finding** (see §0.5, which is NORMATIVE and overrides any conflicting body text). Feeds the Spec Kit flow (`/speckit.plan` → `/speckit.tasks`).

---

## 0. Executive Summary & Decision Record

### 0.1 Current state — it's a deterministic stub (the problem)

The entire visual path is **structurally complete but never interprets pixels**, and PDFs are not parsed at all in the live build:

- "OCR", "captioning" and "visual embedding" all just `image.decode("utf-8", errors="ignore")` — they read fixture *text bytes*, not real PNG/JPEG pixels (`src/raku_rag/providers/ocr/__init__.py:9,22`; `providers/captioning/__init__.py:39`; `providers/visual_embeddings/__init__.py:19`). Bounding boxes are index-derived synthetic values (`ocr/__init__.py:36`).
- The "VLM" (`ExtractiveVLMProvider`, `providers/vlms/__init__.py:23-37`) takes no image and makes no model call; it extracts query-overlapping sentences from OCR text. It is **hardcoded** at `app.py:65` / `production.py:99` (no `vlm_from_settings` selector, unlike LLM/embedder/reranker/guardrail).
- Crops are never rendered — `CropService` mints URI **strings** `memory://crops/…` / `memory://redacted-crops/…` (`services/crop.py:73,114`).
- The production upload parser is text-only: `CompositeParser([TextParser, DocxParser, SpreadsheetParser])` (`production.py:89`), and `production.py:88` literally comments *"PDF needs an optional pypdf parser (not installed here)"*. **No PDF text extraction, and no path whatsoever for images embedded inside PDFs** (no fitz/pymupdf/pdf2image/get_images anywhere in the repo).
- `Modality.VISUAL` chunks are produced **only** by `app.py:160 ingest_visual_fixture` — a fixture/test method exposed by **no** answer-service or NestJS route. So in production, `use_vlm` (`answer.py:274`) is always false and the visual gate never fires.

This is **intentional** — the visual abstractions are declared as **US6, explicitly "out of MVP scope"** (`interfaces/__init__.py:3-6`; `interfaces/base.py:88`). This spec promotes US6 to production.

### 0.2 The CTO decisions this spec is built on (decision record)

1. **Providers = AWS-native.** OCR + layout + tables/forms/queries = **AWS Textract**; figure/photo/diagram/chart semantic understanding = **Bedrock Claude vision**. Visual embeddings stay Hashing for v1 (Titan Multimodal noted as opt-in). `ProviderPolicy` enforces `region=ap-northeast-1, zero_retention=true, no_train=true` for OCR+VLM, exactly as the parser router already does. New `ocr_provider` / `vlm_provider` settings + `*_from_settings` selectors mirror `llm_provider_from_settings`. **Deterministic offline providers remain the default**, so the Tier-A gate is unchanged and fast. **(REVISED 2026-06-27 — vendor-portable by design: see §2/§2.8.)** AWS-native is the DEFAULT, but the contract is vendor-neutral and per-capability/per-tenant selectable; adopting **Google Vertex AI (Document AI + Gemini), Azure, or OSS** is a conformant adapter + config flip with zero retrieval/answer/safety code changes.
2. **Scope = maximum (structured extraction).** Beyond text-layer + OCR: detect & VLM-caption non-text regions (searchable + citable); tables→structured rows (Textract TABLES/QUERIES); forms→key-value (FORMS); charts→numeric series (VLM/dedicated). **Images embedded inside PDFs are detected/extracted/interpreted** (page rasterization + embedded-image extraction), not just the text layer. **Crops are rendered for real and stored in S3** (replacing the `memory://` placeholders).
3. **Safety = visual evidence can be promoted to PRIMARY (high-risk-admissible) evidence** — but only when the source doc is **approved+effective** AND it passes (a) strong OCR-grounding, (b) an adversarial multi-verifier double-check, (c) audit logging. AI output stays `draft`. This **extends, never weakens**, the 002 hard rules.

### 0.3 Thesis: incremental injection, not a rewrite

Every integration point already exists as a seam: the `OcrEngine`/`LayoutExtractor`/`CaptioningProvider`/`VLMProvider` protocols, the `ParserClient` + `ProviderPolicyParserRouter`, the `LayoutRegion`/`VisualAsset`/`CropArtifact` data model, the visual-citation/redaction/ACL plumbing, and the `*_from_settings` provider-selection pattern. We **inject real AWS providers behind these seams**, add the missing `*_from_settings` selectors + an async-Textract job seam, wire an image/PDF ingest route, render real S3 crops, and add a strictly-additive safety promotion gate. No greenfield rewrite.

### 0.4 Non-negotiable invariants

- **Default-off & fail-closed.** Real providers and first-class promotion are off unless `runtime_profile == "production"` and the explicit flag is set. Every failure path downgrades to reference-only / `insufficient_evidence`. The deterministic profile behaves exactly as today.
- **Tier-A stays green & stdlib-only.** No new heavy dependency may import at module load on the deterministic path (lazy imports mandatory — see §0.5-C12).
- **Safety boundary is human-reviewed.** All promotion/grounding/verifier/audit tasks (Epic F) are `[HUMAN]` and ship only as a complete set.

---

## 0.5 NORMATIVE Review Resolutions (binding — these OVERRIDE any conflicting text in §§1–6)

The adversarial review returned `has-blocking-gaps` on Safety and Completeness and `sound-with-fixes` on Integration. The following amendments are **authoritative**; where a body section below conflicts, this subsection wins.

> **Provider-portability amendments are ALSO binding.** The "Portability Patch-List" (after §2.8) folds vendor-neutrality into §0.5/§3/§4/§5/§6/§7 — notably the disjoint `ExtractionSource`/`CaptionSource` provenance vocabulary that closes a default-profile FR-048 hole (the old shared `"deterministic"` value). Those amendments are binding because they now live in the body (§0.5 is the rule, the body implements it); the patch-list itself is **non-normative rationale** (see its header).

### A. Safety / FR-048 & promotion (all `[HUMAN]`, ship as one set)

- **A1 — Close the FR-048 structured-kind bypass.** §5.3 Hook 2 must NOT gate on `c.kind == "visual"` alone. The gate is two-pronged (see the §5.3 `_admissible` code): (1) **every non-text** citation must be membership-promotable — `is_promotable_evidence(c.metadata)` — so a VLM-inferred `chart_series` or any `CaptionSource`/empty-provenance value can never be primary; (2) **every pixel-derived** citation (`pixel_derived=True`, i.e. `kind ∈ VISUAL_DERIVED_KINDS = {"visual","table_row","form_field","chart_series","figure_caption"}` — crop-bearing OCR/VLM kinds) must ALSO carry `c.visual_evidence_verified`. A `spreadsheet` cell is deterministic structured data (`pixel_derived=False`, `extraction_source=spreadsheet_parser`) so it is admissible on approval + membership like text, with no crop to verify. Net: a `figure_caption`/`table_row`/`chart_series` can never satisfy the high-risk approved+effective requirement on document approval alone.
- **A2 — Caption is never grounding text.** §4.4: caption-derived leaf chunks pin `primary_evidence_text = region.ocr_text` (caption **excluded**); when a figure has no OCR, `primary_evidence_text = ""` so `strong_grounding` fails closed. A `figure_caption` with empty OCR is reference-only, always.
- **A3 — VLM-interpreted values are never primary.** Promotability is a **membership test**, never a string literal: a value is primary-eligible iff `primary_evidence_source ∈ PROMOTABLE_EXTRACTION_SOURCES` (the `ExtractionSource` transcription space) AND its producing capability is `extraction_method == 'transcription'` (§2.1). A `chart_series` — or any value — carrying a `CaptionSource` (VLM-inferred) is reference-only. NEVER gate on `== "textract"` or `!= "vlm"` (both break under vendor swap / fail open). `ChartPoint.raw_text` grounds only when its source is in `PROMOTABLE_EXTRACTION_SOURCES`.
- **A4 — Verifier independence is real (canonical rule; restated identically in §2.8.5 and §5.5).** Promotion requires `LexicalOcrSubsetVerifier.passed` AND **at least `visual_evidence_verifier_quorum` (≥2 in production) pixel-reading VLM verifiers all passing**, where the deterministic lexical verifier is mandatory but does **not** count toward the VLM quorum. The VLM verifiers must use **distinct model ids from distinct provider families by default** (e.g. Bedrock Claude + Vertex Gemini) — a different prompt on the same model never counts. Two models of the **same** family qualify only when `visual_verifier_allow_same_family_distinct_models=true` (default `false`, attestation-gated); otherwise high-risk visual evidence demotes to `insufficient_evidence` and the block is **surfaced, not silent**. Document residual correlated-failure risk (§5.5/G1).
- **A5 — Wire the audit for real.** (a) Extend `ManufacturingCitation` + `from_base` (`answer_ext.py:73-88`) to copy `asset_id`, `region_id`, `page_number`, `bbox`, `crop_uri`, `visual_evidence_verified`, `visual_verifier_verdicts`. (b) Add an `extra_client_metadata: Mapping[str,object] = {}` parameter to `record_answer_decision` (`manufacturing/api/audit.py:36-98`) and pass the `visual_evidence` block from `manufacturing/app.py:802-819`. (c) Make `sanitize_audit_log_entry` (`manufacturing/domain/audit.py:177-183,301`) **recurse** into nested lists/dicts so the nested verdict list is redacted. Reference-IDs/booleans/numbers/category-codes only — never OCR/caption/crop bytes (SC-MFG-010).
- **A6 — Audit denied promotions too.** Emit an audit entry on **denied** promotion (grounding fail or verifier dissent), recording citation/asset/region reference ids, each verifier `passed=false` + `reason_code`, and a category code — so the 002 "state transitions are audited" rule holds for the safety-relevant non-promotion, and `safety.visual_grounding_verifier_fail_total` is actually driven.
- **A7 — Pre-filter lives in the overlay, not base.** Base `AnswerService.answer` has no high-risk classifier, so the approved+effective region pre-filter (§5.3) must live in `ManufacturingAnswerService` — extend `_should_answer_from_approved_lookup_evidence` (or add a parallel high-risk branch) so for **all** high-risk queries the generator only ever sees a `_PreselectedRetrieval` restricted to approved+effective regions. This prevents a draft/obsolete crop's caption from poisoning generated text. Pre-filter ≠ promotion (promotion is decided post-generation).
- **A8 — One promotion flag.** Use a single `Settings.visual_evidence_promotion` (`RAKU_VISUAL_EVIDENCE_PROMOTION`) everywhere. **Delete** the old duplicate `visual_primary_evidence_enabled` / `RAKU_VISUAL_PRIMARY_EVIDENCE_ENABLED` name from the §6 drafts and rollout docs.
- **A9 — Fail closed without a real crop.** A VLM verifier that cannot fetch a **real rendered crop** (`crop_uri` not `s3://`, or bytes unavailable) returns `passed=False` — never a pixel-less pass. Add this row to the §5.7 downgrade table.
- **A10 — Sentence-scoped grounding (else it's dead-on-arrival).** §5.4: `A` must be the **sentence(s) of the answer attributed to the region**, NOT the entire answer text — `tokens(A) ⊆ tokens(O)` over the whole multi-sentence answer is essentially never satisfiable. Implement sentence attribution (reuse `_attributed_sentences`/sentence split) and run grounding per attributed sentence; the region backs only the sentences it grounds.
- **A11 — Honest framing.** §5.1 must state this change **tightens** current behavior: today's post-answer demotion (`answer_ext.py:360-363`) and the pre-gate survey (`gate.py:84`) are kind-agnostic and already let an unverified visual citation from an approved+effective doc satisfy high-risk. Promotion gating closes that pre-existing hole.

### B. Integration seams (correctness; `sound-with-fixes`)

- **B1 — Correct the `LayoutExtractor` boundary.** The real contract enforced by `VisualIngestionExecutor.execute_image` (`ingestion.py:583`) is `extract(self, image, *, tenant_id, collection_id, document_id, asset_id, ocr_regions=None) -> tuple[LayoutRegion,...]` — **not** the no-kwarg `extract(image)` the draft asserts. Real adapters must implement this exact signature.
- **B2 — Add an explicit async analysis seam; drop "no new protocols".** A multi-page-PDF async flow cannot hide behind the synchronous `OcrEngine.extract(image: bytes)`. Add a **new** vendor-neutral async boundary `AsyncDocumentAnalyzer.submit(AsyncSubmitRequest(document_ref="s3://...")) -> JobHandle` + `poll(JobHandle) -> DocumentAnalysis | PENDING` (the return is the **neutral** `DocumentAnalysis`, never a Textract-specific shape), driven from the SQS worker (`IngestionWorker.process_once`). The spec explicitly introduces this protocol; it does not claim "no new protocols".
- **B3 — One name per adapter.** Each adapter has exactly one canonical, capability+vendor name — `TextractOcrLayoutEngine`, `TextractStructuredExtractor`, `BedrockVisionVLMProvider`, `BedrockVisionCaptioningProvider` — with no alternate spellings of the **same symbol**. The three *layers* legitimately use a consistent vendor stem (adapter `Textract*`/`BedrockVision*`, normalizer `AwsTextract*Normalizer`/`BedrockVision*Normalizer`, policy/registry key `aws_textract`/`bedrock`); these are the same vendor across layers, NOT competing spellings — a new vendor reuses the same stem in all three layers (no fourth spelling).
- **B4 — One migration strategy.** Reconcile §4 (nest in `metadata` jsonb) vs §6 (`0014` adds real columns): structured payloads live in `chunk.metadata` jsonb with GIN + expression indexes on the identifier paths (specified once in §6.2); the **only** new top-level columns are the async-job state (B5) and `extractor_version`. The `0014` migration is `0014_visual_understanding.sql`, additive/expand-only, and is specified canonically in §6.2 — §4.9 must not carry a second SQL block.
- **B5 — Persist async job state (vendor-neutral).** Add `ingestion_runs.async_provider` + `async_job_id` + `async_job_status` (the vendor-opaque `JobHandle.token` — Textract `JobId` | Document AI LRO name | Azure operation-location), persisted across worker polls. Do **not** use Textract-specific column names.
- **B6 — Anchor fixes.** `IngestionJobMessage.content_type` is at `ingestion.py:41` (not :130). Verify the `0014` index name against the real `idx_chunks_metadata_*` anchors before writing the migration.

### C. Completeness (production-readiness; `has-blocking-gaps`)

- **C1 — Async Textract job lifecycle.** Extend the queue protocol (`workers/ingestion.py:183-187`, today only receive/ack/fail) with a delayed re-drive / "in-progress, come back later" visibility state; define submit→poll→complete/fail transitions, timeout, and max re-drives.
- **C2 — PDFs are ALWAYS async.** `application/pdf` is never ingested inline by `ProductionSystem.ingest_document`; the synchronous `POST /internal/ingest` (`server.py:1944`) returns a **queued** run (`202` + `status_url`) for PDFs. The NestJS `IngestController` adds a multipart `@Post("upload")` with S3 round-trip and `415`/`413` validation.
- **C3 — Textract limits + size reconciliation.** Document sync `AnalyzeDocument` (single-page, ~10 MB inline) vs async `StartDocumentAnalysis` (from S3, large PDFs) in §3.3/§6.5 and reconcile with `Settings.max_document_bytes` (25 MiB, `config.py:18`).
- **C4 — Signed-URL crops must not bypass ACL/redaction (path-invariant).** Crop S3 URIs are **never** returned raw on **any** surface — the asset-view endpoint AND the citation/answer surface. Wherever a crop is exposed, `AssetService` mints a short-TTL presigned GET in a `crop_url` field **only after** `can_read_document` (`assets.py:25`) passes; when `visual_region_redaction_required`, the presigned URL MUST point at the **redacted** crop object. The internal `crop_uri` (`s3://`/bucket/key) is never serialized to a client. A presigned URL is a bearer capability — gate it behind RLS/ACL exactly like the JSON path. This applies identically to the `Citation` schema (answer path) and `VisualAssetResponse` (asset view).
- **C5 — S3 crop lifecycle/retention.** Define the crop bucket lifecycle/expiration aligned to the documented retention (customer 1yr / audit 1yr, per CLAUDE.md); specify whether `S3CropStore.tombstone_document` hard-deletes or marks the object.
- **C6 — Re-ingest = tombstone-and-replace.** At the start of `ingest_visual_document` for an existing `(tenant, document_id)`, tombstone-and-replace ALL prior assets, layout_regions, visual chunks, and S3 crop objects for that `document_id` (reuse `deletion.py:133-157` + physical `DeleteObject`) before writing the new run — no orphans.
- **C7 — ProviderPolicy egress audit for OCR/VLM, concrete.** Specify net-new `OcrPolicyRouter` / `VlmPolicyRouter` (+ adapters) modeled on `ProviderPolicyParserRouter` (`parsers/__init__.py:248-330`) that emit a persisted `raw_content_sent` audit event before any raw bytes leave the worker to Textract/Bedrock.
- **C8 — Fix provider-capability region default.** `DEFAULT_PROVIDER_CAPABILITIES` reports `region='us-east-1'` for `aws_textract`/`bedrock` (`provider_policy.py:235-248`). Change the default-capabilities map (or per-tenant policy) to `ap-northeast-1`, else the zero-retention/region policy mis-evaluates.
- **C9 — Budget answer-time verifier cost AND latency.** The K-VLM adversarial quorum runs Bedrock vision calls **per high-risk visual citation per answer** — recurring answer-time spend/latency, not ingest-time. Add per-answer caps (`max_regions_verified_per_answer`) and a latency budget to §5.5/§6.5; reconcile with the existing `p95_visual_answer_latency_ms` baseline.
- **C10 — Backfill plan.** Add a backfill command (`scripts/backfill_visual.py`) that enumerates already-ingested `content_type ∈ {application/pdf, image/*}` documents lacking visual assets at the current `extractor_version`, re-enqueues them through the visual worker with C6 replace semantics, under a bulk cost ceiling + concurrency cap + idempotent resumability; run as an in-VPC RunTask mirroring `MigrateSeedTask` (`raku-rag-stack.ts:851-874`).
- **C11 — chunk_id backward compatibility.** Changing `{doc}:visual:{idx}` → `{doc}:visual:{page}:{idx}` (`visual.py:25`) alters existing single-image citation anchors. Keep the single-image path at `page_number=1` producing a stable, parseable anchor; do not break existing citations.
- **C12 — Lazy imports guarantee Tier-A stays stdlib-only.** `PdfPageParser`/`PdfImageExtractor` MUST NOT import `pypdfium2`/`pikepdf`/`Pillow` at module load (they are appended to `CompositeParser` at `production.py:89`, which the deterministic gate constructs). Import inside the parse method.
- **C13 — Embedded-image extraction failure handling.** `pikepdf`/`pypdfium2` fail on encrypted/malformed/password-protected PDFs and unsupported image filters (JPXDecode/JBIG2). A rasterization/extraction failure is **fail-soft for that region** (skip, record `caption_failure_reason`/region status) but the text-layer ingest still completes; never crash the whole job.
- **C14 — Concrete rollback.** §6.8/R6: `0014` deploys first and is additive (expand/contract). Define data rollback: when `visual_evidence_promotion` is flipped off or providers reverted to deterministic, already-promoted citations are re-evaluated on read (promotion is never persisted as a final verdict; it is recomputed), so disabling the flag immediately demotes all visual evidence to reference-only.
- **C15 — Cost cardinality.** One `cost_records` row per Textract **job** (plus a page count) and one per VLM call; define how an async job's cost is attributed when pages complete out-of-band.

---

---

## 1. Goal, Scope & Target Architecture

### 1.1 Goal & Problem Statement

Today the visual/PDF understanding path is a **deterministic US6 stub** that never actually decodes pixels, never parses PDFs, and never interprets images embedded in documents. It exists to keep the Tier-A gate fast and to exercise the chunk/citation plumbing with text fixtures — it is not production document understanding. Concretely:

- **"OCR" is a UTF-8 decode, not OCR.** `DeterministicOcrEngine.extract` (`src/raku_rag/providers/ocr/__init__.py:21-40`) calls `_decode_text` (`:8-9`), which is literally `image.decode("utf-8", errors="ignore")`. It treats each text line of the *byte stream* as an OCR region. Feed it a PNG/JPEG/PDF and it returns `()` (or garbage), because real image bytes are not UTF-8 text. `DeterministicCaptioningProvider.caption` (`src/raku_rag/providers/captioning/__init__.py:34-52`) does the same decode (`:39`).
- **The "VLM" reads no pixels.** `ExtractiveVLMProvider.generate` (`src/raku_rag/providers/vlms/__init__.py:23-37`) only term-overlaps the query against `region.ocr_text`; it deliberately ignores even the generated caption and never sees the image. So figures, photos, diagrams, and charts carry **zero** semantic signal.
- **Crops are fake URIs.** `CropService.create_region_crop` (`src/raku_rag/services/crop.py:47-95`) mints `crop_uri=f"memory://crops/{tenant_id}/{crop_id}"` (`:73`, `:79`, `:80-82`). No bytes are ever rendered or stored; a UI cannot display the cited region. The parent asset is equally synthetic: `storage_uri=f"memory://visual-assets/..."` (`src/raku_rag/workers/ingestion.py:546`).
- **There is no PDF parsing at all.** The composition root wires `self.parser = CompositeParser([TextParser(), DocxParser(), SpreadsheetParser()])` (`src/raku_rag/production.py:89`) with the inline note that "PDF needs an optional pypdf parser (not installed here)" (`:86-88`). The single-document ingest boundary `POST /internal/ingest` (`apps/answer-service/server.py:1916-1957`) unconditionally calls `system.ingest_document(...)` (`:1944`) — the text path — with **no** `content_type` branch for `application/pdf` or `image/*`.
- **Images inside PDFs are never interpreted.** Even when a PDF reaches a parser, only its text layer is extracted; embedded figures/photos/scanned pages are dropped. The whole visual stack is fenced off as `# --- US6 (out of MVP scope) ---` (`src/raku_rag/interfaces/base.py:88`), and providers are hardcoded rather than settings-selected: `self.vlm = ExtractiveVLMProvider()` (`production.py:99`), `self.crops = CropService()` (`:108`), and `VisualIngestionExecutor.__init__` falls back to `DeterministicOcrEngine()/DeterministicLayoutExtractor/DeterministicCaptioningProvider` (`workers/ingestion.py:517-519`).

**Goal:** Replace the stub with an **AWS-native, structured visual-understanding pipeline** that (a) actually OCRs and lays out PDFs/images via Textract, (b) detects and semantically interprets non-text regions (figures, photos, diagrams, charts) via Bedrock Claude vision, (c) extracts tables/forms/queries as structured rows/key-values, (d) stores **real** crop renderings in S3, and (e) lets a visual citation become **first-class, primary** evidence for high-risk manufacturing answers — without weakening any existing 002 safety rule. Deterministic offline providers remain the default so the Tier-A gate stays fast and unchanged.

### 1.2 In-Scope (maximum / structured extraction)

1. **Format routing.** `POST /internal/ingest` (`apps/answer-service/server.py:1916-1957`) branches on `content_type`: `application/pdf` and `image/*` route to a visual ingest path; everything else keeps the existing text path. A `PdfPageParser` is added to the `CompositeParser` list (`production.py:89`) yielding `(page_image_bytes, page_number, text_layer_fallback)` per page.
2. **Text-layer + OCR + layout.** AWS **Textract** for OCR, reading order, and block geometry. Sync `AnalyzeDocument` for single images; async `StartDocumentAnalysis`/`GetDocumentAnalysis` for multi-page PDFs.
3. **Tables → structured rows; forms → key-value; queries.** Textract `FeatureTypes=["TABLES","FORMS","QUERIES"]`. Each table row / form field becomes an individually indexable `Chunk` and a typed citation (`table_row` / `form_field`), per the Structured Extraction data-model extensions.
4. **Non-text region detection + VLM interpretation.** Pages are rasterized and embedded images extracted; figure/photo/diagram/chart regions are captioned and QA'd by **Bedrock Claude vision** (multimodal invoke). Charts are decoded to numeric series (`chart_series`). Captions are searchable + citable.
5. **Real crops in S3.** `CropService.create_region_crop` (`crop.py:47-95`) computes real crop bytes from `region.bbox` over the rendered page and uploads to `s3://{crop-bucket}/{tenant_id}/{collection_id}/{document_id}/{crop_id}.png`, replacing every `memory://` URI. Redacted variants uploaded separately. Asset `storage_uri` (`workers/ingestion.py:546`) likewise becomes `s3://`.
6. **First-class visual citations under the 002 safety gate.** Visual `Chunk`s carry manufacturing metadata so `is_approved_effective` (`src/raku_rag/manufacturing/safety/gate.py:51`) and the high-risk demotion check (`src/raku_rag/manufacturing/api/answer_ext.py:358-375`) apply identically to visual evidence. Promotion to **primary** requires: source approved+effective, asserted text ⊆ OCR text of the cited region (grounding), adversarial double-check by ≥2 independent verifiers, and an audit-log entry recording the visual evidence + verifier verdicts. AI output stays `draft`.
7. **Provider selection + policy.** New `Settings` fields `ocr_provider` / `vlm_provider` / `captioning_provider` + `*_from_settings` factories, mirroring `llm_provider_from_settings` (`src/raku_rag/providers/llms.py:190-219`). `ProviderPolicy` enforces `region=ap-northeast-1`, `zero_retention=true`, `no_train=true` for OCR + VLM (allowlist already present at `workers/ingest/provider_policy.py:43`; `"ocr"` operation already mapped at `:139-141`).

### 1.3 Non-Goals

- **No full DMS / e-signature / arbitrary version rollback** (unchanged 002 boundary). We persist approval state + audit, not a document-management system.
- **No real-time / streaming video or live-camera understanding.** Still images, rasterized PDF pages, and embedded raster images only. No frame extraction from video files.
- **No handwriting-grade or low-confidence OCR promotion.** Region OCR below the confidence/grounding bar is reference-only, never primary evidence.
- **No new visual embedding model in v1.** Visual embeddings stay `HashingVisualEmbeddingProvider`; Titan Multimodal is noted as opt-in only.
- **No weakening of existing 002 rules.** This *extends* the "approved+effective citation" requirement so a visual citation can satisfy it; it never relaxes the high-risk gate.
- **No client-side / browser OCR or VLM.** All inference is server-side AWS-native at the worker/answer-service edge.

### 1.4 Target Architecture (AWS-native flow)

```
                          ┌──────────────────────────────────────────────────────────────┐
  upload (PDF / image)    │  NestJS API  ─ POST /v1/ingest ─►  answer-service              │
  ──────────────────────► │  IngestController              POST /internal/ingest          │
                          │  (data:/s3:/file: ref)         server.py:1916-1957            │
                          └───────────────────────────┬──────────────────────────────────┘
                                                       │ connector.fetch(ref) -> bytes
                                                       ▼
                               ┌───────────────────────────────────────────┐
                               │  content_type ROUTER (NEW branch @ :1944)  │
                               │  text/* ─► ingest_document (existing)      │
                               │  application/pdf, image/* ─► visual path   │
                               └───────────────┬───────────────────────────┘
                                               ▼
                   ┌───────────────────────────────────────────────────────────────┐
                   │ PdfPageParser (NEW, added to CompositeParser production.py:89) │
                   │  PDF ─► [page raster bytes, page_no, text-layer fallback]…     │
                   │      + embedded-image extraction (XObject/inline images)       │
                   └───────────────┬───────────────────────────────┬───────────────┘
                                   │ per page / per embedded image  │
                  ┌────────────────▼───────────────┐   ┌────────────▼───────────────────────┐
                  │  OCR + LAYOUT + STRUCTURE       │   │  NON-TEXT REGION UNDERSTANDING      │
                  │  AWS Textract (OcrInvoker seam) │   │  Bedrock Claude vision (VLMInvoker) │
                  │  Sync AnalyzeDocument (1 img)   │   │  figure/photo/diagram caption + QA  │
                  │  Async StartDocumentAnalysis    │   │  chart ─► numeric series            │
                  │  FeatureTypes=TABLES,FORMS,     │   │  (multimodal invoke; pixels in)     │
                  │   QUERIES  ─► OcrTextRegion[]   │   └────────────┬────────────────────────┘
                  │   + table rows + form KV        │                │ captions / series / QA
                  └────────────────┬────────────────┘                │
                                   │  OcrTextRegion[] + structured    │
                                   ▼                                  ▼
              ┌──────────────────────────────────────────────────────────────────┐
              │ VisualIngestionExecutor.execute_image  workers/ingestion.py:524   │
              │   → LayoutRegion[] (bbox, page_number, region_type, ocr_text,     │
              │     generated_caption_text, structured_content) → VisualIngestion │
              │     Result (ingestion.py:490-496)                                 │
              └───────────────┬───────────────────────────────┬──────────────────┘
                              ▼                                ▼
         ┌────────────────────────────────┐   ┌──────────────────────────────────────────┐
         │ visual_chunks_from_ingestion   │   │ CropService.create_region_crop  crop.py:47 │
         │ services/visual.py:17-55       │   │  render bbox ─► PNG bytes ─► S3 upload      │
         │ Chunk(modality=VISUAL,         │   │  crop_uri = s3://{bucket}/{tenant}/{coll}/  │
         │  metadata={asset_id,region_id, │   │   {doc}/{crop_id}.png  (REAL, replaces      │
         │  bbox,crop_uri,ocr_text,       │   │   memory:// @ :73,:79,:80-82)               │
         │  caption,_mfg_meta…})          │   └──────────────────────┬─────────────────────┘
         └───────────────┬────────────────┘                          │
                         ▼ store.upsert (PostgresVectorStore, indexed by asset_id)
       ┌─────────────────────────────────────────────────────────────┴──────────────┐
       │ RETRIEVAL + ANSWER                                                          │
       │  answer.py:271-294  visual_regions = _layout_region_from_chunk(:672)        │
       │    use_vlm ─► Bedrock Claude vision.generate(query, visual_regions)         │
       │  002 SAFETY GATE (visual = first-class):                                    │
       │    is_approved_effective  gate.py:51   (per visual citation)                │
       │    SafetyGate.evaluate     gate.py:73   high-risk ⇒ need approved+effective │
       │    high-risk demotion     answer_ext.py:358-375                             │
       │    PRIMARY promotion ⇒ grounding ⊆ OCR + ≥2 adversarial verifiers + audit   │
       │  ManufacturingCitation.from_base  answer_ext.py:335 (approval_status/        │
       │    effective_date/approval_source on visual chunk)                          │
       │  AuditLogEntry: citation_ids include visual chunk_ids + verifier verdicts   │
       └────────────────────────────────────────────────────────────────────────────┘
```

**AWS edges:** Textract (`textract:AnalyzeDocument`, `StartDocumentAnalysis`, `GetDocumentAnalysis`) and Bedrock Claude vision (`bedrock:InvokeModel`) are reached only through injected `OcrInvoker = Callable[[bytes], tuple[OcrTextRegion, ...]]` / `VLMInvoker = Callable[[str, Sequence[bytes]], str]` callables built with lazy boto3 (mirroring `BedrockInvoker` at `src/raku_rag/providers/llms.py:94-97`), so unit tests stay offline. IAM is granted in CDK alongside `grantBedrockInvoke` (`infra/cdk/lib/raku-rag-stack.ts:1205`); production wiring is gated by `RAKU_RUNTIME_PROFILE=production` + new `RAKU_OCR_PROVIDER`/`RAKU_VLM_PROVIDER` context (`raku-rag-stack.ts:99-107`).

### 1.5 Exact existing seams this plugs into

| Concern | Symbol | File:line | Plug action |
|---|---|---|---|
| Provider settings | `Settings` dataclass | `src/raku_rag/core/config.py:9-75` | the canonical §6.1 block (`ocr/layout/structured/vlm/captioning/visual_embedding_provider="deterministic"`, `ocr_region`/`vlm_region`, …) |
| Env parse | `settings_from_env` | `src/raku_rag/core/config.py:79` | parse `RAKU_OCR_PROVIDER`/`RAKU_VLM_PROVIDER`/`RAKU_CAPTIONING_PROVIDER` |
| Factory template | `llm_provider_from_settings` | `src/raku_rag/providers/llms.py:190-219` | clone as `ocr_from_settings` / `vlm_from_settings` / `captioning_from_settings` (explicit-override → profile selection → fail-closed in production) |
| Invoker seam | `BedrockInvoker` alias | `src/raku_rag/providers/llms.py:94-97` | add `OcrInvoker` / `VLMInvoker`; `build_aws_textract_invoker(*, region_name, client=None)` |
| Protocols | `OcrEngine`/`LayoutExtractor`/`CaptioningProvider`/`VLMProvider` | `src/raku_rag/interfaces/base.py:91-110` | evolve/re-export through `src/raku_rag/interfaces/visual.py`; deterministic adapters preserve current behavior while real adapters receive `IngestContext`/`CropResolver` |
| Policy allowlist | `ProviderPolicy.allowed_ocr_providers` + `_operation_allowlist_field` | `workers/ingest/provider_policy.py:43`, `:139-141` | add `"ocr"`/VLM region + retention/no-train checks (`:162`, `:223`) |
| Composition root | `ProductionSystem.__init__` | `src/raku_rag/production.py:73-110` | replace `self.vlm = ExtractiveVLMProvider()` (`:99`); add `self.ocr/self.captioning = *_from_settings(...)`; inject into executor; S3-back `CropService` (`:108`) |
| PDF parser | `CompositeParser([...])` | `src/raku_rag/production.py:89` | append `PdfPageParser()` |
| Visual executor | `VisualIngestionExecutor.__init__` / `execute_image` | `src/raku_rag/workers/ingestion.py:507-522`, `:524-651` | accept real providers; loop pages; widen type hints `DeterministicOcrEngine|None` → `OcrEngine|None`; `storage_uri` (`:546`) → `s3://` |
| Result shape | `VisualIngestionResult` | `src/raku_rag/workers/ingestion.py:490-496` | carry per-page assets / structured content |
| Crops | `CropService.create_region_crop` | `src/raku_rag/services/crop.py:47-95` | render bbox → S3; replace `memory://` (`:73`,`:79`,`:80-82`) |
| Visual chunks | `visual_chunks_from_ingestion` | `src/raku_rag/services/visual.py:17-55` | attach `_mfg_meta` + structured-kind metadata |
| Ingest route | `POST /internal/ingest` | `apps/answer-service/server.py:1916-1957` (`:1944`) | add `content_type` branch → visual ingest |
| Answer VLM path | `answer` use_vlm / `_layout_region_from_chunk` | `src/raku_rag/services/answer.py:271-294`, `:672` | propagate mfg-meta into `LayoutRegion`; filter non-approved regions for high-risk |
| Safety gate | `is_approved_effective` / `SafetyGate.evaluate` / `normalize_block_reason` | `src/raku_rag/manufacturing/safety/gate.py:51`, `:73`, `:157` | unchanged — already generic over `Citation`; visual works once mfg-meta is attached |
| Visual citation + demotion | `ManufacturingCitation.from_base` / high-risk demotion | `src/raku_rag/manufacturing/api/answer_ext.py:335`, `:358-375` | call `from_base` for visual chunks; add primary-promotion verifier hook |
| IAM / runtime env | `grantBedrockInvoke` / `productionRuntimeEnvironment` | `infra/cdk/lib/raku-rag-stack.ts:1205`, `:99-107` | add `grantTextractInvoke`; new `ocrProvider`/`vlmProvider` context + env |

---

## 2. Provider Adapters, Selection & ProviderPolicy (vendor-neutral)

> This is the **single, binding provider contract** for all six visual capabilities — the earlier AWS-only draft was **deleted** to keep one source of truth. The contract is a vendor-neutral capability registry + a per-vendor normalization seam, selectable per-capability and per-tenant. The concrete **AWS-now implementation** (Textract OCR/layout/structured + Bedrock Claude vision) is specified inline in §2.4 (vendor→neutral mappings) and §6.1; adopting Google Vertex AI (Document AI + Gemini + Vertex embeddings), Azure, or OSS becomes a conformant adapter + config flip with **zero** changes to retrieval/answer/safety code. The deterministic offline providers remain the default; Tier-A (`scripts/gate.sh`) stays stdlib-only and byte-for-byte green.

### 2.0 Design thesis

The parser stack already proves the pattern: one `ParserClient` protocol (`workers/ingest/providers/parsers/__init__.py:37`), one `ParserProviderAdapter` base (`:88`), concrete `TextractParserAdapter`/`AzureDocumentIntelligenceParserAdapter`/`GoogleDocumentAIParserAdapter` (`:182`/`:204`/`:226`), one policy-driven `ProviderPolicyParserRouter` (`:248`) with fallback + `raw_content_sent` audit (`:50`,`:354-375`), gated by an already-operation-agnostic `ProviderPolicyEnforcer.evaluate` (`workers/ingest/provider_policy.py:148-208`). We generalize that to **all six visual capabilities** (`ocr`/`layout`/`structured`/`vlm`/`caption`/`embedding`). Two seams replace the lossy `parse -> str | Mapping` shape:

1. **Capability protocol** — stable, returns the *neutral internal model*; the only thing retrieval/answer/safety ever see.
2. **`*Normalizer` adapter (per vendor)** — translates one raw vendor response *into* the neutral model. The normalizer is the **only** code that knows Textract `Block`, Google `Document`, Azure `AnalyzeResult`, or a Gemini/Claude vision payload.

FR-048 (`spec.md:1074`; `interfaces/base.py:100`; `services/visual.py:12`) is enforced **at the fusion point and the conformance suite**, not "by the type system" — that earlier claim was false and is dropped (see review must-fix). The mechanical guards are: (a) two *actually-disjoint* provenance value-spaces; (b) a centralized `PROMOTABLE_EXTRACTION_SOURCES` allowlist membership test (never `!= "vlm"`); (c) a fail-closed default for absent provenance; (d) a HARD per-`(capability,vendor)` conformance test that a caption string is byte-absent from the OCR slot.

### 2.1 Neutral model extensions — `src/raku_rag/domain/models.py`

**The current `BoundingBox` (`models.py:145-152`) is Textract's shape frozen as "neutral"** — `{x,y,width,height}` 0..1 is byte-for-byte `Geometry.BoundingBox{Left,Top,Width,Height}`, which forced every non-AWS vendor to silently collapse its polygon/rotation to an AABB. Fix it — extend, keep the AABB for back-compat:

```python
@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned box in 0..1 page space. x/y/width/height are the AABB consumers use
    unchanged; quad is the vendor-faithful polygon; ALL coords MUST be in [0,1]."""
    x: float; y: float; width: float; height: float           # AABB (unchanged; retrieval/crop read this)
    quad: tuple[tuple[float, float], ...] = ()                 # NET-NEW: 4 normalized polygon points (0..1)
    page_rotation_deg: float = 0.0                             # NET-NEW: 0/90/180/270 or measured skew
```

Every normalizer MUST populate `quad` (faithful geometry) **and** derive the AABB. Textract `Geometry.Polygon` → `quad` (degenerate from `BoundingBox` if absent), AABB verbatim; Document AI `boundingPoly.normalizedVertices` → `quad`, AABB = `(min x, min y, max x−min x, max y−min y)`; Azure `polygon[8]` → 4-point `quad`, AABB by min/max. Conformance asserts every AABB and `quad` coordinate ∈ [0,1].

**One canonical provenance vocabulary** (the earlier design had THREE incompatible spellings — `textract`/`aws_textract`/the `!= "vlm"` sentinel — and a *shared* `"deterministic"` value across both enums that broke the "disjoint" claim). Replace with two **actually-disjoint** value-spaces plus a single membership set:

```python
class ExtractionSource(str, Enum):              # TRANSCRIPTION / structured provenance — promotable space
    DETERMINISTIC_OCR  = "deterministic_ocr"
    AWS_TEXTRACT       = "aws_textract"
    GOOGLE_DOCAI       = "google_docai"
    AZURE_DOCINTEL     = "azure_docintel"
    OSS_TESSERACT      = "oss_tesseract"
    SPREADSHEET_PARSER = "spreadsheet_parser"   # reconciles §4.3:747 spreadsheet path

class CaptionSource(str, Enum):                 # VLM / caption provenance — NON-promotable space (DISJOINT)
    DETERMINISTIC_VLM     = "deterministic_vlm"
    BEDROCK_CLAUDE_VISION = "bedrock_claude_vision"
    GOOGLE_GEMINI         = "google_gemini"
    AZURE_OPENAI_VISION   = "azure_openai_vision"
    OSS_LLAVA             = "oss_llava"

# THE single safety gate vocabulary. §5 promotion + answer_ext demotion membership-test THIS set.
PROMOTABLE_EXTRACTION_SOURCES: frozenset[str] = frozenset(e.value for e in ExtractionSource)
# Hard invariant (asserted by a test, see §2.8): the two spaces never intersect.
assert PROMOTABLE_EXTRACTION_SOURCES.isdisjoint({c.value for c in CaptionSource})
```

Note `deterministic_ocr` vs `deterministic_vlm` — the default profile is exactly where the old shared `"deterministic"` value would have admitted a caption as primary evidence; that hole is now closed.

Additive fields (defaults keep Tier-A green):
- `OcrTextRegion` (`models.py:155-160`): add `extraction_source: str = ""` (an `ExtractionSource` value). **Confidence is pinned to 0..1** in the docstring; every normalizer converts (Textract `Confidence/100`). A Textract normalizer that forgets `÷100` is caught by the conformance `0<=confidence<=1` assertion (§2.8).
- `LayoutRegion` (`models.py:178-193`): add `extraction_source: str = ""` (provenance of `ocr_text`, the transcription slot), `caption_source: str = ""` (provenance of `generated_caption_text`, the caption slot), `transcription_confidence: float | None = None`. `primary_evidence_text` stays **derived from `ocr_text` only** at chunking (`services/visual.py:50`).

**Structured types are defined ONCE in §4.3** (`StructuredTable`/`StructuredTableColumn`/`StructuredTableCell`/`StructuredTableRow`, `FormField`, `ChartSeries`/`ChartPoint`, `FigureCaption`, and the `structured_content` dict envelope) — there is no second definition here. This subsection only states the **provenance contract** they must satisfy, which every per-vendor `StructuredNormalizer` (§2.4) stamps:

- Transcription types — `StructuredTable`, `FormField`, and a **printed** `FigureCaption` (caption text physically present on the page, read by OCR) — carry an `extraction_source` holding an `ExtractionSource` value, so they are membership-promotable by the §5 gate.
- The VLM-inferred `ChartSeries` (chart→numeric is a model inference, §0.5-A3) carries a `caption_source` holding a `CaptionSource` value, so it is **never** promotable — guaranteed by the `PROMOTABLE_EXTRACTION_SOURCES` membership test, not a special case.
- A VLM-*generated* caption is **NOT** a `FigureCaption`; it lives in `LayoutRegion.generated_caption_text` + a `CaptionSource` and is retrieval-aid only (FR-048). `FigureCaption` never carries a generated/inferred value.

**Neutral `FeatureType`** (the old `AsyncSubmitRequest.feature_types=("TABLES","FORMS","QUERIES","LAYOUT")` leaked Textract enum strings; `QUERIES` has no Document AI equivalent):

```python
class FeatureType(str, Enum):
    TABLES = "tables"; FORMS = "forms"; KEY_VALUE = "key_value"; LAYOUT = "layout"
# QUERIES is AWS-only — never in the neutral default; the AWS normalizer may bolt it on per-vendor.
_VENDOR_FEATURE_MAP: dict[str, dict[FeatureType, str]] = {
    "aws_textract": {FeatureType.TABLES: "TABLES", FeatureType.FORMS: "FORMS",
                     FeatureType.KEY_VALUE: "FORMS", FeatureType.LAYOUT: "LAYOUT"},
    "google_document_ai": {},   # DocAI processor handles tables/forms natively — no per-call token list
    "azure_document_intelligence": {},
}
```

### 2.2 The six capability protocols (neutral return) — `src/raku_rag/interfaces/visual.py` (net-new, re-exported from `interfaces/base.py:91-110`)

Generalize the five protocols at `interfaces/base.py:91-110`, carry the ingestion context the deterministic layout impl already needs (the real signature enforced by `VisualIngestionExecutor.execute_image`, §0.5-B1), add `StructuredExtractor`, and — critically — **put pixels into the VLM/caption seam via a `CropResolver`** (the old `VLMProvider.generate(query, *, visual_regions: Sequence[LayoutRegion])` at `:110` carried only a `crop_uri`, forcing the first real Gemini/Bedrock adapter to inline an S3 client to dereference it):

```python
@dataclass(frozen=True)
class IngestContext:
    tenant_id: str; collection_id: str; document_id: str; asset_id: str; page_number: int = 1

class CropResolver(Protocol):
    """The ONLY way an adapter obtains pixels. Backed by the same CropStore (InMemoryCropStore /
    S3CropStore / GcsCropStore) used for persistence, so NO adapter ever builds a boto3/gcs client
    to fetch image bytes. Resolves s3://, gs://, memory:// uniformly."""
    def bytes_for(self, region: LayoutRegion) -> bytes: ...

class OcrEngine(Protocol):                          # transcription
    def extract(self, image: bytes, *, ctx: IngestContext) -> tuple[OcrTextRegion, ...]: ...

class LayoutExtractor(Protocol):                    # layout geometry + region typing (real :B1 signature)
    def extract(self, image: bytes, *, ctx: IngestContext,
                ocr_regions: Sequence[OcrTextRegion] | None = None) -> tuple[LayoutRegion, ...]: ...

class StructuredExtractor(Protocol):                # NET-NEW: tables/forms/printed-captions
    def extract(self, image: bytes, *, ctx: IngestContext) -> StructuredContent: ...

class CaptioningProvider(Protocol):                 # VLM-generated caption (search aid only, FR-048)
    def caption(self, *, region: LayoutRegion, crops: CropResolver, ctx: IngestContext) -> CaptioningResult: ...

class VLMProvider(Protocol):                        # visual answer generation; pixels via CropResolver
    def generate(self, query: str, *, visual_regions: Sequence[LayoutRegion], crops: CropResolver) -> VlmResult: ...

class VisualEmbeddingProvider(Protocol):
    def embed(self, regions: Sequence[bytes]) -> list[Vector]: ...
```

`CaptioningResult` already exists (`providers/captioning/__init__.py:10-15`) — extend with `caption_source: str = ""`. Net-new `VlmResult` (replaces the bare `str` return at `interfaces/base.py:110` / `providers/vlms/__init__.py:23`):

```python
@dataclass(frozen=True)
class VlmResult:
    text: str                                       # answer/caption text — VLM provenance
    caption_source: str = ""                         # CaptionSource value
    grounded_region_ids: tuple[str, ...] = ()        # OCR regions it claims to ground on (for §5 gate)
```

Both `CaptioningResult.generated_caption_text` and `VlmResult.text` are caption-side: no field of either lands in `ocr_text`/`primary_evidence_text`/`StructuredContent`. The deterministic providers stay structural duck-matches with no AWS import.

### 2.3 Per-vendor normalization seam — `workers/ingest/providers/normalize/`

A normalizer is the structural analog of `ParserProviderAdapter` (`parsers/__init__.py:88`) but does *shape translation*, not extraction. Raw I/O stays behind an `Invoker` seam exactly like `BedrockInvoker` (`providers/llms.py:153-187`, lazy boto3 at `:167-169`) so the deterministic path imports no cloud SDK.

```python
# normalize/base.py
RawT = TypeVar("RawT"); NeutralT = TypeVar("NeutralT")

class VisualNormalizer(Protocol[RawT, NeutralT]):
    capability_type: str        # 'ocr'|'layout'|'structured'|'vlm'|'caption'|'embedding'
    provider: str               # registry/policy key, e.g. 'aws_textract' (matches allowlists)
    provider_family: str        # 'aws'|'google'|'azure'|'oss'|'deterministic'
    extraction_method: str      # 'transcription' | 'generative'  (NET-NEW; see generative-OCR guard, §2.8)
    def normalize(self, raw: RawT, *, ctx: IngestContext) -> NeutralT: ...
```

**The provenance label is computed in ONE place** — `source_tag_for(provider, capability_type)` — so the adapter, `assemble_region`, the §5 gate, and conformance all read the identical value space:

```python
# normalize/source_tags.py — the SINGLE provider_id -> source_tag map (kills the 3-spelling drift)
_OCR_FAMILY = {                                    # ocr|layout|structured -> ExtractionSource value
    "deterministic": "deterministic_ocr", "aws_textract": "aws_textract",
    "google_document_ai": "google_docai", "azure_document_intelligence": "azure_docintel",
    "tesseract": "oss_tesseract", "spreadsheet": "spreadsheet_parser", "customer_managed": "customer_managed_ocr",
}
_VLM_FAMILY = {                                    # vlm|caption -> CaptionSource value
    "deterministic": "deterministic_vlm", "bedrock": "bedrock_claude_vision",
    "google_gemini": "google_gemini", "azure_openai_vision": "azure_openai_vision", "oss_llava": "oss_llava",
}
def source_tag_for(provider: str, capability_type: str) -> str:
    table = _VLM_FAMILY if capability_type in {"vlm", "caption"} else _OCR_FAMILY
    return table[_normalize_provider(provider)]
```

Typed sub-protocols pin the return type per capability (this is what the conformance suite verifies — not the Python type system alone):

| Normalizer protocol | `capability_type` | source-tag space | `normalize(...) -> ` | writes into |
|---|---|---|---|---|
| `OcrNormalizer` | `ocr` | `ExtractionSource` | `tuple[OcrTextRegion, ...]` | `ocr_text` |
| `LayoutNormalizer` | `layout` | `ExtractionSource` | `tuple[LayoutRegion, ...]` | geometry + `ocr_text` |
| `StructuredNormalizer` | `structured` | `ExtractionSource` | `StructuredContent` | `metadata['structured_content']` |
| `CaptionNormalizer` | `caption` | `CaptionSource` | `CaptioningResult` | `generated_caption_text` |
| `VlmNormalizer` | `vlm` | `CaptionSource` | `VlmResult` | answer text only |

Per-vendor concrete normalizers (each implements only the capabilities its vendor offers): `normalize/aws.py` (`AwsTextract{Ocr,Layout,Structured}Normalizer` source_tag `aws_textract`; `BedrockVision{Caption,Vlm}Normalizer` source_tag `bedrock_claude_vision`); `normalize/google.py` (`GoogleDocAi{Ocr,Layout,Structured}Normalizer` `google_docai`; `GoogleGemini{Caption,Vlm}Normalizer` `google_gemini`) **[LATER]**; `normalize/azure.py` **[LATER]**; `normalize/oss.py` **[LATER]**; `normalize/deterministic.py` (thin wrappers tagging existing `DeterministicOcrEngine`/`DeterministicLayoutExtractor`/`DeterministicCaptioningProvider` output with `deterministic_ocr`/`deterministic_vlm`). Each production capability provider = `Invoker` (raw call) + matching `*Normalizer`; `extract()` fails closed if the invoker is `None` (cf. `llms.py:141-145`).

### 2.4 Concrete vendor → neutral mappings (AWS now; others spec-only)

**4a. AWS Textract `Block[]`** (`AwsTextract*Normalizer`, IMPLEMENT NOW). Geometry already 0..1: `Geometry.BoundingBox{Left,Top,Width,Height}` → AABB verbatim, `Geometry.Polygon` → `quad`; **`Block.Confidence/100` → `confidence` (0..1)**; `Block.Page` → `page_number`. `LINE/WORD/LAYOUT_TEXT` → `OcrTextRegion`/`LayoutRegion(region_type='text', ocr_text=Text)`; `LAYOUT_TITLE/SECTION_HEADER` → `heading_path`; `LAYOUT_FIGURE` → `LayoutRegion(region_type='figure')` (no `ocr_text`, later VLM caption); `TABLE`+`CELL` → `StructuredTable`/`StructuredTableCell`; `KEY_VALUE_SET[KEY]→[VALUE]` → `FormField`; caption lines under a figure → `FigureCaption`. All transcription types stamped `extraction_source='aws_textract'`.

**4b. Google Document AI `Document`** (`GoogleDocAi*Normalizer`, SPEC-ONLY/LATER). Text is offset-encoded — slice `document.text` by `layout.textAnchor.textSegments[{startIndex,endIndex}]`. **CJK risk: offsets are UTF-8/surrogate-sensitive; a mandatory Japanese golden (§2.8) gates this.** Geometry is polygons: `boundingPoly.normalizedVertices[]` (0..1) → `quad`, derive AABB; `pages[].tables[].{headerRows,bodyRows}[].cells[]` → `StructuredTable`/`StructuredTableCell`; `pages[].formFields[]` → `FormField`; `entities[]` → `FormField`. Confidence on `entities[].confidence` only → set where present, else `None` (the §5 gate treats `None` as not-strongly-grounded). All transcription types stamped `extraction_source='google_docai'`.

**4c. Bedrock Claude vision / Vertex Gemini** (`BedrockVision*`, `GoogleGemini*`) produce **only** caption/answer text. Bedrock `invoke_model` body → join `payload['content']` text blocks (mirrors `llms.py:182-185`); Gemini → join `response.candidates[0].content.parts[].text`. Both → `CaptioningResult(caption_source='bedrock_claude_vision'|'google_gemini')` / `VlmResult(...)`, written **only** to `generated_caption_text`/answer, **never** `ocr_text`. Both caption normalizers MUST route text through `Redactor.redact_visual_text()` before populating the field (same boundary as the deterministic captioner, `captioning/__init__.py:47-51`); redaction-before-persist is vendor-invariant.

### 2.5 The single fusion point (FR-048) — `src/raku_rag/services/visual.py`

Introduce `assemble_region(...)` as the *only* place transcription and caption merge into a `LayoutRegion`, and make `visual_chunks_from_ingestion` (`services/visual.py:17-55`) **stamp provenance and fail closed when it is absent**:

```python
def assemble_region(*, base: LayoutRegion, ocr: OcrTextRegion | None,
                    caption: CaptioningResult | None) -> LayoutRegion:
    if ocr is not None:
        assert ocr.extraction_source in PROMOTABLE_EXTRACTION_SOURCES   # transcription space
        base.ocr_text = ocr.text
        base.extraction_source = ocr.extraction_source
        base.transcription_confidence = ocr.confidence
    if caption is not None and caption.status == "succeeded":
        assert caption.caption_source in {c.value for c in CaptionSource}   # disjoint space
        base.generated_caption_text = caption.generated_caption_text       # caption slot ONLY
        base.caption_source = caption.caption_source
    return base
```

In `visual_chunks_from_ingestion`, alongside the existing `primary_evidence_text = region.ocr_text` (`:50`), add `metadata['primary_evidence_source'] = region.extraction_source` and `metadata['caption_source'] = region.caption_source`. **Today this propagation is missing entirely** (verified: `visual.py:36-52` copies `ocr_text`/`generated_caption_text` but no source), which is exactly why a `!= "vlm"` gate failed open on the empty default. The §5 promotion gate then membership-tests:

```python
def is_promotable_evidence(meta: Mapping[str, object]) -> bool:
    src = str(meta.get("primary_evidence_source") or "")
    return src in PROMOTABLE_EXTRACTION_SOURCES        # empty/unknown/caption -> NOT promotable (fail closed)
```

`visual_chunk_text` (`:9-14`) continues to append the caption only as a retrieval aid.

### 2.6 Policy, capability registry, audit, credentials, selection (reuse + extend by data)

- **`ProviderCapability`** (`provider_policy.py:16-34`): add `capability_type: str = ""`, `extraction_method: str = "transcription"`, `credential_mode: str = "iam_task_role"` (`iam_task_role|gcp_wif|azure_msi|none`), `credential_audience: str = ""`, `allowed_egress_endpoints: tuple[str, ...] = ()`. `from_mapping` (`:26-34`) reads them tolerantly.
- **`DEFAULT_PROVIDER_CAPABILITIES`** (`:234-278`) becomes a 2-key `dict[tuple[capability, provider], ProviderCapability]`; `capability_for` (`:281-298`) gains a `capability` arg. **C8 region fix lands NOW:** `aws_textract`/`bedrock` region `us-east-1` (`:238`,`:245`) → `ap-northeast-1`. Google/Azure rows default **`zero_retention=False, no_train=False`** (fail-closed — do NOT hardcode `True` on an unverifiable cross-cloud assumption; `zero_retention=True` may be set only by a per-tenant override carrying an operator attestation, see §2.8); their `region` defaults move to `asia-northeast1` / `japaneast` so a JP-residency tenant flip is not auto-rejected on region. `extraction_method="generative"` is set on any generative "OCR" processor so it is excluded from `PROMOTABLE_EXTRACTION_SOURCES` even though it writes `ocr_text` (generative-OCR guard).
- **`ProviderPolicy`** (`:37-104`): add `allowed_layout_providers`, `allowed_structured_providers`, `allowed_vlm_providers`, `allowed_caption_providers` (defaults mirror `allowed_ocr_providers` at `:43`), parsed via the existing `tuple_field` helper (`:58-62`). Replace the single global `customer_opt_in_status` (`:53`) usage with per-family `opt_in_status_by_family: Mapping[str,str]` (back-compat: the legacy field seeds the `aws` family) — allowing a Google region must NOT imply Google sub-processor consent. **Add a load-time validation: a policy whose `fallback_policy` target (or whose allowlist) lacks a self-permitted last-resort (`deterministic`/`customer_managed`) is rejected** — this prevents the all-Google tenant DLQ-storm where the fallback candidate is re-evaluated (`parsers/__init__.py:301`) and rejected because `deterministic` is not in its allowlist.
- **`ProviderPolicyEnforcer._operation_allowlist_field`** (`:139-146`): add `layout`/`structured`/`vlm`/`caption`. `evaluate()` (`:148-208`) needs **no logic change** — allowlist (`:154-160`), cross-cloud (`:174-179`), region (`:181-186`), zero-retention (`:188-189`), no-train (`:191-192`), opt-in (`:194-199`) already apply to every vendor. Generalize the parser-mode opt-in branch (`:162-172`) so the document-extraction family (`parse/ocr/layout/structured`) requires the `google`/`azure` token, restoring the second lock for the new ops.
- **Router**: generalize `ProviderPolicyParserRouter` (`:248`) into `CapabilityRouter(capability_type=...)`, reusing `adapters` (`:262`), `_evaluate` (`:334`), the two-phase `raw_content_sent` audit (`:273-330`,`:354-375`) verbatim; only `ProviderRequest(operation=capability_type, ...)` (`:343`) changes. **Fix the fallback last-resort:** `_fallback_candidates` (`:350-352`) currently hardcodes `["customer_managed", "tesseract"]` — `tesseract` is an OSS *OCR* provider, invalid as a vlm/caption fallback. Replace with the capability-appropriate offline adapter: `[decision.fallback_provider, "customer_managed", "deterministic"]`, terminating at `deterministic` so a vlm fallback degrades offline instead of raising.
- **Audit**: extend `ParserProviderAuditEvent` (`:41-66`) with `capability_type: str` and `source_tag: str`; emit `raw_content_sent=False` before evaluation and `True` only when image bytes reach a vendor invoker — identical to `:285`/`:319`.
- **Selection factories** — `src/raku_rag/providers/factories.py` (net-new): `ocr_from_settings`/`layout_from_settings`/`structured_from_settings`/`vlm_from_settings`/`captioning_from_settings`/`visual_embedding_from_settings`, each cloning `llm_provider_from_settings` (`llms.py:190-219`): explicit per-capability override wins; else branch on `runtime_profile`; deterministic default keeps Tier-A stdlib-only. A global **`RAKU_FORCE_DETERMINISTIC` kill switch** short-circuits every factory to the offline adapter regardless of per-capability settings — the instant, no-redeploy rollback. New `Settings` fields `ocr_provider`/`layout_provider`/`structured_provider`/`vlm_provider`/`caption_provider`/`visual_embedding_provider` (default `"deterministic"`) wired next to `embedding_provider` (`core/config.py:30`,`:142`); **`aws_region` default (`:35`) changes `us-east-1` → `ap-northeast-1`**, and a guard requires a capability's region be explicitly resolved before any residency/region check (no silent `us-east-1`).
- **Credentials seam** — `src/raku_rag/providers/credentials.py` (net-new). `CredentialProvider` protocol with `AwsTaskRoleCredentials` (boto3 default chain via ECS task role) and `GcpWorkloadIdentityCredentials`. **The GCP path is built for ECS Fargate, NOT IRSA:** a `google.auth` `external_account` credential with an `"aws"` credential source — `regional_cred_verification_url="https://sts.{aws_region}.amazonaws.com?Action=GetCallerIdentity&Version=2011-06-15"`, `audience=//iam.googleapis.com/projects/{n}/locations/global/workloadIdentityPools/{pool}/providers/{provider}` — signing `GetCallerIdentity` with the **Fargate task-role creds from the container credential endpoint (`AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`)**. There is **no** web-identity token file on Fargate; all `AWS_WEB_IDENTITY_TOKEN_FILE` language is dropped. No long-lived service-account JSON key ever exists. Lazily imported so deterministic stays stdlib.

### 2.7 Net-new symbols → files; now vs. later

| Symbol(s) | File |
|---|---|
| `BoundingBox.quad/page_rotation_deg`, `ExtractionSource`, `CaptionSource`, `PROMOTABLE_EXTRACTION_SOURCES`, `FeatureType`, and the §4.3 structured types (`StructuredTable`/`StructuredTableColumn`/`StructuredTableCell`/`StructuredTableRow`, `FormField`, `ChartSeries`/`ChartPoint`, `FigureCaption` + the `structured_content` envelope); `OcrTextRegion`/`LayoutRegion` provenance fields | `src/raku_rag/domain/models.py` |
| `IngestContext`, `CropResolver`, `StructuredExtractor`, evolved `OcrEngine/LayoutExtractor/CaptioningProvider/VLMProvider`, `VlmResult` | `src/raku_rag/interfaces/visual.py` (re-export from `interfaces/base.py:91-110`) |
| `VisualNormalizer` + typed sub-protocols, `source_tag_for` | `workers/ingest/providers/normalize/{base,source_tags}.py` |
| `AwsTextract*Normalizer`, `BedrockVision*Normalizer`, `Deterministic*Normalizer` | `normalize/{aws,deterministic}.py` **(NOW)** |
| `GoogleDocAi*`/`GoogleGemini*`, `AzureDocIntel*`/`AzureOpenAiVision*`, `OssTesseract*`/`OssLlava*` | `normalize/{google,azure,oss}.py` **(LATER, conformance-gated)** |
| `CapabilityRouter` (generalized `ProviderPolicyParserRouter`) | `workers/ingest/providers/capability_router.py` |
| `assemble_region`, `is_promotable_evidence` | `src/raku_rag/services/visual.py` |
| `*_from_settings`, `RAKU_FORCE_DETERMINISTIC` | `src/raku_rag/providers/factories.py` |
| `CredentialProvider`, `AwsTaskRoleCredentials`, `GcpWorkloadIdentityCredentials` | `src/raku_rag/providers/credentials.py` |

**Implement now:** neutral model, protocols, AWS normalizers, deterministic normalizers, `CapabilityRouter`, factories, policy/audit/region/credential extensions. **Specify-only (conformance-validated later):** `GoogleDocAi*`/`GoogleGemini*`, `Azure*`, `Oss*`. Default profile stays deterministic — Tier-A green, unchanged.

---

## 2.8 Provider Portability & Vendor Switching (AWS ⇄ Google Vertex AI ⇄ Azure ⇄ OSS)

This section specifies the portability *guarantee*: any capability adapter from any vendor is admissible **iff** it passes one shared conformance battery and is declared in the capability matrix. Nothing here touches retrieval/answer/safety code.

### 2.8.1 The neutral seams (recap) and what they buy

The frozen contracts are: the neutral model (`domain/models.py` — `BoundingBox` with `quad`, `OcrTextRegion`/`LayoutRegion` + provenance, `StructuredContent`), the six protocols (`interfaces/visual.py`), `PROMOTABLE_EXTRACTION_SOURCES`, and the `ProviderPolicy`/`ProviderCapability`/`_operation_allowlist_field` routing data. A vendor plugs in by (1) writing `*Normalizer`s into the neutral model, (2) registering a `(capability, provider_id)` factory + a `DEFAULT_PROVIDER_CAPABILITIES` row, (3) passing the conformance battery, (4) flipping config. Per-capability selection (`Settings.*_provider`) is overridden by the per-tenant `ProviderPolicy` allowlist, so **tenant-A can run all-Google while tenant-B stays all-AWS on the same deployment**; whole-stack switch is the degenerate case where every `RAKU_*_PROVIDER` points at one vendor and each `allowed_*_providers` is widened to it.

### 2.8.2 Vendor-neutral async document analysis (Textract async ⇄ Document AI LRO ⇄ Azure operation-location)

Multi-page PDFs cannot ride the sync `OcrEngine.extract(image)` seam (`interfaces/base.py:91`). Per §0.5-B2 (`spec.md:62`) we add an explicit async boundary, generalized to one vendor-opaque `JobHandle` + one normalized `DocumentAnalysis`:

```python
class AsyncDocumentAnalyzer(Protocol):
    provider: str; provider_family: str
    def submit(self, request: AsyncSubmitRequest) -> JobHandle: ...
    def poll(self, handle: JobHandle) -> AsyncPollResult: ...
    def capability(self) -> ProviderCapability: ...

class AsyncJobStatus(str, Enum):
    PENDING = "pending"; SUCCEEDED = "succeeded"
    MORE_AVAILABLE = "more_available"     # pagination — more shards/tokens to fetch (Textract NextToken, DocAI shards)
    PARTIAL_FAILURE = "partial_failure"   # Textract JobStatus=='PARTIAL_SUCCESS' — some PAGES failed (handled, not silently OK)
    FAILED = "failed"

@dataclass(frozen=True)
class Continuation:                       # structured cursor — NOT a single Textract NextToken
    next_token: str = ""                  # Textract
    shards: tuple[str, ...] = ()          # DocAI/Azure remaining output-object names
    shard_index: int = 0
    def more(self) -> bool: return bool(self.next_token) or self.shard_index < len(self.shards)
```

`AsyncSubmitRequest.feature_types` defaults to the **neutral** `(FeatureType.TABLES, FeatureType.FORMS, FeatureType.LAYOUT)` (no `QUERIES`). `JobHandle.token` is vendor-opaque (Textract `JobId` | DocAI LRO operation name | Azure operation-location), persisted verbatim into the generalized `IngestionRun.async_job_id`/`async_provider` columns (migration `0014`, §0.5-B5). `poll()` returns a normalized, **already-redacted** `DocumentAnalysis` (§2.5) — the worker never sees a vendor block/Document shape, and `_index_analysis` runs `Redactor.redact_visual_text()` over every `OcrTextRegion.text` and structured cell **before** `visual_chunks_from_ingestion`, so redaction is path-invariant across the sync executor (`ingestion.py:571`) and the async multi-page path for **both** Textract and Document AI. Textract `PARTIAL_SUCCESS` maps to `PARTIAL_FAILURE` (persist succeeded pages, mark failed ones, never an empty-OCR success); pagination maps to `MORE_AVAILABLE` and advances `Continuation`.

**The GCS bridge is a first-class deliverable, not an assumption.** Textract async reads only S3; Document AI `batchProcessDocuments` reads only GCS and writes sharded GCS output. Today all bytes live in S3/`memory://` (`S3Connector._parse_ref` only understands `s3://`), so a `gs://` `document_ref` has no producer. Therefore: add a `VendorStagingResolver` seam + a `GcsConnector`; `AsyncSubmitRequest.document_ref` is **family-resolved** (S3 for Textract, GCS for Document AI) by copying the source object into the analyzer family's native bucket before `submit`, with cleanup-on-DLQ. CDK provisions a GCS input/output bucket in `asia-northeast1` with an aggressive deletion lifecycle (zero-retention) and WIF object perms. **Until the bridge is provisioned, the Google OCR matrix cell stays `spec_later` and the enforcer refuses `google_document_ai` OCR (fail-closed) rather than assume `gs://` inputs exist.**

### 2.8.3 Multi-cloud policy, credentials (WIF), residency

- **Credentials (WIF, Fargate-correct):** as §2.6 — `external_account` `"aws"` source signing `GetCallerIdentity` from the container credential endpoint against `sts.{aws_region}.amazonaws.com`, exchanged at `sts.googleapis.com`. The egress allowlist MUST therefore include **both** `sts.{aws_region}.amazonaws.com` (to sign) and `sts.googleapis.com` (to exchange) — the earlier draft omitted the AWS STS endpoint, which would have broken token exchange under lockdown.
- **Egress backstop (real, not aspirational):** `ecsSecurityGroup` is `allowAllOutbound: true` (`infra/cdk/lib/raku-rag-stack.ts:326`), so the "network-layer backstop" did not exist. Replace with deny-by-default egress to the per-family endpoint set: `textract.ap-northeast-1.amazonaws.com` / `bedrock-runtime.ap-northeast-1.amazonaws.com` (prefer interface VPC endpoints to avoid the single NAT, `:139`), plus `*-documentai.googleapis.com` / `asia-northeast1-aiplatform.googleapis.com` / `sts.googleapis.com` / `sts.{aws_region}.amazonaws.com`. `allowed_egress_endpoints` on `ProviderCapability` is the policy-layer twin (deny → `ProviderPolicyViolation`).
- **Zero-retention is runtime-verified, not a static lie:** `zero_retention=True` on a Google/Azure descriptor requires a startup/periodic GCP config-attestation check (or an operator-signed attestation artifact) that the Document AI processor (no human review + immediate delete) and Gemini project (abuse-monitoring zero-retention exception) are actually provisioned; absent attestation, the default stays `False` and `evaluate()` (`provider_policy.py:188-189`) fails closed.
- **Per-document residency aggregate (`evaluate_residency`), MANDATORY before any submit/egress:** `evaluate()` checks one `capability.region` per leg, which lets a document's bytes split across clouds/regions while each leg passes. Add a `JURISDICTION_OF_REGION` map (`ap-northeast-1`/`asia-northeast1`→`JP`) and an aggregate over the set of capabilities touching one document, keyed on **jurisdiction not region-string**, with `single_region` / `single_jurisdiction` / `home_jurisdiction_only` semantics, gated additionally on **per-family** opt-in. Worked case: OCR=`google_document_ai`@`asia-northeast1` (JP) + VLM=`bedrock`@`ap-northeast-1` (JP) → allowed under `single_jurisdiction` iff `cross_cloud_processing_allowed=True` AND both families have granted consent; the same split with VLM@`us-east-1` is flagged cross-border and raises before the invoker runs. Same-family cross-region (Bedrock JP + Bedrock US) is also caught. `cross_cloud_processing_allowed` default stays `False`.

### 2.8.4 Conformance battery (gates LATER adapters) + capability matrix

`src/raku_rag/providers/capability_matrix.py` is the SSOT registry; `scripts/conformance.sh matrix` renders it to `specs/021-visual-pdf-understanding-prod/capability-matrix.md` with a docs-drift gate. A single parameterized suite asserts, for **every** registered `(capability, provider_id)` — Google/Azure/OSS included, with a replayed `<provider>.raw.json` so Tier-A imports no cloud SDK:

1. **Neutral type + 0..1 geometry** — output is the neutral type; every AABB and `quad` coord ∈ [0,1]; `0<=confidence<=1` (catches a Textract `÷100` miss).
2. **Provenance correctness** — `extraction_source ∈ PROMOTABLE_EXTRACTION_SOURCES` for OCR/layout/structured, `caption_source ∈ CaptionSource` for vlm/caption; the two sets are disjoint (hard assertion `PROMOTABLE_EXTRACTION_SOURCES.isdisjoint(CaptionSource values)`).
3. **`test_fr048_caption_not_in_ocr_slot`** (HARD, every vendor) — given a golden where the vendor returns both OCR text and a caption, the caption string is **byte-absent** from `ocr_text`/`primary_evidence_text`/`StructuredContent`; a Gemini caption normalized into `ocr_text` is a hard fail.
4. **Deny-before-egress spy** — a denying `ProviderPolicy` raises `ProviderPolicyViolation` **before** the invoker is touched (spy invoker records zero calls); allowed → exactly one `raw_content_sent=True` event after the pass event.
5. **Redaction-before-persist** — `_EMAIL`/`_SECRET` (`parsers/__init__.py:33-34`) redacted before the first store `put` (spy `CropStore`/`VectorStore`).
6. **Async lifecycle** — `submit→PENDING…→SUCCEEDED` yields `page_count==expected`; `MORE_AVAILABLE` re-polls without partial persist; `PARTIAL_FAILURE` never becomes empty-OCR success; `JobHandle.from_row(to_token())` round-trips a Textract `JobId` and a DocAI LRO name; budget exhaustion → DLQ with `doc ocr_failed`.
7. **CropResolver** — a non-deterministic VLM/caption adapter MUST obtain pixels via `crops.bytes_for` (spy resolver asserts the adapter never built a cloud client).
8. **Generative-OCR guard** — an OCR/structured adapter must declare `extraction_method="transcription"`; a generative extractor is registered `generative` and its tag is excluded from `PROMOTABLE_EXTRACTION_SOURCES`.
9. **Mandatory CJK golden** — Japanese fixtures for offset-sliced text (Document AI `document.text` slicing) so a Latin-only golden cannot hide surrogate corruption on the actual KB language.

**Live-provider conformance** (`scripts/gate.sh conformance` → `workflow_dispatch`-gated `.github/workflows/provider-conformance-live.yml`, AWS via OIDC, Google via WIF) re-runs the same cases against live Textract/Bedrock/Document AI/Gemini and additionally asserts schema-drift (pinned processor/model version), latency/throughput SLO vs `target_visual_p95_latency_ms` (`config.py:26`), and 429/quota backoff — the gaps a replay suite is blind to. This is the job an operator runs before turning a matrix cell `✅`.

Two "zero-edit" guards make portability auditable: `test_no_vendor_leakage.py` (AST-scans `services/retrieval/answer/safety/domain` for `boto3`/`google.*`/`azure.*` imports and `provider_family ==` branching) and `test_provider_swap_invariance.py` (one golden query under `aws_textract+bedrock` vs `google_document_ai+google_gemini`; the **safety verdict and primary-evidence provenance MUST be identical** — only answer prose may differ).

**Capability matrix** (region/retention from the corrected `DEFAULT_PROVIDER_CAPABILITIES`; ✅ green = impl+conformance-green, ◻ spec_later, ⚠ partial, ✗ n/a):

| vendor (family) | ocr | layout | structured | vlm | caption | embedding | region / zero_ret / no_train |
|---|---|---|---|---|---|---|---|
| deterministic | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | local / yes / yes |
| aws_textract | ✅ | ✅ | ✅ | ✗ | ✗ | ✗ | ap-northeast-1 / yes / yes |
| bedrock | ✗ | ✗ | ✗ | ✅ | ✅ | ⚠ Titan opt-in | ap-northeast-1 / yes / yes |
| google_document_ai | ◻ | ◻ | ◻ | ✗ | ✗ | ✗ | asia-northeast1 / **attest** / **attest** |
| google_gemini | ✗ | ✗ | ✗ | ◻ | ◻ | ✗ | asia-northeast1 / attest / attest |
| vertex_embeddings | ✗ | ✗ | ✗ | ✗ | ✗ | ◻ (pin dim 256) | asia-northeast1 / attest / attest |
| azure_document_intelligence | ◻ | ◻ | ◻ | ✗ | ✗ | ✗ | japaneast / **no** / **no** |
| tesseract | ⚠ raster | ✗ | ✗ | ✗ | ✗ | ✅ (hashing) | local / yes / yes |

`vertex_embeddings` is config-only **only if** the adapter pins `output_dimensionality=256` to match the `vector(256)` pgvector column / `embedding_dim` (`config.py:31`); otherwise it needs a schema migration + full reindex (call-out, not a silent claim).

### 2.8.5 Worked example: adopt Vertex AI = adapters + config, zero safety/retrieval/answer edits

To move a tenant from **Textract + Bedrock** to **Google Document AI + Vertex Gemini**: (1) implement `GoogleDocAi{Ocr,Layout,Structured}Normalizer` + `GoogleGemini{Caption,Vlm}Normalizer` against §2.8.4; (2) provision the GCS bridge + WIF; (3) attest zero-retention; (4) flip config. No edits to `services/`, `retrieval/`, `answer/`, `safety/`, `domain/`.

**Before/after env (default single-tenant profile):**

```diff
  RAKU_RUNTIME_PROFILE=production
- RAKU_OCR_PROVIDER=aws_textract
- RAKU_LAYOUT_PROVIDER=aws_textract
- RAKU_STRUCTURED_PROVIDER=aws_textract
- RAKU_VLM_PROVIDER=bedrock
- RAKU_CAPTION_PROVIDER=bedrock
- AWS_DEFAULT_REGION=ap-northeast-1
+ RAKU_OCR_PROVIDER=google_document_ai
+ RAKU_LAYOUT_PROVIDER=google_document_ai
+ RAKU_STRUCTURED_PROVIDER=google_document_ai
+ RAKU_VLM_PROVIDER=google_gemini
+ RAKU_CAPTION_PROVIDER=google_gemini
+ RAKU_VLM_MODEL_ID=gemini-1.5-pro-002
+ GCP_PROJECT_ID=raku-prod
+ GCP_LOCATION=asia-northeast1
+ GCP_WORKLOAD_IDENTITY_PROVIDER=projects/123/locations/global/workloadIdentityPools/aws/providers/fargate
+ GCP_WORKLOAD_IDENTITY_SA_EMAIL=raku-ocr@raku-prod.iam.gserviceaccount.com   # impersonation target (or direct resource access)
+ GCP_DOCAI_GCS_BUCKET=raku-prod-docai-stage-an1                              # GCS bridge (zero-retention lifecycle)
```

**Before/after per-tenant `ProviderPolicy` row** (the per-tenant override; without it the default deterministic policy admits only `aws_textract`/`bedrock`):

```diff
  { "provider_policy_id": "tenant-acme",
-   "parser_mode": "aws_only",
-   "allowed_ocr_providers":        ["aws_textract", "customer_managed"],
-   "allowed_layout_providers":     ["aws_textract", "customer_managed"],
-   "allowed_structured_providers": ["aws_textract", "customer_managed"],
-   "allowed_vlm_providers":        ["bedrock", "customer_managed"],
-   "allowed_caption_providers":    ["bedrock", "customer_managed"],
-   "cross_cloud_processing_allowed": false,
-   "allowed_regions": ["ap-northeast-1"],
-   "opt_in_status_by_family": { "aws": "granted" },
+   "parser_mode": "aws_google",
+   "allowed_ocr_providers":        ["google_document_ai", "deterministic", "customer_managed"],
+   "allowed_layout_providers":     ["google_document_ai", "deterministic", "customer_managed"],
+   "allowed_structured_providers": ["google_document_ai", "deterministic", "customer_managed"],
+   "allowed_vlm_providers":        ["google_gemini", "deterministic", "customer_managed"],
+   "allowed_caption_providers":    ["google_gemini", "deterministic", "customer_managed"],
+   "cross_cloud_processing_allowed": true,
+   "allowed_regions": ["asia-northeast1", "ap-northeast-1"],
+   "data_residency_requirement": "single_jurisdiction",
+   "home_jurisdiction": "JP",
+   "opt_in_status_by_family": { "aws": "granted", "google": "granted" },
+   "provider_capability_overrides": { "google_document_ai": { "zero_retention": true, "no_train": true, "attestation_ref": "att-2026-06-..." } },
    "zero_retention_required": true,
+   "fallback_policy": { "ocr": "deterministic", "vlm": "deterministic" } }
```

Note the fallback targets (`deterministic`) are in the allowlists — load-time validation (§2.6) rejects the row otherwise, so a later Google deprovision **degrades** (re-submit in-flight `PENDING` jobs to the deterministic analyzer) rather than DLQ-storms; `RAKU_FORCE_DETERMINISTIC=1` is the global instant kill switch. The safety verdict is unchanged because primary evidence is still sourced from `PROMOTABLE_EXTRACTION_SOURCES` (now `google_docai` instead of `aws_textract`), never the caption slot — `test_provider_swap_invariance` enforces it. **Caveat (whole-stack one-vendor):** per the canonical A4 rule (§0.5-A4), the verifier quorum needs ≥2 distinct model ids **from distinct provider families** by default; an all-Gemini (or all-Bedrock) tenant cannot form two families, so high-risk visual evidence demotes to `insufficient_evidence` (block surfaced, not silent) unless `visual_verifier_allow_same_family_distinct_models=true` (default `false`, attestation-gated; documents residual correlated-failure risk).

---

## Portability Patch-List (rationale + LATER-vendor task index)

> **These amendments have been FOLDED into the body — the body is now the single source of truth.** The flag (`visual_evidence_promotion`), migration (metadata-jsonb + async columns, no persisted verdict), PDF-always-async, provenance vocabulary (`ExtractionSource`/`CaptionSource` + `PROMOTABLE_EXTRACTION_SOURCES`), crop-`crop_url` exposure, and verifier-independence reconciliations now live directly in §0.5/§2/§3/§4/§5/§6/§7. This list is retained only as (a) the rationale/audit trail for those edits and (b) the index of LATER vendor tasks (Google/Azure/OSS adapters) that remain gated behind §2.8.4 conformance. **Precedence (single rule, no contradiction):** the §0.5 NORMATIVE resolutions are authoritative; the body §§1–7 have been reconciled to agree with them, and this patch-list is non-normative rationale. If the body ever appears to disagree with a §0.5 resolution, that is a reconciliation bug to fix in the body — §0.5 states the intended rule. (This list previously said "the body wins"; that applied only to the portability amendments already folded in, and is subsumed by: §0.5 is the rule, the body implements it.)

Each item is `section ref → exact change`.

**§0.5-A3 (`spec.md:49`) — extraction_source allowlist, not a literal.** Replace `extraction_source == "vlm"` reference-only / `extraction_source == "textract"` promotable with: *"primary evidence is promotable iff `primary_evidence_source ∈ PROMOTABLE_EXTRACTION_SOURCES = {deterministic_ocr, aws_textract, google_docai, azure_docintel, oss_tesseract, spreadsheet_parser}` AND the producing capability has `extraction_method == 'transcription'`. NEVER use `!= "vlm"` (fails open). Empty/unknown ⇒ NOT promotable."* Canonical spelling is `aws_textract` (reconcile with §4.3:747); add `spreadsheet_parser`; the `"textract"` literal is retired.

**§0.5-A1 — VISUAL_DERIVED_KINDS unchanged in intent**, but the `_admissible` predicate now reads `is_promotable_evidence(c.metadata)` (membership) rather than `c.kind`-string logic; the gate is provenance-driven, vendor-neutral.

**§0.5-A4 — verifier independence. ✅ FOLDED into §0.5-A4 (and restated identically in §2.8.5/§5.5/F2/G1).** The canonical rule: distinct model ids from distinct `provider_family` required by default in production; a whole-stack one-vendor tenant uses `visual_verifier_allow_same_family_distinct_models` (default `False`, attestation-gated) for two distinct same-family model-ids, else high-risk visual demotes to `insufficient_evidence` and surfaces the block — documented, not silent.

**§0.5-A8 — one promotion flag.** Honored: a single `Settings.visual_evidence_promotion` (`RAKU_VISUAL_EVIDENCE_PROMOTION`), declared once in §6.1; the old `visual_primary_evidence_enabled` / `RAKU_VISUAL_PRIMARY_EVIDENCE_ENABLED` name is deleted everywhere.

**§0.5-B2 — async seam is multi-vendor.** `AsyncDocumentAnalyzer.submit/poll` returns a vendor-neutral `DocumentAnalysis` (was Textract-specific `TextractAnalysis`); `JobHandle.token` is vendor-opaque; the `Continuation` cursor is structured (Textract `NextToken` | DocAI shard list | Azure operation-location), and `AsyncJobStatus` separates `MORE_AVAILABLE` (pagination) from `PARTIAL_FAILURE` (Textract `PARTIAL_SUCCESS`).

**§0.5-B5 — generalize async columns.** Rename `IngestionRun.textract_job_id`/`textract_job_status` → `async_provider`/`async_job_id`/`async_job_status` (the exact three §0.5-B5 columns; `extractor_version` is the separate §0.5-B4 column); `0014` is additive. `async_job_id` stores `JobHandle.to_token()` verbatim for any vendor.

**§0.5-C1 — redrive includes vendor-deprovision.** The queue `defer`/poll lifecycle adds: a poll returning auth/not-found (403/404) after a provider is deprovisioned re-submits the in-flight `PENDING` job to the policy fallback analyzer (deterministic), not DLQ.

**§0.5-C2 (`:71-72`) — staging is family-resolved.** PDFs are S3-round-tripped for Textract **and** GCS-staged for Document AI via the `VendorStagingResolver`; `document_ref` is family-resolved; a `gs://` ref is produced only by the `GcsConnector`, never mis-parsed by `S3Connector._parse_ref`.

**§0.5-C8 — region fix lands NOW, broadened.** `DEFAULT_PROVIDER_CAPABILITIES` `aws_textract`/`bedrock` `region` `us-east-1` (`provider_policy.py:238`,`:245`) → `ap-northeast-1`; **also** `Settings.aws_region` default (`config.py:35`) `us-east-1` → `ap-northeast-1`; inject `AWS_DEFAULT_REGION` on the worker task (CDK currently sets it only on the answer/Bedrock path, `raku-rag-stack.ts:84`,`:105`); add a guard that a capability region must be explicitly resolved before any region/residency check. Add `google_document_ai`/`vertex_gemini`/`vertex_embeddings` rows at `asia-northeast1` and Azure at `japaneast`, all defaulting `zero_retention=False, no_train=False` (attestation-gated to `True`).

**§0.5-C15 — cost cardinality + cross-cloud bytes.** Keep one `cost_records` row per async **job** (page_count, `async_provider`) at `SUCCEEDED`; **add** a `kind='cross_cloud_egress'` row per document when a cross-cloud span occurs, carrying transferred bytes + NAT-GB + GCS-storage estimate, surfaced on the KPI scorecard.

**§3.2 / §3.5 (`:581`,`:616`) — adapter naming + executor neutrality.** Rename `Textract*`/`Bedrock*` per-vendor classes to capability+vendor naming behind the neutral protocols; `VisualIngestionExecutor` constructor takes `ocr/layout/structured/vlm/captioner/visual_embedder/crops` defaulting to the `*_from_settings` factories, so it never names a vendor. Per-page normalization (`_parse_textract_blocks` for AWS, `_parse_google_document` for Google) happens **inside** the adapter, before the executor sees a region.

**§3.6 (`:642`) — redaction is path-invariant.** State that `Redactor.redact_visual_text()` runs inside the async `_index_analysis` path (over `DocumentAnalysis.ocr_regions` and structured cells) before `visual_chunks_from_ingestion` — closing the gap that `services/visual.py:58-78` only copies redaction flags and never redacts, so multi-page PDFs (Textract async **and** Document AI LRO) no longer persist un-redacted OCR.

**§4.2/§4.3 (`:704`,`:747`) — neutral structured types + provenance.** `StructuredTable.extraction_source` is an `ExtractionSource` value (`aws_textract|google_docai|azure_docintel|spreadsheet_parser`), `ChartSeries`/chart-derived carries a `CaptionSource` (never promotable); generalize `_parse_textract_blocks`-only references to "the per-vendor `StructuredNormalizer`"; `BoundingBox` gains `quad`/`page_rotation_deg`; every cell `bbox` 0..1.

**§4.5/§4.10 (`:834`,`:955`) — citation anchors are provenance-tagged.** `Citation`/`VisualCitation` carry `extraction_source` (transcription) and `caption_source` separately; cell/form/chart anchors record which one backs them so promotion membership-tests the transcription tag only.

**§5.2(b)/§5.4 (`:998`,`:1065`) — grounding gate is membership-based.** `strong_grounding` admits a region iff `is_promotable_evidence(c.metadata)` (membership in `PROMOTABLE_EXTRACTION_SOURCES`, `extraction_method=='transcription'`), not `extraction_source == "textract"`; empty/unknown `primary_evidence_source` fails closed; works for AWS today (which emits `aws_textract`, not `textract`) and any future vendor.

**§5.3 Hook 2 (`:1053-1058`) — `_admissible` neutral.** `c.visual_evidence_verified and is_promotable_evidence(c.metadata)` for visual-derived kinds, independent of vendor.

**§6.1 — Settings. ✅ FOLDED into the single canonical §6.1 `Settings` block** (`ocr/layout/structured/vlm/captioning/visual_embedding_provider` default `deterministic`, `vlm_model_id`/`caption_model_id`, `ocr_region`/`vlm_region`, the GCP WIF block, `force_deterministic`, `visual_verifier_allow_same_family_distinct_models`, the verifier-quorum fields, `max_inline_ocr_bytes`/`max_regions_verified_per_answer`; `aws_region` default `ap-northeast-1`). The §5.5 verifier-field block was deleted; there is no second `Settings` declaration.

**§6.3 (`:1225-1249`) — CDK: IAM→add GCP WIF (no secret).** Keep `grantTextractInvoke`/`grantBedrockInvoke` (`raku-rag-stack.ts:1205-1216`,`:695`,`:757`). Add `grantVertexInvoke(taskRole)` that grants **no AWS IAM** (the task-role identity *is* the credential) and injects only the non-secret WIF `external_account` config (pool/provider resource name, `audience`, `sts.{region}.amazonaws.com` verification URL). **Do NOT** add a `secretsmanager.Secret` for GCP (unlike the OpenAI key and Google OAuth client_secret). Replace `ecsSecurityGroup allowAllOutbound: true` (`:326`) with deny-by-default egress to the per-family endpoint set incl. `sts.{aws_region}.amazonaws.com` + `sts.googleapis.com`; prefer interface VPC endpoints for Textract/Bedrock to bypass the single NAT (`:139`). Provision the `asia-northeast1` GCS bridge bucket with a zero-retention lifecycle; export worker/answer task-role ARNs as outputs so the GCP pool condition can pin them.

**§6.5 (`:1258`) — cost model.** Add per-document cross-cloud egress/transfer + GCS storage lines; note Document AI batch LRO latency may blow `target_visual_p95_latency_ms` and is gated by the live-conformance SLO check.

**§6.6 (`:1270`) — testing.** Add the §2.8.4 battery (HARD `test_fr048_caption_not_in_ocr_slot` + deny-before-egress per `(capability,vendor)`), `test_no_vendor_leakage`, `test_provider_swap_invariance`, mandatory CJK goldens, generative-OCR guard, and the disjoint-enum invariant test.

**§7 Epics (`:1304-1355`) — add Google/Azure as later conformance-gated tasks.** Epic A: add `ExtractionSource`/`CaptionSource`/`PROMOTABLE_EXTRACTION_SOURCES`/`BoundingBox.quad`/`CredentialProvider`/`capability_type`+4 allowlists+region fix (all NOW, AWS-only). New **Epic A2 (LATER, conformance-gated):** `GoogleDocAi*`/`GoogleGemini*`/`VertexEmbedding*` normalizers + `GcpWorkloadIdentityCredentials` + GCS bridge + WIF CDK, each blocked behind the §2.8.4 battery turning its matrix cell `✅`; Azure/OSS likewise. Epic E: generalize async columns + `Continuation` + `PARTIAL_FAILURE` + vendor-deprovision redrive. Epic G1 (`:1347`): verifier providers become a cross-family list with the single-family fallback.

---

## Revised Decision Record note

> **§0.2 decision #1 (`spec.md:25`) — REVISED.** Providers are **AWS-native by DEFAULT, vendor-portable by design (per-capability and per-tenant).** OCR/layout/tables/forms = AWS Textract and figure/photo/diagram/chart VLM = Bedrock Claude vision remain the shipped, conformance-green implementation, and the deterministic offline providers remain the default so Tier-A is unchanged. But the *contract* is no longer AWS-specific: each of the six capabilities (`ocr`/`layout`/`structured`/`vlm`/`caption`/`embedding`) is selected independently, per-tenant, through the existing `ProviderPolicy`, and every vendor reaches the system only through one vendor-neutral capability protocol + a per-vendor `*Normalizer` that maps its native shape (Textract `Block`, Google Document AI `Document`, Azure `AnalyzeResult`, Bedrock/Gemini vision payloads) into a single neutral model whose geometry carries faithful polygons (`BoundingBox.quad`), whose provenance lives in two *actually-disjoint* value-spaces (`ExtractionSource` vs `CaptionSource`), and whose promotability is one centralized `PROMOTABLE_EXTRACTION_SOURCES` membership test — so the FR-048 OCR-vs-VLM safety firewall, redaction-before-persist, and the `region/zero-retention/no-train/per-family-consent/residency` ProviderPolicy gates survive normalization identically for every vendor. **Google Vertex AI (Document AI + Gemini + Vertex embeddings), Azure, and OSS are not rewrites — they are conformance-test-validated adapters behind these same neutral seams**, with GCP credentials obtained by Workload Identity Federation from the Fargate task role (no long-lived service-account keys). Adopting one is a conformant adapter + a config flip (`RAKU_*_PROVIDER` + a per-tenant `allowed_*_providers` row), with zero changes to retrieval, answer, or safety code; whole-stack vendor switch is just the special case where all capabilities point at one vendor.

Relevant files (all absolute): `/workspace/raku-rag/specs/021-visual-pdf-understanding-prod/spec.md` (merge target), `/workspace/raku-rag/workers/ingest/provider_policy.py`, `/workspace/raku-rag/workers/ingest/providers/parsers/__init__.py`, `/workspace/raku-rag/src/raku_rag/domain/models.py`, `/workspace/raku-rag/src/raku_rag/interfaces/base.py`, `/workspace/raku-rag/src/raku_rag/services/visual.py`, `/workspace/raku-rag/src/raku_rag/core/config.py`, `/workspace/raku-rag/src/raku_rag/providers/llms.py`, `/workspace/raku-rag/infra/cdk/lib/raku-rag-stack.ts`.

---

## 3. Ingestion Pipeline & PDF-Embedded-Image Handling

This section specifies how `image/*` and `application/pdf` uploads are ingested into first-class, citable `Modality.VISUAL` evidence. It extends the existing visual ingestion boundary (`VisualIngestionExecutor`, `src/raku_rag/workers/ingestion.py:499-651`) rather than introducing a parallel pipeline, and replaces the three placeholders that block production: the deterministic-only OCR/caption stack, the `memory://` crop URIs (`src/raku_rag/services/crop.py:73,79-82`), and the text-only ingest dispatch (`src/raku_rag/production.py:89,166-227`).

The hard rule from §1/§2 holds end-to-end: **PII/secret redaction (`Redactor.redact_visual_text`, `src/raku_rag/observability/redaction.py:74-76`) and EXIF strip (`Redactor.redact_exif`, `redaction.py:78-96`) run on the REAL Textract/VLM output BEFORE any asset, region, crop, chunk, or vector is persisted** — exactly where the deterministic path already redacts (`ingestion.py:540`, `570-573`, `614-617`).

### 3.1 Upload endpoint

Two surfaces, both content-type driven. No new contract fields are required on the JSON path; the binary path adds one multipart handler.

**NestJS gateway — `IngestController` (`apps/api/src/ingest/ingest.controller.ts:6-38`).**
- Existing `@Post()` (line 8) forwards a JSON `IngestRequest` whose `ref` (line 21) is an object-store key or `data:` URI, and `content_type` (line 22, today defaulting to `"text/plain"`). This already carries `image/*` / `application/pdf` if the caller sets `content_type` and supplies a `data:application/pdf;base64,…` or `s3://…` ref. The `manufacturing` block (line 25) is forwarded unchanged so the safety overlay can resolve approval state (§ safety spec).
- **Add `@Post("upload")`** (multipart): stream the file part to the ingestion `DocumentBucket` (`infra/cdk/lib/raku-rag-stack.ts:166-174`), derive `content_type` from the part's MIME (do **not** default to `text/plain`), and POST to `/internal/ingest` with `document_ref="s3://{documents-bucket}/{tenant}/{collection}/{document_id}.{ext}"`. This S3 round-trip is **mandatory for PDFs** because Textract async (`StartDocumentAnalysis`) reads `DocumentLocation.S3Object`, not inline bytes — a `data:` URI cannot drive the async API.
- Boundary validation: enforce `Settings.max_document_bytes` (`src/raku_rag/core/config.py:18`, 25 MiB) and an allowlist `{image/png, image/jpeg, image/tiff, application/pdf}`; reject others with 415 before forwarding.

**answer-service route — `POST /internal/ingest` (`apps/answer-service/server.py:1916-1957`).** Shape is unchanged. It validates the four refs (line 1918), resolves bytes via `connector.fetch(document_ref)` (line 1922 — `S3Connector` for `s3://`, `DataUriConnector` for `data:`), extracts mfg metadata (line 1941), and calls `system.ingest_document(..., content_type=…)` (line 1944-1953). The fetch-failure branch (line 1929-1939) and the `202`/`200` projection (line 1954-1957) are reused as-is. **All PDF/image branching happens below this line, inside `ProductionSystem`** — the route does not change.

### 3.2 Content-type dispatch inside `ProductionSystem` / the worker

`ProductionSystem.ingest_document` (`production.py:166-227`) currently always routes to `self.ingestion.ingest` (the text path; `CompositeParser` at `production.py:89` has no PDF parser). Add a dispatch at the top of `ingest_document`:

```python
ct = (content_type or "text/plain").lower()
if ct == "application/pdf":
    # §0.5-C2: PDFs are ALWAYS async — enqueue to the SQS worker, return a queued run (202 + status_url).
    # Never inline: inline would skip Textract async-job state, retry/redrive, DLQ, and cost control.
    return self.enqueue_visual_document(..., raw=raw, document_ref=document_ref, kind="pdf")
if ct.startswith("image/") and len(raw) <= self.settings.max_inline_ocr_bytes:
    return self.ingest_visual_document(..., raw=raw, document_ref=document_ref, kind="image")  # small single image: inline OK
if ct.startswith("image/"):
    return self.enqueue_visual_document(..., raw=raw, document_ref=document_ref, kind="image")  # large image: async
# else: existing text path (self.ingestion.ingest, lines 199-209) unchanged
```

`enqueue_visual_document` and `ingest_visual_document` are new `ProductionSystem` methods. **`enqueue_visual_document` (PDFs + large images) only creates a queued run** (`PostgresIngestionRunStore.create_queued`) and publishes an `IngestionJobMessage`; the actual Textract async submit/poll + persistence happens in the worker, so the HTTP caller gets `202` + a `status_url` immediately (§0.5-C2). **`ingest_visual_document` (small single images, sync) drives the visual executor inline** via the same `PostgresIngestionRunStore` lifecycle already used at `production.py:194-226` (`create_queued → mark_running → mark_succeeded/mark_failed`), persisting `document_ref`/`content_type` + manufacturing metadata onto the `Document` exactly as lines 212-220 do. The async SQS worker is where the PDF/large-image path lives: `IngestionWorker.process_once` (`ingestion.py:782-831`) currently always calls `execute_document` (line 806, text); add a `content_type` branch there to drive the visual executor + the async Textract job lifecycle (§0.5-C1/B5). `IngestionJobMessage.content_type` (`ingestion.py:41`) already carries the discriminator — **no queue-message schema change**.

### 3.3 PDF path A — Textract async (text + layout + tables + forms, all pages)

For `application/pdf`, the structured text layer is produced by **Textract async `StartDocumentAnalysis`** over the S3 object, with `FeatureTypes=["TABLES","FORMS","QUERIES"]` and `LAYOUT` (per §1). Flow:

1. `StartDocumentAnalysis(DocumentLocation={"S3Object":{Bucket,Name}}, FeatureTypes=…)` → `JobId`. SNS completion notification (or bounded poll) → `GetDocumentAnalysis(JobId, NextToken=…)` paginated until `JobStatus=SUCCEEDED`.
2. Group returned `Block`s by `Page`. Map block types to `LayoutRegion.region_type` (`src/raku_rag/domain/models.py:178-193`): `LINE/LAYOUT_TEXT → "text"`, `TABLE`+`CELL → "table_row"`, `KEY_VALUE_SET → "form_field"`, `QUERY_RESULT → "query"`.
3. **Geometry maps directly with no transform**: Textract `Geometry.BoundingBox` (`Left, Top, Width, Height`) is already normalized to `0..1`, which is exactly the contract of our `BoundingBox` (`models.py:145-152`: "x/y/width/height in the 0..1 page coordinate space"). Set `OcrTextRegion.bbox`/`LayoutRegion.bbox` from it verbatim and carry `page_number` from `Block.Page` (`OcrTextRegion.page_number` at `models.py:160`, `LayoutRegion.page_number` at `models.py:186`).

This uses the explicit async seam from §0.5-B2, not the synchronous image OCR protocol. PDFs and
large multi-page documents are staged to S3, submitted with
`AsyncDocumentAnalyzer.submit(AsyncSubmitRequest(document_ref="s3://...")) -> JobHandle`, and polled
with `poll(JobHandle) -> DocumentAnalysis | PENDING` until a terminal state. The neutral
`DocumentAnalysis` output is then normalized into the same page/region assembly path as image OCR.
Single-image OCR remains behind `OcrEngine` via
`TextractOcrLayoutEngine.extract(image, *, ctx: IngestContext) -> tuple[OcrTextRegion, ...]`.
`ocr_from_settings` selects the AWS Textract adapters only when `runtime_profile=production` and
`RAKU_OCR_PROVIDER=aws_textract`, then injects them into `VisualIngestionExecutor.__init__`
(`ingestion.py:507-522`, changing the `ocr`/`layout`/`captioning` type hints from the
`Deterministic*` concretes to the `OcrEngine`/`LayoutExtractor`/`CaptioningProvider` protocols).
`ProviderPolicy.allowed_ocr_providers` gates the provider per tenant and enforces
`region=ap-northeast-1, zero_retention=true, no_train=true` **before** either the sync image OCR
invoker or async document analyzer is called (`workers/ingest/provider_policy.py`), identical to the
parser router.

### 3.4 PDF path B — page rasterization + embedded-image extraction (non-text regions)

Textract returns **nothing** for figures, photos, diagrams, and charts that have no text layer. Those are recovered by a second, parallel pass over the same PDF and are the regions fed to the Bedrock VLM.

**Library choice: `pypdfium2` (Apache-2.0) for rasterization + `pikepdf` (MPL-2.0) for embedded-image extraction; `PyMuPDF` (`fitz`) is an opt-in higher-fidelity alternative gated behind a commercial license.** Justification:
- **Capability.** We need two things PDFium alone does not cleanly expose: (a) full-page raster at a fixed DPI for crop rendering, and (b) per-embedded-image *bounding boxes on the page* plus the decoded image bytes. `pypdfium2` (Chromium's PDFium) gives high-fidelity, fast rasterization (`PdfPage.render(scale=…)` → bitmap). `pikepdf` (libqpdf) walks `/Resources/XObject` subtype `/Image` streams to extract the embedded image bytes and the `/CTM` placement to compute each image's page bbox. PyMuPDF does both in one call (`page.get_image_info(xrefs=True)` → bbox per image, `Document.extract_image(xref)` → bytes; `page.get_pixmap(dpi=…)` → raster), which is why it is offered as an opt-in.
- **License.** PyMuPDF is **AGPL-3.0**; its §13 network-use clause is a genuine hazard for a closed-source SaaS that serves users over a network. `pypdfium2`/`pikepdf` are permissive (Apache-2.0 / MPL-2.0) and impose no copyleft obligation. The default ships license-clean; PyMuPDF is selectable only where a commercial PyMuPDF license is held.

For each page: render at a fixed DPI (e.g. 200) → `page_image: bytes` (PNG, kept in memory for crop rendering, §3.7), and enumerate embedded images → list of `(image_bytes, page_bbox_normalized: BoundingBox, page_number)`. Each embedded image (and each rasterized non-text region detected by layout) becomes a `LayoutRegion` with `region_type ∈ {"figure","photo","diagram","chart"}`, `ocr_text=""`, and its image bytes routed to the VLM for `generated_caption_text` (§3.5).

### 3.5 `execute_pdf` — producing `LayoutRegion`s per page

Add `VisualIngestionExecutor.execute_pdf` as the multi-page analog of `execute_image` (`ingestion.py:524-651`):

```python
def execute_pdf(
    self, *, tenant_id: str, collection_id: str, source_id: str, document_id: str,
    pdf: bytes, document_ref: str = "",            # s3:// key Textract reads from
    options: VisualIngestionOptions | None = None,  # ingestion.py:483-486
    job_id: str = "", trace_id: str = "",
) -> tuple[VisualIngestionResult, ...]:             # one result per page
```

Per page it assembles a `VisualIngestionResult` (`ingestion.py:489-496`) carrying one page-scoped `VisualAsset` (`models.py:163-175`, with `page_number` set, `asset_id=f"asset_p{page}_{checksum[:8]}"` to keep pages distinct per the grounding note) plus that page's `regions`, `visual_vectors`, and `caption_status`. The per-page assembly reuses `execute_image`'s exact stage order (`ingestion.py:538-650`):

1. EXIF strip on any page/image metadata → `redact_exif` (`ingestion.py:540`).
2. `VisualAsset` creation — `storage_uri` becomes the real `s3://…` page-raster key (not `memory://…` as at `ingestion.py:546`).
3. **OCR/structured**: Textract regions from §3.3 (replacing `self.ocr.extract`, `ingestion.py:566`).
4. **Redact OCR text BEFORE storage**: `replace(region, text=self.redactor.redact_visual_text(region.text))` for every region (mirrors `ingestion.py:570-573`), capturing sensitive labels (`ingestion.py:567-569`) for redaction metadata.
5. **Layout regions** merge Textract regions (§3.3) and non-text figure/photo regions (§3.4).
6. **VLM captioning of non-text regions**: for `region_type ∈ {figure,photo,diagram,chart}`, send the region crop to the Bedrock VLM (`VLMProvider` protocol, `interfaces/base.py:109-110`; selected by new `vlm_from_settings`, replacing the hardcoded `ExtractiveVLMProvider()` at `production.py:99`) → `generated_caption_text`, **redacted before assignment** exactly as `ingestion.py:613-617` and `CaptioningResult` redaction at `providers/captioning/__init__.py:48-52`.
7. Redaction metadata stamped on each region (`_visual_region_redaction_metadata`, `ingestion.py:618-628`).
8. Visual embeddings: `HashingVisualEmbeddingProvider` for v1 (Titan Multimodal opt-in per §1), input `f"{ocr_text}\n{generated_caption_text}"` (`ingestion.py:630-634`).

`ingest_visual_document` then iterates the per-page results, calls `visual_chunks_from_ingestion(result)` (`src/raku_rag/services/visual.py:17-55`) per page, and upserts all chunks+vectors via `self.store.upsert(...)` (same as `app.py:185-186`). For single `image/*` uploads, `execute_image` is used unchanged (`page_number=1`).

### 3.6 EXIF strip + redaction occur BEFORE storage (invariant)

The ordering is load-bearing and already correct in the deterministic path; the production path must preserve it: `redact_exif` runs before `VisualAsset` is built (`ingestion.py:540-541`); `redact_visual_text` runs on every OCR region before layout/embedding/asset persistence (`ingestion.py:570-573`); caption redaction runs before the caption is attached (`ingestion.py:614-617`). No raw Textract/VLM byte or string is written to S3, the vector store, the document registry, or the audit log prior to redaction. **This invariant is path-invariant:** on the async multi-page path the same `Redactor.redact_visual_text()` runs inside `_index_analysis` over every `OcrTextRegion.text` and structured cell **before** `visual_chunks_from_ingestion` (§2.8.2), so sync executor and async worker redact identically. Audit entries record reference IDs only — `crop_uri`, `ocr_text`, and `generated_caption_text` never enter the audit sink (consistent with the audit redaction contract in the safety spec).

### 3.7 REAL crop rendering to S3 (replacing `memory://`)

`CropService.create_region_crop` (`src/raku_rag/services/crop.py:47-95`) currently mints `memory://crops/{tenant}/{crop_id}` (line 73) and `memory://redacted-crops/…` (lines 79-82, `_redacted_crop_uri` line 114-115) and stores into `InMemoryCropStore` (`crop.py:13-40`). Two changes:

1. **Extend the signature** to receive the page raster so a real crop can be rendered:
   ```python
   def create_region_crop(self, region, *, page_image: bytes | None = None,
                          page_pixel_size: tuple[int, int] | None = None,
                          redaction_policy_ref: str = "inherit") -> CropArtifact
   ```
   When `page_image` is provided, denormalize `region.bbox` (`0..1`, `models.py:145-152`) to pixel coordinates via `page_pixel_size`, crop with Pillow/pypdfium2, encode PNG, and upload. The redacted variant (`crop.py:80-82`) becomes a **real** rendering with the sensitive sub-bbox masked/blurred before upload.

2. **Add `S3CropStore`** implementing the same duck-typed interface as `InMemoryCropStore` (`put/get/list_document/tombstone_document`, `crop.py:17-40`) so it drops into `CropService(store=…)` and into the deletion cascade (`DeletionService._tombstone_crops`, `src/raku_rag/services/deletion.py:133-136`) and `AssetService` (`production.py:160`) with no caller changes:
   ```python
   class S3CropStore:
       def __init__(self, *, bucket: str, region: str, kms_key_id: str = "", client=None): ...
       def put(self, crop: CropArtifact) -> CropArtifact: ...   # PUTs PNG, sets crop_uri=s3://…
       def get(self, tenant_id, crop_id) -> CropArtifact | None: ...
       def tombstone_document(self, tenant_id, document_id) -> int: ...  # delete/mark; cascade hook
   ```
   URI scheme: `s3://{crop-bucket}/{tenant_id}/{collection_id}/{document_id}/{crop_id}.png` (raw) and `…/redacted-crops/{tenant_id}/{crop_id}.png`. The resulting `CropArtifact.crop_uri` (`models.py:217`) and the region's `crop_uri` (`models.py:191`) become `s3://…`, replacing every `memory://` literal. `CropService` is wired at `production.py:108` (`self.crops = CropService()`) → `CropService(store=S3CropStore(...))` under `runtime_profile=production`, `InMemoryCropStore` under deterministic so Tier-A stays fast.

`GET /internal/assets/{asset_id}` (`server.py:1584-1591` → `AssetService.get_visual_asset`) **MUST NOT return the raw `s3://` URI / bucket / key** (§0.5-C4). After `can_read_document` (`assets.py:25`) passes, `AssetService` mints a **short-TTL presigned GET** and returns it in a separate response field **`crop_url`** (the internal `crop_uri` is never serialized to the client); when `visual_region_redaction_required`, the presigned URL points at the **redacted** crop object. A presigned URL is a bearer capability, so it is minted **per request behind the same RLS/ACL as the JSON path** — never precomputed or cached across principals. The `VisualAssetResponse`/`assets.ts` DTO therefore exposes `crop_url` (presigned/proxy), not `crop_uri`.

### 3.8 Chunking → `Modality.VISUAL`, per-region provenance

`visual_chunks_from_ingestion` (`visual.py:17-55`) maps each `LayoutRegion` to a `Chunk` with `modality=Modality.VISUAL` (`visual.py:32`) and metadata already carrying the full provenance set (`visual.py:36-52`): `asset_id`, `region_id`, `page_number` (line 39, sourced from `LayoutRegion.page_number`), `bbox` as `{x,y,width,height}` (lines 40-45), `crop_uri` (line 46, now `s3://`), `region_type` (line 47), `ocr_text` (line 48), `generated_caption_text` (line 49), `primary_evidence_text = region.ocr_text` (line 50 — caption is retrieval aid only, never primary evidence, per `interfaces/base.py:100`), plus the inherited redaction fields (`_visual_redaction_metadata`, `visual.py:58-78`). The chunk text is `ocr_text + "\n" + caption` (`visual_chunk_text`, `visual.py:9-14`) for hybrid recall.

**Required fix for multi-page PDFs (bug):** `chunk_id` is built as `f"{document_id}:visual:{idx}"` (`visual.py:25`) where `idx` restarts at 0 for each per-page `VisualIngestionResult`. Across pages this **collides**. Change to incorporate page/asset, e.g. `f"{region.document_id}:visual:{region.page_number}:{idx}"` (or key on `region.region_id`), keeping `page_number` (already in metadata at `visual.py:39`) the disambiguator. New structured `region_type`s (`table_row`, `form_field`, `figure`, `chart`, etc.) flow through unchanged because the mapping is type-agnostic; structured-citation `chunk_id` namespacing is specified in the data-model section.

Provenance for "show in original": each region/crop additionally carries `source_page_number` (already set in `CropArtifact.metadata`, `crop.py:78`) and SHOULD carry `source_extraction_type ∈ {"textract_block","rendered_region","embedded_image"}` and, for embedded images, the PDF XObject ref recovered by `pikepdf`/PyMuPDF — nested in `LayoutRegion.metadata` to avoid schema churn.

### 3.9 Deletion / ACL inheritance (unchanged seams, must hold for PDF)

Visual chunks, assets, and crops inherit the source document's ACL and tombstone. `DeletionService` already cascades visual artifacts and crops (`deletion.py:_tombstone_crops` 133-136, `_visual_refs`), and `S3CropStore.tombstone_document` is the production hook for that cascade. Multi-page PDFs produce multiple `asset_id`s under one `document_id`; the cascade keys on `document_id`, so per-page assets and their S3 crops are tombstoned together — no per-page deletion logic is needed.

---

**Net new symbols to implement:** `ProductionSystem.ingest_visual_document`; content-type dispatch in `ingest_document` (`production.py:166`) and `IngestionWorker.process_once` (`ingestion.py:806`); `VisualIngestionExecutor.execute_pdf` (`ingestion.py` alongside `execute_image:524`); `TextractOcrLayoutEngine` + `ocr_from_settings`; `BedrockVisionVLMProvider` + `vlm_from_settings` (replacing `production.py:99`); `captioning_from_settings`; `S3CropStore` + extended `CropService.create_region_crop` (`crop.py:47`); a `pypdfium2`/`pikepdf` PDF page+image extractor; `IngestController.@Post("upload")` (`ingest.controller.ts`); `Settings.ocr_provider/vlm_provider/captioning_provider` + env parsing (`config.py:10-65`, `settings_from_env:79-172`); and the `chunk_id` page-disambiguation fix (`visual.py:25`).

---

## 4. Structured Extraction & Data-Model Extensions

This section defines the domain types, metadata envelopes, DTO/OpenAPI surface, migration shape, and citation anchors required to turn Textract/VLM structured output (table rows, form key-values, chart numeric series, figure captions) into **individually retrievable and citable** units that inherit the existing visual redaction contract. It is grounded in the current model and service code; implement directly against the anchors below.

### 4.1 Design principle: nest in `metadata`, do not explode the dataclass/SQL schema

The current visual pipeline already carries arbitrary per-region data through `dict` metadata fields, not bespoke columns:

- `Chunk.metadata: dict` — `src/raku_rag/domain/models.py:89`
- `LayoutRegion.metadata: dict` — `src/raku_rag/domain/models.py:192`
- `VisualAsset.metadata: dict` — `src/raku_rag/domain/models.py:174`
- `CropArtifact.metadata: dict` — `src/raku_rag/domain/models.py:219`
- Postgres mirror: `chunks.metadata jsonb` + `chunks.metadata_schema_version integer` — `infra/db/migrations/postgres/0001_core_rls.sql:119-120`; same pair on `layout_regions` (`0002_policy_profile_visual_rls.sql:41-42`), `visual_assets` (`:20-21`), `crops` (`:59`).

**Rule:** structured extraction adds *one* nested JSON envelope key (`structured_content`) plus a small set of flat scalar keys on the existing `metadata` dicts. It does **not** add new top-level dataclass fields to `Chunk`/`LayoutRegion`/`VisualAsset` (which would force a wide ALTER and break the in-memory stores). New dataclasses below are **serialization shapes** stored *inside* `metadata["structured_content"]` and re-hydrated at retrieval time — mirroring how `extract_structured_table_manifests()` already stores plain `dict` manifests under `Document.metadata[STRUCTURED_TABLE_MANIFESTS_KEY]` (`src/raku_rag/services/structured_tables.py:90-140`, key at `:29`).

### 4.2 `region_type` vocabulary extension (LayoutRegion)

`LayoutRegion.region_type` is a free `str` defaulting to `"text"` (`src/raku_rag/domain/models.py:187`). Extend the **accepted vocabulary** (no schema change) to a closed set, and add a module constant so the gate can validate it:

```python
# src/raku_rag/domain/models.py (new constant near LayoutRegion)
REGION_TYPES = (
    "text", "figure", "photo", "diagram", "chart",   # existing/visual
    "table", "table_row", "form", "form_field",      # structured (Textract TABLES/FORMS)
    "chart_series", "figure_caption",                # structured (VLM / caption)
)
```

A `region_type="table"` region is the **container** (whole detected table bbox); each extracted row is materialized as a derived `region_type="table_row"` region (or as a row entry inside the container's `structured_content`, see §4.3). Same container/leaf split for `form`→`form_field` and `chart`→`chart_series`.

### 4.3 The `structured_content` envelope (lives on `LayoutRegion.metadata`)

New serialization dataclasses, defined in `src/raku_rag/domain/models.py` (alongside `OcrTextRegion` at `:155` and `VisualCitation` at `:196`). Each is `@dataclass(frozen=True)` and `asdict()`-serializable into the JSON envelope.

```python
@dataclass(frozen=True)
class StructuredTableColumn:
    name: str                 # header label or "column_{i}" (mirror structured_tables.py:104-107)
    index: int                # 1-based column index

@dataclass(frozen=True)
class StructuredTableCell:
    column_name: str
    column_index: int
    value: str                # post-redaction text (see §4.8)
    cell_anchor: str          # canonical "sheet!R{row}C{col}" token, parsers.py:36
    bbox: BoundingBox | None = None   # Textract cell geometry (None for spreadsheet origin)
    confidence: float = 1.0

@dataclass(frozen=True)
class StructuredTableRow:
    row_id: str               # str(row_number)
    row_number: int           # 2-based (header is row 1), mirror structured_tables.py:109
    cells: tuple[StructuredTableCell, ...]

@dataclass(frozen=True)
class StructuredTable:
    table_id: str             # Textract table block id, or sheet_name for spreadsheet origin
    extraction_source: str    # ExtractionSource value ONLY (transcription space); chart/VLM-inferred values carry caption_source instead — never mix the two (§2.1)
    page_number: int = 1
    header_row: int = 1
    columns: tuple[StructuredTableColumn, ...] = ()
    rows: tuple[StructuredTableRow, ...] = ()

@dataclass(frozen=True)
class FormField:                                   # Textract FORMS (key-value)
    form_id: str
    field_name: str           # KEY block text, normalized
    field_label: str          # display label (raw KEY text)
    field_value: str          # VALUE block text (post-redaction)
    extraction_source: str    # ExtractionSource value ONLY (transcription) — required for §5 membership gate
    field_type: str = "text"  # text|number|date|checkbox|selection
    required: bool = False
    page_number: int = 1
    key_bbox: BoundingBox | None = None
    value_bbox: BoundingBox | None = None
    confidence: float = 1.0

@dataclass(frozen=True)
class ChartPoint:
    label: str                # x-axis label / category
    value: float              # numeric y
    raw_text: str = ""        # VLM-inferred source token (NOT promotable; chart→numeric is inference, §0.5-A3)

@dataclass(frozen=True)
class ChartSeries:                                 # VLM or dedicated chart parser — NEVER promotable
    chart_id: str
    series_name: str
    series_type: str          # line|bar|scatter|pie
    caption_source: str       # CaptionSource value ONLY (∉ PROMOTABLE_EXTRACTION_SOURCES) — reference-only
    axis_x_label: str = ""
    axis_y_label: str = ""
    unit: str = ""
    page_number: int = 1
    points: tuple[ChartPoint, ...] = ()

@dataclass(frozen=True)
class FigureCaption:                               # PRINTED caption physically on the page, read by OCR
    caption_id: str
    text: str                 # transcribed caption text (post-redaction)
    extraction_source: str    # ExtractionSource value ONLY — a VLM-GENERATED caption is NOT a FigureCaption
    referenced_region_ids: tuple[str, ...] = ()    # figures this caption describes
    confidence: float = 1.0
```

These are stored under one envelope on the container region:

```python
LayoutRegion.metadata["structured_content"] = {
    "version": "structured-content-v1",
    "tables":   [asdict(t) for t in tables],
    "forms":    [asdict(f) for f in form_fields],
    "charts":   [asdict(c) for c in chart_series],
    "captions": [asdict(c) for c in figure_captions],
}
```

This is the visual analog of `Document.metadata[STRUCTURED_TABLE_MANIFESTS_KEY]` (the spreadsheet path, `structured_tables.py:263`); the two converge on the same row/cell shape so `TableManifestStructuredTool` (`structured_tables.py:183-284`) can consume Textract-origin tables unchanged by reading `manifest["rows"][n]["cells"]`.

### 4.4 Per-leaf `Chunk.metadata` (the searchable/citable units)

Each table row / form field / chart point / caption becomes its own `Chunk` (`modality=VISUAL`, `Modality` enum at `src/raku_rag/domain/models.py:14`) so it is individually embeddable, ACL-filtered, and citable. Extend the chunk builder `visual_chunks_from_ingestion()` (`src/raku_rag/services/visual.py:17-55`) to emit, in addition to the region chunk, one chunk per leaf. Each leaf chunk's `metadata` carries the flat anchor keys plus the inherited redaction block:

```python
# table-row chunk metadata
{
  "structured_kind": "table_row",            # spreadsheet_cell | table_row | form_field | chart_series | figure_caption
  "structured_parent_id": table_id,
  "asset_id": region.asset_id,
  "region_id": region.region_id,             # the table_row leaf region (or container region_id)
  "page_number": region.page_number,
  "bbox": {...},                             # row bbox for visual display
  "crop_uri": region.crop_uri,
  "table_id": table_id,
  "row_id": row.row_id,
  "row_number": row.row_number,
  "column_values": {col: cell.value, ...},   # full row, for retrieval text
  "cell_anchors": {col: cell.cell_anchor},   # column -> "sheet!R{r}C{c}"
  "primary_evidence_text": "<row rendered as text>",
  **_visual_redaction_metadata(region),      # §4.8
}
```

Reuse the existing flat keys already understood downstream: `structured_kind`, `sheet_name`, `row_id`, `column_index`, `column_name`, `cell_range` are exactly the keys `cell_metadata_for_text()` already emits for spreadsheet cells (`src/raku_rag/services/structured_tables.py:166-181`) — generalize that function into `row_metadata_for_text`, `form_field_metadata_for_text`, `chart_series_metadata_for_text` returning the same flat shape so one citation builder handles all kinds.

The chunk's searchable `text` (the value passed to the embedder, analogous to `visual_chunk_text()` at `visual.py:9-14`) is: for `table_row` → `"col=val; col=val; …"`; for `form_field` → `"{field_label}: {field_value}"`; for `chart_series` → `"{series_name} ({axis_y_label}): label=value; …"`; for `figure_caption` → the caption text.

### 4.5 `Citation` extension (Python + TS + OpenAPI)

`Citation` (`src/raku_rag/domain/models.py:117-135`) already has `kind: str`, `chunk_id`, `asset_id`, `page_number`, `region_id`, `bbox`, `crop_uri`, `sheet_name`, `cell_range`, `row_id`. Extend the **`kind` vocabulary** and add a small number of optional fields (all default-valued, so frozen-dataclass construction stays backward compatible):

```python
# additions to Citation (domain/models.py:117); all default-valued (frozen-dataclass back-compat)
kind: str   # "text" | "visual" | "spreadsheet" | "table_row" | "form_field" | "chart_series" | "figure_caption"
pixel_derived: bool = False                        # True for every VISUAL_DERIVED_KIND below — the SINGLE safety-gate key (§5.3)
visual_evidence_verified: bool = False             # §5.3 promotion verdict (grounding + verifier quorum); text/structured leave at default
visual_verifier_verdicts: tuple[VerifierVerdict, ...] = ()  # audit: reference ids / bools / numbers only
table_id: str = ""
form_id: str = ""
field_name: str = ""
chart_id: str = ""
series_name: str = ""
point_index: int = -1
column_name: str = ""

# THE single source for "which citation kinds are pixel/OCR/VLM-derived" (crop-bearing), domain/models.py:
VISUAL_DERIVED_KINDS = {"visual", "table_row", "form_field", "chart_series", "figure_caption"}
# NOTE: "spreadsheet" is NOT here — an xlsx cell is a deterministic structured parse (extraction_source=
# spreadsheet_parser ∈ PROMOTABLE_EXTRACTION_SOURCES), not pixels; it has no crop to VLM-verify.
```

The structured-citation builder sets `pixel_derived = (kind in VISUAL_DERIVED_KINDS)` at construction; the §5.3 safety gate consumes `pixel_derived` + `is_promotable_evidence(metadata)`, **never** a bare `kind == "visual"` test (§0.5-A1).

TS DTO `Citation` (`packages/shared/src/dto/answer.ts:9-24`) — extend the union and add the optional fields (keep existing `sheet_name?`/`cell_range?`/`row_id?` and the manufacturing overlay fields `approval_status?`/`effective_date?`/`approval_source?` at `:21-23`, which **must** populate for structured citations too so the safety gate can demote unapproved evidence):

```ts
kind: "text" | "visual" | "spreadsheet" | "table_row" | "form_field" | "chart_series" | "figure_caption";
table_id?: string | null;
form_id?: string | null;
field_name?: string | null;
chart_id?: string | null;
series_name?: string | null;
point_index?: number | null;
column_name?: string | null;
```

OpenAPI (`specs/001-rag-platform/contracts/openapi.md`, `Citation` schema): add the four new `kind` enum members and document the discriminated fields. All structured kinds inherit the existing visual citation fields (`asset_id`, `page_number`, `bbox`, `document_id`, `source_id`, `version`, `retrieval_score`) plus the redaction flags (§4.8). **The `Citation` schema NEVER carries a raw `crop_uri` (§0.5-C4, path-invariant):** today's answer serializers (`apps/answer-service/server.py:703-717` base, `:746-759` mfg) emit no crop field, and clients dereference a region's crop only via `GET /internal/assets/{asset_id}` (presigned `crop_url`, §3.7). If a citation is ever extended to inline a crop, it MUST be a per-request, post-ACL, redaction-aware presigned `crop_url` — never `crop_uri`.

The structured-citation builder generalizes the existing spreadsheet `_citation()` (`src/raku_rag/services/structured_tables.py:331-342`) — same factory, parameterized by `kind`, populating `chunk_id` with the anchors in §4.10.

### 4.6 `VisualAssetResponse` surfacing (asset view + assets.ts)

`AssetService.get_visual_asset()` (`src/raku_rag/services/assets.py:20-40`) returns `regions` and `crops`; `_region_json()` (`:57-73`) must emit `region_type`/`bbox` + a presigned **`crop_url`** (short-TTL, minted only after `can_read_document`, pointing at the redacted object when `visual_region_redaction_required=true`) and the redaction flags — the internal `crop_uri` is **never** serialized (§0.5-C4). The DTO field is renamed `crop_uri` → `crop_url` in `packages/shared/src/dto/assets.ts:14,21`. Extend:

1. **`AssetRegion`** (`packages/shared/src/dto/assets.ts:8-15`): add `structured_data_ref?: string` (the `table_id`/`form_id`/`chart_id` a region maps to) and `extraction_confidence?: number`, plus `embedded_image_provenance?` (§4.7). Populate in `_region_json()` from `chunk.metadata["structured_parent_id"]`.

2. **`VisualAssetResponse`** (`packages/shared/src/dto/assets.ts:26-38`): add a parallel `structured_content?` block so a single asset GET returns the parsed tables/forms/charts/captions for client rendering and aggregation:

```ts
export interface StructuredCell { column_name: string; column_index: number; value: string; cell_anchor: string; bbox?: BoundingBoxDto; }
export interface StructuredRow { row_id: string; row_number: number; cells: StructuredCell[]; }
export interface StructuredTable { table_id: string; page_number: number; columns: { name: string; index: number }[]; rows: StructuredRow[]; }
export interface StructuredFormField { form_id: string; field_name: string; field_label: string; field_value: string; field_type: string; required: boolean; page_number: number; }
export interface StructuredChartSeries { chart_id: string; series_name: string; series_type: string; axis_x_label: string; axis_y_label: string; unit: string; points: { label: string; value: number }[]; }
export interface StructuredCaption { caption_id: string; text: string; source: "ocr" | "generated" | "extracted_pdf_text"; referenced_region_ids: string[]; }

export interface VisualAssetResponse {
  /* …existing fields… */
  structured_content?: {
    tables: StructuredTable[];
    forms: StructuredFormField[];
    charts: StructuredChartSeries[];
    captions: StructuredCaption[];
  };
}
```

The server side: `get_visual_asset()` reads `structured_content` from the container chunk's metadata (or joins the leaf chunks) and emits it under the same ACL pre-filter already enforced at `assets.py:25` (`can_read_document`) — structured content inherits the parent document's ACL and is never returned for a document the principal cannot read.

### 4.7 Embedded-image provenance (PDF page + object id)

PDF-extracted images must be traceable to their source object, not just rendered pages. Add a provenance dataclass and attach it on every region/crop derived from an embedded image:

```python
@dataclass(frozen=True)
class EmbeddedImageProvenance:
    source_doc_ref: str        # the ingested PDF document_ref / S3 key
    page_number: int
    extraction_type: str       # "embedded_image" | "rendered_region" | "scanned_page"
    pdf_object_ref: str = ""   # PDF indirect object, e.g. "/XObject 12 0 R" or "/EmbeddedFile 5 0 R"
    original_width: int = 0    # source raster dimensions (for bbox→pixel mapping in CropService)
    original_height: int = 0
```

Stored as `LayoutRegion.metadata["embedded_image_provenance"] = asdict(prov)` and propagated to `Chunk.metadata` and `CropArtifact.metadata`. The `original_width/height` are required by `CropService.create_region_crop()` to convert normalized `BoundingBox` (`domain/models.py:145-152`) into pixel crops when minting real S3 crops (replacing the `memory://` placeholder). Surface as `AssetRegion.embedded_image_provenance?` in the asset view to enable a future "show in original PDF" affordance.

### 4.8 Redaction inheritance (mandatory)

Every structured leaf chunk MUST carry the full visual-redaction block produced by `_visual_redaction_metadata()` (`src/raku_rag/services/visual.py:58-78`): `sensitive_detected`, `sensitive_detection_labels`, `pii_redaction_applied`, `secret_redaction_applied`, `pii_redaction_policy_ref`, `visual_region_redaction_required`, `visual_region_redaction_status`, `visual_redaction_policy_ref`. Requirements:

1. **Value redaction at extraction time.** `StructuredTableCell.value`, `FormField.field_value`, and `ChartPoint.raw_text` are stored **post-redaction**, applying the same callable used for spreadsheets via `redact_table_manifest_values()` (`structured_tables.py:143-163`). Raw (pre-redaction) values are never persisted in `structured_content`.
2. **Flag propagation.** Copy the eight redaction keys from the parent `LayoutRegion.metadata` onto each leaf `Chunk.metadata` (the leaf inherits the container's detection result; a cell may additionally be flagged if its own value matched a detector).
3. **Citation propagation.** `_region_json()`/`_crop_json()` already emit `sensitive_detected`, `sensitive_detection_labels`, `visual_region_redaction_required`, `visual_region_redaction_status`, `visual_redaction_policy_ref` (`assets.py:66-72`, `:85-90`). The structured citation builder must copy these to `Citation` and the TS DTO so the UI can mask/blur and the audit log records that a redacted cell was cited.
4. **Crop URL gating (presigned, never raw).** `_public_region_crop_uri()` / `_public_crop_uri()` (`assets.py:120-137`) become **`_public_region_crop_url()` / `_public_crop_url()`**: they mint a short-TTL **presigned GET** (never a raw `s3://` or synthetic URI) only after `can_read_document`; when `visual_region_redaction_required`, the presigned URL targets the **redacted** crop object. Returned per-request as `crop_url`, behind ACL — applies identically to a `table_row`/`form_field` crop (§0.5-C4).

### 4.9 Migration shape

No new tables and no new structured columns — structured content rides the existing `jsonb metadata` columns: `chunks.metadata` for leaf cells (`structured_kind` / `structured_parent_id` / `table_id` / `form_id` / `chart_id`), `layout_regions.metadata['structured_content']` for the container envelope (read by `AssetService`), and `embedded_image_provenance` for PDF-origin "show in original" lookups. **The migration is specified once, canonically, in §6.2 — `0014_visual_understanding.sql`** (§0.5-B4): it adds the async-job + `extractor_version` columns and the structured-lookup indexes (GIN on `layout_regions.metadata->'structured_content'` + expression indexes on `chunks.metadata->>'structured_kind'`, `structured_parent_id`, and the `embedded_image_provenance` path, mirroring `idx_chunks_metadata_identifiers` at `0002:296-305`). There is **no second SQL block here** — §4.9 only documents which metadata keys ride the jsonb; §6.2 owns the DDL. Because all payload is `jsonb`, the in-memory stores used by the Tier-A gate need no migration — only the serialization shapes in `domain/models.py`.

### 4.10 Citing a specific cell / form field / chart point (anchors)

`chunk_id` is the citation anchor. Extend the existing schemes (`{document_id}:visual:{idx}` at `visual.py:25`; `{document_id}:table:{sheet_name}:R{row_id}` at `structured_tables.py:338`) to deterministic, parseable IDs:

| kind | `chunk_id` anchor | additional `Citation` fields |
|---|---|---|
| `visual` (base) | `{doc}:visual:{page}:{idx}` (§3.8; single-image path keeps `page=1`) | `asset_id`, `region_id`, `page_number` (already in metadata) |
| `table_row` | `{doc}:table_row:{table_id}:R{row_number}` | `table_id`, `row_id`, `column_name`, `cell_range` |
| spreadsheet cell | `{doc}:table:{sheet}:R{row}` + `cell_range="sheet!R{r}C{c}"` | `sheet_name`, `cell_range`, `row_id` (existing path) |
| `form_field` | `{doc}:form_field:{form_id}:{field_name}` | `form_id`, `field_name` |
| `chart_series` | `{doc}:chart_series:{chart_id}:{series_name}:P{point_index}` | `chart_id`, `series_name`, `point_index` |
| `figure_caption` | `{doc}:figure_caption:{region_id}` | `region_id` |

Cell-level precision uses the canonical token `sheet!R{row}C{col}` minted by `cell_anchor()` and parsed by `parse_cell_anchor()` (`src/raku_rag/providers/parsers.py:36-48`); store it in `Citation.cell_range` and in the leaf's `cell_anchors` map (§4.4). For Textract-origin tables the "sheet" component is the `table_id`, so a single regex round-trips spreadsheet and PDF-table citations. Round-trip: given a `Citation`, the asset view resolves `asset_id`+`region_id`+`bbox` to render the exact crop, and `cell_range`/`field_name`/`point_index` to highlight the specific cell/field/point.

### 4.11 Aggregation / structured-query reuse

`TableManifestStructuredTool` (`src/raku_rag/services/structured_tables.py:183-284`) already performs deterministic aggregation/ranking/latest/numeric-filter/period-filter over manifest rows and emits exact citations with `route="structured_tool"` (`:235`). Because Textract `StructuredTable.rows` use the **same** `{row_id, row_number, values, cells}` shape (§4.3) as the spreadsheet manifest (`structured_tables.py:120-128`), the tool requires no new query logic — only that the visual ingestion path also writes the Textract-derived tables into `Document.metadata[STRUCTURED_TABLE_MANIFESTS_KEY]` (`:29`, `:263`) so `_visible_rows()` (`:253-284`) sees them under the same ACL pre-filter (`can_read_document`, `:261`). Chart series add a parallel numeric surface: a `chart_series` leaf chunk's `column_values`/`points` feed the same `_aggregate`/`_rank` helpers (`:345-407`) keyed on `ChartPoint.value`.

---

**Implementation anchor summary:** new dataclasses → `src/raku_rag/domain/models.py` (near `:155-220`); chunk emission → `src/raku_rag/services/visual.py:17-55`; flat metadata helpers → generalize `src/raku_rag/services/structured_tables.py:166-181`; citation builder → generalize `:331-342`; asset surfacing → `src/raku_rag/services/assets.py:20-40,57-91`; DTOs → `packages/shared/src/dto/assets.ts:8-38` and `packages/shared/src/dto/answer.ts:9-24`; migration → §6.2's `infra/db/migrations/postgres/0014_visual_understanding.sql` (single canonical migration; pattern from `0002_...:296-305`).

---

## 5. Safety: Visual Evidence as First-Class (grounding + adversarial verify + audit)

### 5.1 Principle: extend, never weaken

The existing 002 hard rule is unchanged and remains the floor: a high-risk manufacturing answer MUST rest on an **approved + effective** citation or it MUST NOT assert (`ManufacturingSafetyGate.evaluate`, `src/raku_rag/manufacturing/safety/gate.py:116`). This section adds **one** new way for a citation to qualify as that approved+effective evidence — a *pixel-derived* citation (`pixel_derived=True`, i.e. `kind ∈ VISUAL_DERIVED_KINDS`; produced at `src/raku_rag/services/answer.py:451-467`) — but only after it clears a strictly *additional* gate (and only when its provenance is membership-promotable, so a VLM-inferred `chart_series`/caption never qualifies). Nothing here relaxes an existing check:

- The 001 `GroundednessGate.pre_gate` / `post_check` still run first and unchanged (`src/raku_rag/services/groundedness.py:24-37`, called at `answer.py:365`).
- The 002 `ManufacturingSafetyGate` still runs after (`answer_ext.py:282`), and the two post-answer demotions still run (`answer_ext.py:358-394`).
- AI output stays `draft`. Promotion changes *which evidence may back a high-risk assertion*, not the draft/human-review status of the output.
- A visual citation that fails ANY part of the new gate is treated exactly as a non-approved citation is treated today: it does not count toward `has_approved_effective`, so the high-risk block at `gate.py:116` / the demotion at `answer_ext.py:365-367` fires → `insufficient_evidence` (reference-only). This is strictly fail-closed: the default is "not promotable".

Promotion is **off by default**. It is gated behind `runtime_profile == "production"` AND an explicit `Settings.visual_evidence_promotion` flag AND a configured verifier quorum (§5.5). In the deterministic profile the visual gate never promotes, so the Tier-A gate and all existing tests are unaffected.

### 5.2 The four conditions for promotion (ALL required, AND-combined)

A pixel-derived citation `c` (`c.pixel_derived`, i.e. `c.kind ∈ VISUAL_DERIVED_KINDS`) may satisfy the high-risk approved+effective requirement for a given generated answer `text` iff (in addition to **(e) membership-promotable provenance** — `is_promotable_evidence(c.metadata)`, which a VLM-inferred `chart_series`/caption fails):

**(a) Source approved + effective.** Reuse the existing check verbatim — `is_approved_effective(get_mfg_meta(tenant, c.document_id), today)` (`src/raku_rag/manufacturing/safety/gate.py:51-59`, which calls `is_effective`, `gate.py:36-48`). The visual chunk inherits its parent document's manufacturing metadata, so the same enforcement point applies with no change. Draft / pending_review / obsolete / future-effective / missing-date all fail here (fail-safe), identical to text.

**(b) Strong grounding against OCR (NOT caption).** The asserted text must be a verbatim/subset-supported span of the cited region's **OCR text only**. The OCR span is `c`'s `metadata["primary_evidence_text"]`, which is set to `region.ocr_text` at ingestion (`src/raku_rag/services/visual.py:50`) and read back at `src/raku_rag/services/answer.py:685`. The VLM/captioner output `generated_caption_text` is **excluded** and can NEVER be the asserted high-risk evidence (FR-048; `src/raku_rag/spec/001-rag-platform/spec.md:266`, `interfaces/base.py:100`, `visual.py:12`). Precise check in §5.4.

**(c) Adversarial double-check.** N independent verifiers (quorum ≥ 2 in production) must *unanimously* concur that the OCR span supports the assertion AND that the rendered crop actually depicts what the assertion claims. Any single dissent ⇒ not promoted. Definition in §5.5.

**(d) Audit entry.** A reference-IDs-only audit record of the promotion: the visual citation id, asset_id, region_id, page_number, approval state at use, and each verifier's verdict. Definition in §5.6. No OCR text, caption text, or crop bytes are ever logged (SC-MFG-010).

### 5.3 Exact hook points

There are three edits, all additive. The promotion decision is computed where both the generated answer `text` and the visual chunk's OCR metadata are in scope (`answer.py`), stamped onto the `Citation`, then *consumed* by the existing high-risk demotion predicate (`answer_ext.py`). The audit is emitted at the existing answer-audit hook.

**Hook 1 — `src/raku_rag/services/answer.py:451-467` (the pixel-derived citation branch).**
`text` (the generated answer) is in scope from line 292/294; `ans_terms = _terms(text)` from line 416. When building any pixel-derived `Citation` (`kind ∈ VISUAL_DERIVED_KINDS`, so `pixel_derived=True`), compute the grounding+verify result against `chunk.metadata["primary_evidence_text"]` and stamp the `visual_evidence_verified` / `visual_verifier_verdicts` fields (declared once in §4.5) onto the `Citation`. Before appending the `Citation` (answer.py:452), call:

```python
verified, verdicts = verify_visual_primary_evidence(
    assertion=text,
    region=self._layout_region_from_chunk(c),   # answer.py:672-691 — ocr_text=primary_evidence_text
    verifiers=self._visual_verifiers,            # injected; see §5.5
    settings=self._settings,
)
```

Note: `_layout_region_from_chunk` (answer.py:672-691) already populates `ocr_text` from `primary_evidence_text` (line 685) and exposes `crop_uri` (line 688) for the VLM verifier. Set `visual_evidence_verified=verified` and `visual_verifier_verdicts=verdicts` on the `Citation`. This does NOT alter the existing `post_check` (groundedness.py:34), which still uses `chunk.text` (ocr+caption); the visual gate is a *stricter, separate* layer on top, never a relaxation.

**Important guard on the VLM generation path:** for high-risk queries the regions sent to the generator at `answer.py:271-274 / 291-294` must be pre-filtered to approved+effective source docs only, mirroring the existing approved-only lookup filter (`answer_ext.py:309-329`). This prevents a draft/obsolete crop's caption from poisoning the generated `text` before it is ever grounded. Pre-filter reduces poisoning; it is NOT promotion — promotion is decided post-generation in Hook 1.

**Hook 2 — `src/raku_rag/manufacturing/api/answer_ext.py:358-372` (high-risk demotion predicate).**
`ManufacturingCitation.from_base` (answer_ext.py:73-88) must copy the safety fields through so the `_admissible` gate (which runs over `mfg_citations`) can see `pixel_derived`, `visual_evidence_verified`, and the `metadata` that `is_promotable_evidence` reads (this is the §0.5-A5 copy-through set: `asset_id`/`region_id`/`page_number`/`bbox`/`crop_uri`/`pixel_derived`/`visual_evidence_verified`/`visual_verifier_verdicts`/`metadata`):

```python
# ManufacturingCitation — add fields + copy in from_base:
pixel_derived: bool = False
visual_evidence_verified: bool = False
# in from_base(cls, c, meta): ... pixel_derived=getattr(c, "pixel_derived", False),
#                                  visual_evidence_verified=getattr(c, "visual_evidence_verified", False),
#                                  metadata=c.metadata,   # so is_promotable_evidence(c.metadata) works on the overlay
```

Then change the per-citation admissibility predicate at `answer_ext.py:360-363`. Today it is:

```python
cited_approved_effective = [
    is_approved_effective(self._get_mfg_meta(tenant, c.document_id), today=self._today)
    for c in mfg_citations
]
```

Extend it so **every** pixel-derived citation must ALSO pass the visual gate, and **every** non-text citation must be membership-promotable — never a bare `kind == "visual"` test (§0.5-A1). Text citations are unchanged:

```python
def _admissible(c):
    base_ok = is_approved_effective(self._get_mfg_meta(tenant, c.document_id), today=self._today)
    if not base_ok:
        return False
    if c.kind == "text":
        return True                                  # text path unchanged
    # Non-text MUST be membership-promotable: a CaptionSource / empty / unknown provenance is
    # never primary — this is what stops a chart_series (VLM-inferred) or a generated caption
    # from satisfying high-risk on document-approval alone (FR-048):
    if not is_promotable_evidence(c.metadata):
        return False
    # Pixel-derived (crop-bearing: VISUAL_DERIVED_KINDS, §4.5) MUST also pass the §5 visual gate;
    # deterministic structured (e.g. spreadsheet) is admissible on membership alone — no crop to verify:
    return (not c.pixel_derived) or c.visual_evidence_verified
cited_approved_effective = [_admissible(c) for c in mfg_citations]
```

Worked outcomes: a `chart_series` (CaptionSource) fails `is_promotable_evidence` → never admissible; a `table_row`/`form_field`/`figure_caption` (Textract/OCR, promotable) is admissible only with `visual_evidence_verified`; a `spreadsheet` cell (deterministic, promotable, `pixel_derived=False`) is admissible on approval+membership like text; a plain `text` citation is unchanged.

`high_risk_unsupported = classification.is_high_risk and not all(cited_approved_effective)` (answer_ext.py:365-367) is then correct for visual evidence with no other change: an unverified visual citation makes the set non-uniform → demote to `insufficient_evidence` with `SafetyBlockReason.APPROVED_CITATION_MISSING` (answer_ext.py:372-394). The authoritative pre-gate (`ManufacturingSafetyGate.evaluate`, gate.py:116) is unchanged; it surveys *candidate* citations and remains the conservative first line. The promotion only ever *adds* an admissible source to the post-answer demotion check (Hook 2), never removes a block — so it cannot make an unsafe answer pass that the gate would have blocked on text grounds.

**Hook 3 — audit, `src/raku_rag/manufacturing/app.py:798-819`.** The answer-path already records the decision via `record_answer_decision` (`manufacturing/api/audit.py:36-98`) and citation access (app.py:824-831, action `citation.access`). Extend per §5.6.

### 5.4 Strong grounding verification (condition b), precisely

Let `O = normalize(region.ocr_text)` (the `primary_evidence_text`, caption excluded) and `A = normalize(assertion)` where `assertion` is the generated answer `text` (or, in a later iteration, the sentence(s) of `text` attributed to the region). `normalize` = NFKC fold + lowercase + whitespace collapse + strip. Tokenization reuses `content_terms` / `_terms` (the CJK-bigram tokenizer; `src/raku_rag/core/text.py`, used at groundedness.py:33 and answer.py:416).

`strong_grounding(A, O)` passes iff **`O` is non-empty** AND at least one of:

- **G1 (verbatim):** `A` is a contiguous substring of `O`; or
- **G2 (subset-supported):** `tokens(A) ⊆ tokens(O)` AND every digit/identifier anchor in `A` appears verbatim in `O`. Anchors are computed with the existing `_query_anchor_terms` / `_identifier_anchors` logic (answer.py:756-767, 419) — i.e., any token bearing a digit (equipment IDs, part numbers, torque/pressure values, dates) must be present verbatim in the OCR span.

Empty `O` ⇒ **fail-closed**: a pure photo/diagram/chart whose only text is a model-generated caption can never back a high-risk assertion (this is the operational meaning of FR-048). A chart's numeric series, a form's key-value, and a table's cells are admissible only via their Textract-extracted OCR/structured text in `O`, never via the caption.

Rationale (load-bearing): OCR text is a faithful transcription of pixels; the caption is a model paraphrase that can hallucinate. Only the transcription is admissible as asserted high-risk evidence. G2 with the verbatim-anchor requirement permits faithful rephrasing of prose while forbidding any fabricated or altered safety-critical number/identifier.

### 5.5 Adversarial double-check (condition c)

Promotion requires a configured quorum of **independent** verifiers, all concurring (unanimous). Verifier contract:

```python
@dataclass(frozen=True)
class VerifierVerdict:
    verifier_id: str        # e.g. "lexical_ocr_subset", "bedrock_claude_vision", "bedrock_claude_vision_2"
    passed: bool
    confidence: float       # 0..1, non-PII number
    reason_code: str        # CATEGORY only, e.g. "ocr_subset_ok" | "semantic_mismatch" | "anchor_absent"

class VisualEvidenceVerifier(Protocol):
    def verify(self, *, assertion: str, region: LayoutRegion) -> VerifierVerdict: ...
```

The verifier set always includes:

1. **`LexicalOcrSubsetVerifier`** (mandatory, deterministic, offline): implements §5.4 `strong_grounding`. Always runs; if it fails, promotion is denied regardless of any VLM verdict. This keeps the floor deterministic and testable on the Tier-A gate.
2. **K independent VLM verifiers** (production only): each re-reads the **real rendered crop** at `region.crop_uri` (the S3 crop, not a `memory://` placeholder) and independently confirms (i) the OCR span `O` is actually present in the region, and (ii) the region depicts what `A` asserts. Independence follows the canonical A4 rule (§0.5-A4): **distinct model ids from distinct provider families by default** (the portability layer (§2.8) enables a **Bedrock-Claude + Vertex-Gemini cross-family quorum**) — a different adversarial prompt (`"Does this image contradict the claim …?"`) on the **same** model never counts. Two models of the same family qualify only when `visual_verifier_allow_same_family_distinct_models=true` (default `false`, attestation-gated); otherwise an all-one-family tenant demotes to `insufficient_evidence` (block surfaced, not silent). The verifier is never the same call that generated the answer (`self._vlm.generate`, answer.py:292). Wired through the existing provider-selection seam (a `vlm_from_settings`-style factory; mirrors `llm_provider_from_settings`, providers/llms.py:190) with `ProviderPolicy` region/zero-retention/no-train enforced exactly as the parser router does.

Promotion (`visual_evidence_verified=True`) iff: `LexicalOcrSubsetVerifier.passed` (mandatory floor, does **not** count toward the quorum) AND **at least `Settings.visual_evidence_verifier_quorum` (default 2 in production) VLM verifiers** passing — counting VLM verifiers only, so `{lexical + 1 VLM}` does NOT satisfy quorum=2 (§0.5-A4) — AND **all** configured verifiers `passed`. Any dissent, or a verifier error/timeout, ⇒ `passed=False` for that verifier ⇒ **not promoted** (fail-closed). In the deterministic profile the quorum is not met (only the lexical verifier exists, and `visual_evidence_promotion` defaults `False`), so visual evidence is never promoted and remains reference-only — preserving current behavior and the fast gate.

The verifier `Settings` fields (`visual_evidence_verifier_quorum`, `visual_evidence_verifier_providers`, `visual_verifier_allow_same_family_distinct_models`, `max_regions_verified_per_answer`) and the master `visual_evidence_promotion` flag are declared **once** in the canonical §6.1 `Settings` block — not here.

### 5.6 Audit (condition d)

Extend the existing answer-decision audit (no new schema fields needed on `AuditLogEntry`; reuse `client_metadata`, which is non-PII and survives redaction — `manufacturing/domain/audit.py:82-128`, `sanitize_audit_log_entry`). At the `record_answer_decision` call (`manufacturing/app.py:802-819`), when a visual citation was promoted, add to `client_metadata`:

```python
"visual_evidence": [
  {
    "citation_id": c.chunk_id,           # e.g. "doc123:visual:0" (reference id, already in citation_ids)
    "asset_id": <asset_id>,              # reference id
    "region_id": <region_id>,            # reference id
    "page_number": <int>,
    "approval_status_at_use": "approved",
    "grounding_method": "ocr_subset",    # G1|G2 category, NOT the matched text
    "verifiers": [ {"verifier_id": ..., "passed": true, "confidence": 0.96, "reason_code": "ocr_subset_ok"}, ... ],
    "quorum": 2,
  },
]
```

The promoted visual `chunk_id`s already flow into `citation_ids` (app.py:799-801) and into the `citation.access` event (app.py:824-831), so citation-access auditing covers them with no change. Crucially: `ocr_text`, `generated_caption_text`, the assertion text, and crop bytes are **never** placed in the entry — only reference IDs, category codes, booleans, and numbers (SC-MFG-010; enforced by the writer's redaction as defense-in-depth, audit.py:12). Telemetry can therefore count promotion attempts vs. promotions and correlate verifier dissent (`passed=false`) with `safety_block_reason=approved_citation_missing` (`manufacturing/api/audit.py` answer entries) per factory/department/collection via the existing org-context stamp (T056).

### 5.7 Fail-closed behavior and downgrade-to-reference-only

Every failure path lands on the safe side — "no assertion without admissible evidence":

| Failure | Behavior |
|---|---|
| Source not approved+effective (a) | Visual citation not admissible → for high-risk, `high_risk_unsupported` → `insufficient_evidence`, `safety_block_reason=approved_citation_missing` (answer_ext.py:365-394). Obsolete source raises `obsolete_warning` and is shown reference-only (gate.py:88-92, 143). |
| Empty OCR / caption-only region (b) | `strong_grounding` fails (O empty) → not promoted → reference-only. FR-048 enforced. |
| Asserted number/identifier not verbatim in OCR (b/G2) | Anchor-absent → not promoted → reference-only (prevents fabricated torque/pressure/part-number assertions). |
| Quorum not met or any verifier dissents/errors/times out (c) | `visual_evidence_verified=False` → not promoted → reference-only. |
| VLM verifier unavailable in production | Verdict `passed=False` (fail-closed, same posture as LLM at answer.py:301-324) → not promoted. |
| Promotion disabled (deterministic profile / flag off) | Visual evidence never primary; behaves exactly as today. |

"Reference-only" = the visual region may still be retrieved, shown, and cited as supporting/contextual material (it survives `post_check` if its ocr+caption text overlaps the answer, groundedness.py:34), but it does **not** count toward the high-risk approved+effective requirement, so a high-risk answer with no *promotable* visual (and no approved+effective text) citation is demoted to `insufficient_evidence` rather than asserting. In all cases the output remains `draft` and human review is still required. The net effect is monotonic safety: promotion can only *add* an independently-verified, OCR-grounded, approved+effective visual source to the admissible set; it can never remove a block the existing 002 gate would raise.

---

## 6. Config, Migration, Rollout, Testing, Observability & Risks

This section specifies the operational envelope for the AWS-native visual extraction stack (Textract OCR/layout/tables/forms, Bedrock Claude vision captioning/VLM). The governing invariant is: **the deterministic offline stack stays the default and the Tier-A gate stays unchanged**. Every real provider is selected only when `runtime_profile == "production"` AND an explicit provider switch is set AND a per-tenant `ProviderPolicy` allows it. The composition root that wires this is `ProductionSystem.__init__` (`src/raku_rag/production.py:73-100`); the offline default is `DeterministicOcrEngine()` / `ExtractiveVLMProvider()` (`production.py:99`, `workers/ingestion.py:517-519`).

### 6.1 Config — new `Settings` fields + `RAKU_*` env

**This is the single, canonical declaration of every visual-related `Settings` field** (the §5.5 verifier fields and the portability provider/region/GCP/rollback fields are folded in here — there is no second `Settings` block anywhere). Extend the frozen `Settings` dataclass (`src/raku_rag/core/config.py:9-65`), mirroring the existing `embedding_provider` (line 30) / `llm_provider` (line 49) / `runtime_profile` (line 45) pattern. Everything defaults to `"deterministic"`/off so an un-set env reproduces today's behavior exactly (Tier-A unaffected):

```python
# src/raku_rag/core/config.py — add to @dataclass(frozen=True) class Settings

# Per-capability provider selection (vendor-neutral; overridden per-tenant by ProviderPolicy):
ocr_provider: str = "deterministic"           # | aws_textract | google_docai | azure_docintel | oss_tesseract
layout_provider: str = "deterministic"        # | aws_textract | google_docai | azure_docintel
structured_provider: str = "deterministic"    # | aws_textract | google_docai | azure_docintel
vlm_provider: str = "deterministic"           # | bedrock | google_gemini | azure_openai_vision
captioning_provider: str = "deterministic"    # | bedrock | google_gemini | oss_llava
visual_embedding_provider: str = "deterministic"  # | titan_multimodal (Hashing default, CTO #1)
vlm_model_id: str = ""                         # explicit Bedrock Claude vision / Vertex Gemini model id
caption_model_id: str = ""

# Regions (vendor-neutral; each "" falls back to aws_region):
aws_region: str = "ap-northeast-1"            # base AWS region (was us-east-1; CTO #1 region pin)
ocr_region: str = ""                          # "" -> aws_region; OCR/Textract endpoint region
vlm_region: str = ""                          # "" -> aws_region; Bedrock vision endpoint region

# GCP Workload Identity Federation (no long-lived keys; LATER — Vertex/Document AI):
gcp_project_id: str = ""
gcp_location: str = "asia-northeast1"
gcp_workload_identity_provider: str = ""      # full WIF provider resource name
gcp_workload_identity_sa_email: str = ""

# Crops:
crop_storage_uri: str = ""                    # "" -> memory:// (dev); "s3://<bucket>" -> real S3 crops

# Safety: first-class visual evidence (all default OFF / fail-closed):
visual_evidence_promotion: bool = False       # RAKU_VISUAL_EVIDENCE_PROMOTION (§6.4 master flag, SAFETY)
visual_evidence_verifier_quorum: int = 2      # RAKU_VISUAL_EVIDENCE_VERIFIER_QUORUM (≥2 in production)
visual_evidence_verifier_providers: str = ""  # RAKU_VISUAL_EVIDENCE_VERIFIERS (csv of DISTINCT-FAMILY ids, A4)
visual_verifier_allow_same_family_distinct_models: bool = False  # attestation-gated same-family escape (A4)
max_regions_verified_per_answer: int = 3      # answer-time verifier cost/latency cap (§6.5/C9)

# Ingestion + global rollback:
max_inline_ocr_bytes: int = 5_000_000         # images ≤ this go inline; larger + ALL PDFs are async (§3.2)
force_deterministic: bool = False             # RAKU_FORCE_DETERMINISTIC=1 -> every *_from_settings → offline
```

Add the corresponding reads to `settings_from_env()` (`src/raku_rag/core/config.py:79-172`) next to the `llm_provider` read (line 154), reusing the existing `_get` / `_bool` / `_int` helpers (lines 87-100) — every field above is parsed by its `RAKU_*` env var (e.g. `RAKU_OCR_PROVIDER`, `RAKU_OCR_REGION`, `RAKU_VLM_PROVIDER`, `RAKU_CROP_STORAGE_URI`, `RAKU_VISUAL_EVIDENCE_PROMOTION`, `RAKU_FORCE_DETERMINISTIC`, …):

```python
ocr_provider=_get("RAKU_OCR_PROVIDER", Settings.ocr_provider),
vlm_provider=_get("RAKU_VLM_PROVIDER", Settings.vlm_provider),
ocr_region=_get("RAKU_OCR_REGION", Settings.ocr_region),
crop_storage_uri=_get("RAKU_CROP_STORAGE_URI", Settings.crop_storage_uri),
visual_evidence_promotion=_bool("RAKU_VISUAL_EVIDENCE_PROMOTION", Settings.visual_evidence_promotion),
force_deterministic=_bool("RAKU_FORCE_DETERMINISTIC", Settings.force_deterministic),
# … and the remaining provider/region/GCP/verifier fields, same pattern.
```

The six factories (`ocr_from_settings`, `layout_from_settings`, `structured_from_settings`, `vlm_from_settings`, `captioning_from_settings`, `visual_embedding_from_settings`, in `providers/factories.py`) follow the exact `*_from_settings(settings, *, invoker=None) -> Provider` shape of `llm_provider_from_settings` (`providers/llms.py:190-219`) and `guardrail_from_settings` (`providers/guardrails.py:93-112`): normalize the name (`.strip().lower().replace("-","_")`), honor the explicit per-capability switch first, then fall back to `runtime_profile`. A set `force_deterministic` (`RAKU_FORCE_DETERMINISTIC=1`) short-circuits **every** factory to the offline adapter regardless of per-capability settings — the instant, no-redeploy rollback. **Fail-closed** semantics like the LLM path (raise `RuntimeError("ocr_provider_not_configured")` if `production` + no invoker), NOT the fail-safe reranker path (`providers/rerankers.py:88-101`) — an image that cannot be OCR'd must not silently become a text-less chunk. These are called in the composition root: replace `production.py:99` (`self.vlm = ExtractiveVLMProvider()`) with `self.vlm = vlm_from_settings(self.settings)` and add `self.ocr = ocr_from_settings(...)`, `self.layout = layout_from_settings(...)`, `self.captioning = captioning_from_settings(...)`, then thread them into `VisualIngestionExecutor(ocr=..., layout=..., captioning=...)` (the executor already accepts these params — `workers/ingestion.py:507-522`).

Runtime-profile truth table (composition root behavior):

| `runtime_profile` | `RAKU_OCR_PROVIDER` | Result |
|---|---|---|
| `deterministic` (default) | unset | `DeterministicOcrEngine`, `ExtractiveVLMProvider` — **Tier-A unchanged** |
| `deterministic` | `aws_textract` | Still deterministic (profile gate wins; explicit switch ignored unless production) |
| `production` | unset | Deterministic visual providers remain selected; real OCR/VLM/captioning stay disabled until explicit provider env/context is set |
| `production` | `aws_textract` | `TextractOcrLayoutEngine(invoker=build_aws_textract_invoker(region_name=settings.ocr_region or settings.aws_region))`; PDF jobs use `AsyncDocumentAnalyzer` with the same provider policy gate |

### 6.2 DB migration — async-job + provenance columns (structured payloads stay in `metadata` jsonb)

The visual tables already exist with `metadata jsonb` escape hatches: `visual_assets`, `layout_regions`, `crops`, `embeddings` in `infra/db/migrations/postgres/0002_policy_profile_visual_rls.sql:9-81`, all tenant-scoped via `tenant_isolation_*` RLS (lines 365-396). Per **§0.5-B4** the structured-extraction payload + provenance nest into those existing `metadata` columns — **not** new columns; per **§0.5-C14** promotion verdicts are recomputed at read and are **never persisted** (no `*_verified` / verifier-count columns). The only new top-level columns are the vendor-neutral async-job state and the extractor version. Add a forward+down pair as the next sequence number — **`0014_visual_understanding.sql`** / `.down.sql` (current HEAD is `0013_datasource_sync_runtime.sql`), applied in-VPC by the existing `MigrateSeedTask` RunTask (`infra/cdk/lib/raku-rag-stack.ts:851-874`, runs `scripts/pg-migrate.sh up`).

```sql
-- 0014_visual_understanding.sql  (PostgreSQL; assumes 0002 ran). Additive / expand-only.
SET search_path TO public;

-- (1) Async document-analysis job state — the ONLY new run-level columns (vendor-neutral JobHandle):
ALTER TABLE ingestion_runs
  ADD COLUMN IF NOT EXISTS async_provider   text NOT NULL DEFAULT '',   -- '' | 'aws_textract' | 'google_docai' | 'azure_docintel'
  ADD COLUMN IF NOT EXISTS async_job_id     text NOT NULL DEFAULT '',   -- vendor-opaque JobHandle.token (Textract JobId | DocAI LRO name | Azure op-location)
  ADD COLUMN IF NOT EXISTS async_job_status text NOT NULL DEFAULT '';   -- '' | PENDING | MORE_AVAILABLE | PARTIAL_FAILURE | SUCCEEDED | FAILED

-- (2) Extractor provenance for staleness/backfill — the ONLY new asset-level column:
ALTER TABLE visual_assets
  ADD COLUMN IF NOT EXISTS extractor_version text NOT NULL DEFAULT '';

-- (3) Structured payload + crop S3 URIs REUSE the existing jsonb escape hatches (NO new columns):
--   layout_regions.metadata -> 'structured_content'  : StructuredContent envelope (§2.1)
--   layout_regions.metadata ->> 'extraction_source' / 'caption_source' : disjoint provenance (§2.1)
--   crops.crop_uri  : now holds 's3://…' (was 'memory://…')  — column REUSED, not added
--   crops.metadata  ->> 'redacted_crop_uri' / 'source_page_number' / 'original_resolution'
-- Structured-lookup indexes (§0.5-B4) — GIN over the container envelope + expression indexes
-- for leaf-chunk citation/aggregation, mirroring idx_chunks_metadata_identifiers (0002:296-305):
CREATE INDEX IF NOT EXISTS idx_layout_regions_structured
  ON layout_regions USING gin ((metadata -> 'structured_content'));
CREATE INDEX IF NOT EXISTS idx_chunks_structured_kind
  ON chunks ((metadata->>'structured_kind'))
  WHERE metadata ? 'structured_kind' AND NOT tombstone;
CREATE INDEX IF NOT EXISTS idx_chunks_structured_parent
  ON chunks ((metadata->>'structured_parent_id'), (metadata->>'structured_kind'))
  WHERE metadata ? 'structured_parent_id' AND NOT tombstone;
CREATE INDEX IF NOT EXISTS idx_chunks_pdf_provenance
  ON chunks ((metadata#>>'{embedded_image_provenance,source_doc_ref}'),
             (metadata#>>'{embedded_image_provenance,page_number}'))
  WHERE metadata ? 'embedded_image_provenance';
```

Migration is **additive and backward-compatible** (all `ADD COLUMN IF NOT EXISTS ... DEFAULT`), so it deploys ahead of code (expand/contract). RLS is inherited automatically — the new columns sit on `ingestion_runs` / `visual_assets`, which already carry their `tenant_isolation_*` policies (`0002:365-396`); structured payloads and crop URIs stay inside the already-RLS'd `layout_regions.metadata` / `crops` rows. The `.down.sql` drops only the three `async_*` columns, `extractor_version`, and the four structured indexes (the GIN index + the three `chunks` expression indexes); it must NOT drop the tables (those predate this feature), and there is **no promotion-verdict column to roll back** (verdicts are recomputed at read, §0.5-C14). No `embeddings` change is required for v1 — visual embeddings stay Hashing (CTO #1), reusing the `target_type='visual_asset'`, `modality='visual'` rows (`0002:66-81`).

### 6.3 CDK / IAM changes (cite infra anchors)

Three changes to `infra/cdk/lib/raku-rag-stack.ts`:

1. **Textract IAM.** Add a `grantTextractInvoke(taskRole)` method beside `grantBedrockInvoke` (`raku-rag-stack.ts:1205-1216`), scoped least-privilege to the pinned region:
   ```ts
   private grantTextractInvoke(taskRole: iam.IRole): void {
     taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
       actions: ["textract:AnalyzeDocument", "textract:DetectDocumentText",
                 "textract:StartDocumentAnalysis", "textract:GetDocumentAnalysis"],
       resources: ["*"]  // Textract has no resource-level ARNs; constrain via region + condition
     }));
   }
   ```
   Call it on both task roles that today get Bedrock: the worker (`raku-rag-stack.ts:695`, after `grantBedrockInvoke(workerTask.taskRole)`) and the answer-service (`raku-rag-stack.ts:757`). `bedrock:InvokeModel` for Claude vision is **already granted** by the existing `grantBedrockInvoke` (`raku-rag-stack.ts:1205-1216`, `foundation-model/*`), so VLM captioning needs no new Bedrock policy.

2. **S3 crop bucket.** Add a `cropBucket` mirroring `documentBucket` (`raku-rag-stack.ts:166-174`) — same `BlockPublicAccess.BLOCK_ALL`, `BucketEncryption.KMS` with `dataKey`, `enforceSSL`, `versioned`, `removalPolicy`. Grant it in `attachRuntimePolicies` (`raku-rag-stack.ts:1193-1200`, which currently only does `documentBucket.grantReadWrite`) — pass `cropBucket` through and `cropBucket.grantReadWrite(taskRole)` for worker (write crops) + answer-service (read crops for `GET /internal/assets/{asset_id}`, `apps/answer-service/server.py:1584-1591`). This is what lets `CropService.create_region_crop` (`src/raku_rag/services/crop.py:47-95`) stop emitting `memory://crops/...` placeholders (`crop.py:73,79-82`) and write real `s3://` objects; inject an `S3CropStore` in place of the default `InMemoryCropStore` (`crop.py:13-45`) when `settings.crop_storage_uri` starts with `s3://`.

3. **Env wiring.** Extend `productionRuntimeEnvironment` (`raku-rag-stack.ts:99-107`) — which already flips `RAKU_RUNTIME_PROFILE=production` only when guardrail context is present — to also inject `RAKU_OCR_PROVIDER` / `RAKU_VLM_PROVIDER` / `RAKU_LAYOUT_PROVIDER` / `RAKU_CAPTIONING_PROVIDER` / `RAKU_TEXTRACT_REGION` / `RAKU_CROP_STORAGE_URI`, gated behind new CDK context flags (`--context ocrProvider=aws_textract --context vlmProvider=bedrock`) parsed like `answerLlm` (`raku-rag-stack.ts:77-78`). Context values are canonical provider IDs from the capability registry (`aws_textract`, `bedrock`, `google_docai`, `google_gemini`); vendor/model-specific provenance such as `bedrock_claude_vision` is emitted only as a result/source tag. This dict is already spread into the answer container env at `raku-rag-stack.ts:791-792`; add the same spread to the worker container. Deploy command:
   ```
   npx cdk deploy --context stage=prod --context minimalSpec=false --context domainName=... \
     --context answerLlm=bedrock --context bedrockGuardrailId=... --context bedrockGuardrailVersion=... \
     --context ocrProvider=aws_textract --context vlmProvider=bedrock
   ```

### 6.4 Phased rollout behind a feature flag (per-tenant)

Two independent gates, both default-off, so the blast radius is controlled:

- **Global capability flag** (does the running stack even call Textract/Bedrock vision): `RAKU_OCR_PROVIDER` / `RAKU_VLM_PROVIDER` env, only honored under `runtime_profile=production` (§6.1). With these unset, prod behaves exactly like deterministic for visual.
- **Per-tenant enablement**: the existing `ProviderPolicy` (`workers/ingest/provider_policy.py:37-104`) is the per-tenant allowlist, persisted in `provider_policies` (`0002:154-179`). A tenant is opted in only when `allowed_ocr_providers` contains `aws_textract` (`provider_policy.py:43`) AND `customer_opt_in_status == "granted"` (`provider_policy.py:53`, enforced at `provider_policy.py:194-199`). `ProviderPolicyEnforcer.evaluate` already maps `operation="ocr"` to `allowed_ocr_providers` (`provider_policy.py:141`) and rejects out-of-region (`provider_policy.py:181-186`), non-zero-retention (`188-189`), trainable (`191-192`) providers — this is the egress gate (§6.5).
- **Visual-as-primary-evidence** (the SAFETY-critical CTO #3 escalation) is a *third*, strictest flag: `visual_evidence_promotion` (default `False`). When off, visual citations remain reference/candidate-only and CANNOT satisfy the high-risk "approved+effective citation" requirement; when on, a visual citation may be promoted only after passing grounding-subset + multi-verifier + audit (enforced in `SafetyGate.evaluate`, `manufacturing/safety/gate.py:73-146`, via `is_approved_effective`, `gate.py:51`). Rollout order: (1) prod with OCR/VLM on but `visual_evidence_promotion=False` (captions are search aids only) for N tenants → (2) enable primary-evidence for one design-partner tenant via per-tenant policy → (3) general availability. Each stage is reversible by env flip + redeploy with zero data migration.

### 6.5 Cost & latency budget

**Textract (async `StartDocumentAnalysis`, `FeatureTypes=[TABLES,FORMS,QUERIES]`):** first-tier list price ≈ Tables $0.015 + Forms $0.05 + Queries $0.015 per page ≈ **$0.08/page**. A typical 10-page manufacturing SOP ≈ **$0.80** one-time at ingest. Use async (not sync `AnalyzeDocument`) for any doc > 1 page in the worker (`IngestionWorker.process_once`, `workers/ingestion.py:782-831`): submit job, persist the `JobHandle.token` in `ingestion_runs.async_job_id`/`async_provider` (§0.5-B5, the single home for the handle — NOT `VisualAsset.metadata`), poll on next worker tick — keeps the worker non-blocking. Single standalone images use sync. (Textract enables `QUERIES` only on this `application/pdf` async path, per the AWS-PDF override in §2.1; the per-page cost above prices it in.)

**Bedrock Claude vision (per non-text region):** captioning is invoked **only per detected figure/photo/diagram region**, not per page. Budget ≈ ~$0.002–0.004 per region (image input tokens + short caption output). A doc with ~3 figures ≈ **$0.01**. Use Textract (10× cheaper) for OCR/tables/forms; reserve Claude vision strictly for semantic captioning of non-text regions (CTO #1).

**Per-doc ceiling** ≈ Textract pages + VLM regions ≈ `$0.08·pages + $0.003·regions`. Guardrails/caps, all fail-closed:
- `max_pages_per_visual_doc` (reject/queue-DLQ beyond, e.g. 100) — protects against a 500-page scan blowing $40 in one job.
- `max_vlm_regions_per_page` (e.g. 8) — caps captioning fan-out per page.
- Per-tenant monthly spend cap enforced through the **existing** `budgets` table + `CostService` (`0002:97-108`); the visual executor already takes a `cost: CostService` param (`workers/ingestion.py:515,522`). Record one `cost_records` row (`0002:83-95`) per Textract job and per VLM call (`kind='textract_pages'` / `kind='bedrock_vision_regions'`) so spend is attributable per `tenant`/`collection`/`document`.
- Hard region pin `ocr_region`/`vlm_region` (default `aws_region=ap-northeast-1`, §6.1) + `zero_retention`/`no_train` enforced by `ProviderPolicyEnforcer.evaluate` (`provider_policy.py:181-192`) — out-of-region or retaining providers are rejected before any bytes egress.

### 6.6 Testing strategy

**Tier-A (must stay deterministic, stdlib-only, ~ms, GREEN unchanged — `scripts/gate.sh` Tier A, `gate.sh:24-34`):** all new factories default to deterministic, so existing `tests/unit/test_visual_ingestion.py`, `test_crop_service.py`, and `tests/integration/test_visual_eval.py` are unaffected. Add **offline** unit tests using the injected-invoker seam (the exact pattern of `tests/unit/test_llm_provider_profile.py:48-65`): a `mock_ocr_invoker(image: bytes) -> tuple[OcrTextRegion, ...]` and `mock_vlm_invoker(query, image) -> str` returning fixtures, passed via `ocr_from_settings(settings, invoker=mock_ocr_invoker)`. These prove provider selection + fail-closed behavior with zero AWS SDKs installed.

**Provider-policy contract tests (the security-load-bearing ones):** assert that `ProviderPolicyEnforcer.assert_allowed` (`provider_policy.py:210-213`) raises `ProviderPolicyViolation` **before** any invoker is called, for: (a) `aws_textract` outside `allowed_regions` (`provider_policy.py:181-186`), (b) provider lacking `zero_retention`/`no_train` (`188-192`), (c) `customer_opt_in_status != "granted"` (`194-199`). Use a spy invoker that records whether it was ever entered — the test fails if raw bytes reached the invoker after a deny. This proves the "no raw-bytes egress before policy passes" invariant for the new OCR/VLM operations.

**Tier-B (real Postgres + provider FAKES — `gate.sh:55+`, Docker compose Postgres/pgvector/RLS):** run the `0014` migration against real PG; assert the new `ingestion_runs.async_*` + `visual_assets.extractor_version` columns and the `idx_layout_regions_structured` GIN index persist, that `layout_regions.metadata->'structured_content'` round-trips and `crops.crop_uri` holds `s3://`, that **no promotion-verdict column exists** (verdicts recomputed at read, §0.5-C14), and that RLS still isolates them per tenant (extend the `tests/security/` ACL+deletion-cascade suites — visual crops must tombstone-cascade with the parent document). Providers are **fakes**, not live AWS: a `FakeTextractInvoker` returning a recorded Textract JSON fixture parsed into `OcrTextRegion[]`, and a `FakeClaudeVisionInvoker`. This exercises the full ingest→store→retrieve→cite path over real SQL without spending on AWS and without flaking on network.

**Eval-harness extension:** `p95_visual_answer_latency_ms` is already produced (`src/raku_rag/eval/runner.py:207`) and bounded in `DEFAULT_MAX_METRICS` at 5000.0 (`src/raku_rag/eval/baseline.py:40`, matching `Settings.target_visual_p95_latency_ms`, `config.py:26`). Add eval items whose `expected_evidence` is a structured region (table_row/figure_caption) so `visual_recall_at_k`, `visual_citation_accuracy`, `bbox_iou`, and `visual_groundedness` (`runner.py:203-206`, min-gated at `baseline.py:32-35`) cover the new extraction; add a `visual_grounding_subset_rate` metric asserting the asserted text ⊆ cited-region OCR text for safety answers. The baseline gate keeps these as hard min/max thresholds so a regression blocks the build.

### 6.7 Observability metrics

Emit (via the existing cost/telemetry seams — `CostService` → `cost_records` `0002:83-95`, Langfuse exporter gated by `langfuse_enabled` `config.py:53`):
- `visual.ocr.textract_pages_total`, `visual.ocr.textract_cost_usd` (per tenant/collection).
- `visual.vlm.regions_captioned_total`, `visual.vlm.cost_usd`.
- `visual.ocr.async_job_latency_ms`, `p95_visual_answer_latency_ms` (eval + live, `runner.py:207`).
- `visual.ocr.failure_total{reason}`, `visual.async.dlq_depth` (jobs that exhausted Textract polling → DLQ).
- `safety.visual_primary_evidence_promoted_total`, `safety.visual_grounding_verifier_fail_total`, `safety.visual_block_total{reason}` — driven from the audit log, the SSOT. Each promotion/block is an immutable `AuditLogEntry` (`manufacturing/domain/audit.py:82`) carrying reference IDs only (`citation_ids` = visual `asset_id:region_id`, `safety_block_reason`, `approval_status_at_use`) — never `ocr_text` / `crop_uri` / caption body (sanitized by `sanitize_audit_log_entry`, `audit.py:289`).
- `providerpolicy.ocr.denied_total{reason}` — counts `ProviderPolicyViolation` (egress blocks), a leading indicator of misconfig or a tenant attempting a disallowed region/provider.

### 6.8 Risks

| # | Risk | Likelihood / Impact | Mitigation | Fallback |
|---|---|---|---|---|
| R1 | **VLM hallucination promoted to PRIMARY evidence on a high-risk safety answer** (caption asserts a torque/voltage value not in the document) | Med / Critical | `visual_evidence_promotion` default-OFF (§6.4); promotion requires grounding-subset check (asserted text ⊆ region OCR), multi-verifier double-check, and source `approved+effective` via `is_approved_effective` (`safety/gate.py:51`) before `SafetyGate.evaluate` (`gate.py:73-146`) returns OK | Demote to `insufficient_evidence` with `APPROVED_CITATION_MISSING`; AI output stays `draft` (002 hard rule, unchanged) |
| R2 | **Cost blow-up** — a few-hundred-page scan or runaway captioning drains the AWS bill | Med / High | `max_pages_per_visual_doc`, `max_vlm_regions_per_page` caps; per-tenant monthly `budgets` (`0002:97-108`) enforced by `CostService`; async Textract over sync; Textract-for-OCR not Claude (§6.5) | Over-budget → ingest job rejected to DLQ, alert on `cost_records` spend; visual stays unindexed, text layer still ingests |
| R3 | **Async Textract job fails / never returns** (`GetDocumentAnalysis` stuck, throttling) | Med / Med | Poll with bounded retries + timeout in worker (`workers/ingestion.py:782-831`); persist `job_id` for idempotent re-poll; fail-closed OCR (no silent text-less chunk) | Route to SQS DLQ (`raku-rag-stack.ts:176-181`, `maxReceiveCount:5`); document marked `ocr_failed`, retriable; **never** ingest a doc with empty OCR as if complete |
| R4 | **Data residency / cross-region leak** — bytes sent to a non-JP Textract/Bedrock endpoint | Low / Critical | Hard `ocr_region`/`vlm_region` pin (default `aws_region=ap-northeast-1`, §6.1); `ProviderPolicyEnforcer.evaluate` rejects out-of-region (`provider_policy.py:181-186`) and non-zero-retention/trainable providers (`188-192`) before invoker call; contract tests in §6.6 prove no-egress-before-policy | Policy violation raises `ProviderPolicyViolation`, ingest blocked, audited via `provider_config_audit_events` (`0002:260-271`) |
| R5 | **Provider unavailable / not configured in production** (missing boto3, missing IAM, Bedrock model not enabled) | Med / Med | Fail-closed factories (raise `RuntimeError`), surfaced at composition root (`production.py:96-99`); CDK guard already throws if prod Bedrock lacks guardrail context (`raku-rag-stack.ts:94-98`) | Per-tenant `ProviderPolicy.fallback_policy` (`provider_policy.py:215-231`) → `aws_textract`/`tesseract`; or flip provider env back to `deterministic` and redeploy (no data migration) |
| R6 | **Crop URI migration regression** — answer-service serves stale `memory://` crops or broken S3 links | Low / Med | `crops.crop_uri` is REUSED (`memory://`→`s3://`, no new column); `CropService` selects store by `crop_storage_uri` (`crop.py:44-45`); Tier-B asserts real `s3://` after migration; never returned raw (presigned `crop_url` only, §0.5-C4) | If S3 store errors, fall back to no-crop citation (text/OCR still cited); crops are display aids, not the grounding source |
| R7 | **Eval/Tier-A drift** — adding real providers accidentally slows or changes the deterministic gate | Low / High | Profile gate ensures deterministic stays default; no AWS SDK import on the deterministic path (lazy imports only, `providers/embeddings.py:90`); baseline min/max gate (`baseline.py:28-43`) blocks metric regressions | CI Tier-A is stdlib-only and authoritative (`gate.sh:24-34`); a real-provider import on the hot path fails the gate |

---

## 7. Phased Delivery Plan

Epics are dependency-ordered. **Critical path: A → B → (C ∥ D) → E → F → G → H.** Each task names the files it touches and an explicit gate. `[HUMAN]` marks safety-boundary tasks that require human design/review and ship only as a complete set (Epic F). Gate legend: **G-A** = Tier-A deterministic stays green/stdlib-only; **G-Pol** = ProviderPolicy raw-bytes egress audit test passes before any provider call; **G-Ground** = grounding + adversarial-verify unit tests (promote only on full quorum; caption/empty-OCR/vlm-source never promote).

> The first epics (A–E2) below were re-derived from §§1–6 to complete the plan; tasks E3 onward are as synthesized. All tasks honor §0.5 (NORMATIVE).

### Epic A — Provider seams & settings (foundation)
- **A1.** Add `ocr_provider` / `vlm_provider` / `layout_provider` / `structured_extraction` `Settings` fields + `RAKU_*` env parsing in `settings_from_env`, defaulting to the deterministic offline providers. Files: `src/raku_rag/core/config.py`. Gate: G-A (deterministic default unchanged).
- **A2.** Add `ocr_from_settings` / `vlm_from_settings` / `layout_from_settings` selectors mirroring `llm_provider_from_settings` (`providers/llms.py:190`); inject at `production.py:99` / `app.py:65` / the `VisualIngestionExecutor` defaults. Files: `src/raku_rag/providers/*`, `production.py`, `app.py`, `workers/ingestion.py`. Gate: G-A.
- **A3.** `OcrPolicyRouter` / `VlmPolicyRouter` (+ Textract/Bedrock capability adapters) modeled on `ProviderPolicyParserRouter` (`parsers/__init__.py:248-330`); fix `DEFAULT_PROVIDER_CAPABILITIES` region → `ap-northeast-1` (§0.5-C8); enforce `region/zero_retention/no_train` + persisted `raw_content_sent` audit. Files: `workers/ingest/provider_policy.py`, new router module. Gate: G-Pol.

### Epic B — Real OCR/VLM adapters + ingestion (depends on A)
- **B1.** `TextractOcrLayoutEngine` (sync single-image, behind the real `extract(image, *, ctx: IngestContext, …)` signature, §0.5-B1) + `AsyncDocumentAnalyzer.submit/poll` async seam (§0.5-B2). Files: new `providers/ocr/textract.py`. Gate: G-Pol + Tier-B provider-fake contract test.
- **B2.** `BedrockVisionVLMProvider` (replaces hardcoded `ExtractiveVLMProvider` for the production profile) + `BedrockVisionCaptioningProvider`. Files: `providers/vlms/`, `providers/captioning/`. Gate: G-Pol.
- **B3.** `PdfPageParser` / `PdfImageExtractor` (page rasterization + embedded-image extraction, **lazy imports** §0.5-C12; fail-soft per region §0.5-C13). Files: new `workers/ingest/providers/pdf.py`, `production.py:89`. Gate: G-A (lazy-import test) + Tier-B.
- **B4.** Real S3 crop rendering — `S3CropStore` replacing `memory://` URIs (`services/crop.py:73,114`); EXIF strip + redaction on **real** OCR/VLM output before persist. Files: `services/crop.py`, `workers/ingestion.py`. Gate: Tier-B redaction-before-persist test.

### Epic C — Structured extraction (depends on B; runs ∥ D)
- **C1.** `TextractStructuredExtractor` → tables→rows / forms→KV / queries; each value stamped with an `ExtractionSource` (transcription space, e.g. `aws_textract`) via the `StructuredNormalizer` (§2.1, §0.5-A3). Files: new `providers/structured/textract.py`. Gate: Tier-B.
- **C2.** Chart→numeric series via VLM, stamped with a `CaptionSource` (∉ `PROMOTABLE_EXTRACTION_SOURCES` → reference-only, never primary). Files: `providers/structured/`. Gate: G-Ground (caption-source never promotes).

### Epic D — Data model & DTO (depends on B; runs ∥ C)
- **D1.** Structured payloads nested in `chunk.metadata` jsonb + GIN identifier index; new top-level columns limited to async-job state + `extractor_version` (§0.5-B4). Files: `domain/models.py`, migration `0014`.
- **D2.** Stamp `VisualAsset.metadata["extractor_version"]`; embedded-image provenance (page + PDF object id). Files: `domain/models.py`, `workers/ingestion.py`.
- **D3.** Surface structured cells + presigned crop URLs (the `crop_url` DTO field, minted per-request after `can_read_document` with redaction applied per §0.5-C4 — never raw `crop_uri`) in `VisualAssetResponse` / `assets.ts` / openapi; structured cells inherit redaction metadata. Files: `services/assets.py`, `packages/shared/src/dto/assets.ts`, `apps/api/src/openapi`. Gate: API contract test.
- **D4.** `Citation` safety fields (`pixel_derived`, `visual_evidence_verified`, `visual_verifier_verdicts`, `asset_id`/`region_id`/`page_number`); presigned-crop access gated by `can_read_document`, redacted variant when required (§0.5-C4). Files: `domain/models.py`, `services/assets.py`. Gate: signed-URL-ACL test.

### Epic E — Ingest routes & async worker (depends on B, D)
- **E1.** Async document-analysis job-lifecycle state machine: persist `async_provider`/`async_job_id`/`async_job_status` (§0.5-B5), extend queue protocol with delayed re-drive/in-progress visibility (§0.5-C1). Files: `workers/ingestion.py`, migration `0014`. Gate: Tier-B worker poll/redrive test.
- **E2.** Wire `vlm_from_settings`-style multi-provider verifier factory groundwork (consumed by F2/G1). Files: `providers/vlms/`. Gate: G-A.
- **E2 (cont.)** Gate: Tier-B worker poll/redrive test.
- **E3.** Content-type dispatch: `ProductionSystem.ingest_document` (`production.py:166`) routes `application/pdf` → `enqueue_visual_document` (always async, returns queued run), `image/*` ≤`max_inline_ocr_bytes` → inline `ingest_visual_document`; `IngestionWorker.process_once` (`ingestion.py:806`) branch on `message.content_type` (`:41`). Files: `production.py`, `workers/ingestion.py`. Gate: G-A + Tier-B PDF-enqueue test.
- **E4.** `POST /internal/ingest` (`server.py:1944`) PDF → `202` + `status_url`; `IngestController.@Post("upload")` multipart + S3 round-trip + `415`/`413` validation. Files: `apps/answer-service/server.py`, `apps/api/src/ingest/ingest.controller.ts`. Gate: API contract test.
- **E5.** Visual re-ingest/replace: tombstone-and-replace all prior assets/regions/chunks/S3 crops for `document_id` (reuse `deletion.py:133-157` + physical `DeleteObject`) before a new run. Files: `production.py`, `services/deletion.py`, `services/crop.py`. Gate: Tier-B re-ingest-orphan test.

### Epic F — Safety: first-class visual evidence (depends on D, E) — all [HUMAN]
- **F1. [HUMAN]** `Citation` safety fields already in D4; stamp `pixel_derived/visual_evidence_verified/visual_verifier_verdicts` in the `is_visual` branch (`answer.py:451-467`); sentence-level attribution `_attributed_sentences`. Files: `src/raku_rag/services/answer.py`, `domain/models.py`. Gate: G-Ground (no promotion path live yet).
- **F2. [HUMAN]** `LexicalOcrSubsetVerifier` (deterministic, §5.4) + `VisualEvidenceVerifier` protocol + `VerifierVerdict`; `verify_visual_primary_evidence` quorum logic (lexical mandatory and non-counting; ≥2 distinct-**family** pixel verifiers per the canonical A4 rule §0.5-A4, with the attested same-family escape; fail-closed on no-crop/timeout/dissent); verdict cache + `max_regions_verified_per_answer`. Files: new `src/raku_rag/manufacturing/safety/visual_verify.py`, `services/answer.py`. Gate: G-Ground unit tests (promote only on full quorum; caption/empty-OCR/vlm-source never promote).
- **F3. [HUMAN]** Hook 0 pre-filter in the overlay: extend `_should_answer_from_approved_lookup_evidence` (or parallel high-risk branch) → `_PreselectedRetrieval` restricted to approved+effective for ALL high-risk queries. Files: `src/raku_rag/manufacturing/api/answer_ext.py`. Gate: draft/obsolete crop never reaches the generator (test).
- **F4. [HUMAN]** Hook 2: `ManufacturingCitation` + `from_base` copy `asset_id/region_id/page_number/pixel_derived/visual_evidence_verified/visual_verifier_verdicts`; `_admissible` gates `pixel_derived` on `visual_evidence_verified` (`answer_ext.py:360-372`); **re-evaluate on read**. Files: `answer_ext.py`. Gate: G-Ground + enumerate-all-`structured_kind`s no-bypass test.
- **F5. [HUMAN]** Audit: `record_answer_decision(..., extra_client_metadata=...)` merge (`audit.py:36-98`); `manufacturing/app.py:802-819` passes `visual_evidence` (promoted AND denied); recurse `sanitize_audit_log_entry` into `client_metadata` (`domain/audit.py:177-183`,`:301`). Files: `manufacturing/api/audit.py`, `manufacturing/app.py`, `manufacturing/domain/audit.py`. Gate: payload-has-no-OCR/caption/crop-bytes test + denied-promotion-audited test.

### Epic G — Verifier providers, observability, eval (depends on F)
- **G1. [HUMAN]** Wire `visual_evidence_verifier_providers` to **distinct provider families** (Bedrock Claude + Vertex Gemini by default; two same-family model ids only when `visual_verifier_allow_same_family_distinct_models=true`, attested) via a `vlm_from_settings`-style multi-provider factory; confirm the IAM grants cover every configured verifier; document degraded-mode residual risk (§0.5-A4/§5.5). Files: `providers/vlms/__init__.py`, `infra/cdk/lib/raku-rag-stack.ts`. Gate: G-Pol per verifier.
- **G2.** cost_records cardinality (one row per `async_job` at completion + page count; `bedrock_vision_caption`; `bedrock_vision_verify`); metrics §6.7; caps as enforced Settings. Files: `workers/ingestion.py`, `services/answer.py`, `eval/`. Gate: Tier-B cost-attribution test.
- **G3.** Eval items: structured-region `expected_evidence` + `visual_grounding_subset_rate` hard min (`eval/runner.py`, `eval/baseline.py`). Files: `src/raku_rag/eval/`. Gate: baseline min/max blocks regressions.

### Epic H — Backfill (depends on E, F) — gated GA
- **H1.** Stamp `VisualAsset.metadata["extractor_version"]` (D2) so staleness is detectable.
- **H2. [HUMAN]** Backfill script: enumerate `Document.metadata` `content_type ∈ {application/pdf, image/*}` lacking visual assets at the current `extractor_version`; re-enqueue through the visual worker with the E5 replace semantics; bulk cost ceiling + concurrency cap + idempotent resumability (skip already-current). Run as in-VPC RunTask (mirror `MigrateSeedTask`, `raku-rag-stack.ts:851-874`). Files: new `scripts/backfill_visual.py`, `infra/cdk/lib/raku-rag-stack.ts`. Gate: dry-run cost estimate + resumability test before any live run.

**Critical path:** A → B → (C ∥ D) → E → F → G → H. Safety promotion (Epic F) MUST NOT ship until F1–F5 land together with G-Ground green; until then visual evidence is reference-only (`visual_evidence_promotion=False`), which is the safe default and keeps every prior 002 guarantee intact.
