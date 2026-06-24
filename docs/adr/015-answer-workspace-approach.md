# ADR-015: Manufacturing Answer Workspace (015) — Image Hazard Evaluation Approach

- **Status**: Accepted (design-convergence spike / Goal 0 — implementation deferred to Goal 1)
- **Date**: 2026-06-22
- **Branch**: `015-mfg-answer-workspace-poc`
- **Seed**: `memo.txt` (untracked) — "画像の評価システム / 質問回答票を作る"
- **Scope of this ADR**: freeze the *approach*, the *model*, and the *reuse boundary* so the implementation
  loop has a machine-evaluable target. **No endpoint / UI / code is written in this spike.**
- **Related**: `adr.md` (ADR-001..006, base/industry layering & no-LangChain critical path),
  `docs/decisions/ADR-016-canonical-layout.md`, frozen contract `contracts/answer-sheet.schema.json`,
  hard rules in `CLAUDE.md` (§Active Feature 002), `specs/001-rag-platform` (visual-RAG US6),
  `specs/002-manufacturing-field-knowledge-rag`.

---

## Context

`memo.txt` sketches a new manufacturing capability: a field user submits a photo and gets a
**質問回答票 (answer sheet)** — *where is the hazard, what to do, the improvement, the legal basis, and an
OK / 一部OK / NG / 要確認 verdict*. The memo ends with an unresolved design fork: **「画像をどうやって
学習させるか？」 (how do we train on the images?)**.

Treated literally, "training on images" turns 015 into an open-ended ML data-collection project with no
convergence condition — it cannot be run as an implementation loop. The audit that produced this branch's
goal already classified 015 as **③ new / not-started**, distinct from the wiring gaps (① / ②) whose backend
contracts are fixed. The purpose of this ADR is to **reframe the fork so 015 collapses into an ordinary
vertical slice**, then freeze the contract that makes that slice machine-verifiable.

---

## Decision

### D1 — Approach: multimodal reasoning + regulation retrieval + structured output (NOT training)

We do **not** train or fine-tune an image model. We treat the answer sheet as a **multimodal reasoning +
retrieval + structured-output** problem:

1. **Ingest the image** through the existing 001 visual pipeline (EXIF strip → OCR → layout regions →
   optional caption → visual embeddings) — reuse, see **D3**.
2. **Detect hazards** by passing the image + its OCR/layout regions to a **vision-capable Claude on
   Bedrock** (the model *reasons over the picture*; it is not trained on a hazard corpus) — see **D2**.
3. **Ground each hazard in regulation** by querying the existing 001 retrieval over the tenant's approved
   regulation/standard corpus (`RetrievalService` + manufacturing filters). The **legal basis is a real
   retrieved, approved+effective citation**, never a model-recalled statute — this is what makes the
   answer auditable (Constitution I Groundedness, II Traceability).
4. **Compose a structured AnswerSheet** (hazard / improvement / legal_basis[] / verdict ∈
   {OK,PARTIAL,NG,NEEDS_CHECK}) validated against the frozen `contracts/answer-sheet.schema.json`.
5. **Keep the human in the loop**: the sheet is an AI **draft** (Hard Rule: AI output is always draft); a
   high-risk finding with no approved+effective citation is **blocked / NEEDS_CHECK**, not asserted
   (reuse `ManufacturingSafetyGate`).

**No-train posture (answers the literal fork).** Because we do not learn weights, "how to train on images"
becomes "we don't"; correctness comes from reasoning + cited regulation. The Bedrock provider must also be
configured under the existing **no-train governance** (`no_train_default`, `provider_no_train_required` in
002 governance) — i.e. the model provider must not train on our images/queries either.

#### Rejected alternatives

- **A1 — Train/fine-tune a custom hazard-image classifier** (the literal reading of the memo fork).
  *Rejected*: no labeled in-domain corpus; slow, brittle, per-customer retraining; a learned weight is not a
  citable legal basis, so it fails Groundedness/Traceability and the high-risk approved-citation hard rule;
  no convergence condition for an implementation loop.
- **A2 — Caption-then-text-RAG only** (use the generated caption as the primary evidence and run text RAG).
  *Rejected*: violates **FR-048** — captions are a retrieval aid, **not** primary evidence
  (`src/raku_rag/providers/vlms/__init__.py` docstring); also discards spatial grounding (no
  `evidence_region`).
- **A3 — Pure rules / classical-CV heuristic hazard detector.** *Rejected as the primary path*: brittle,
  non-generalizable, high build cost. Retained only as an **offline deterministic default** (the existing
  `ExtractiveVLMProvider`) so the Tier-A gate stays stdlib-only and fast (Track A).

### D2 — Model: vision-capable Claude on Bedrock via the **Japan cross-region inference profile**

- **Primary model**: a vision-capable Claude **Sonnet** on Amazon Bedrock, invoked through the **Japan geo
  cross-region inference (CRIS) profile** for in-Japan data residency. Concrete profile id:
  **`jp.anthropic.claude-sonnet-4-5-20250929-v1:0`** — the `jp.` geo profile routes only to
  `ap-northeast-1` (Tokyo) and `ap-northeast-3` (Osaka), so customer images never leave the Japan geo.
  (Source: AWS, *"Introducing Amazon Bedrock cross-Region inference for Claude Sonnet 4.5 and Haiku 4.5 in
  Japan and Australia"*.)
- **Helper/classification tasks** (intent/keyword disambiguation, summarization) use a Haiku-class Claude on
  the same Japan profile (`jp.anthropic.claude-haiku-4-5-…`), matching the repo's existing
  Sonnet-for-final / Haiku-for-helper split in `apps/api/src/llm/bedrock-claude.service.ts`
  (`DEFAULT_BEDROCK_CLAUDE_SONNET_MODEL_ID`, `DEFAULT_BEDROCK_CLAUDE_HAIKU_MODEL_ID`).
- **Integration point**: implement the **existing** `VLMProvider` interface
  (`src/raku_rag/interfaces/base.py:109-110`, `generate(query, *, visual_regions)`) with a Bedrock-backed
  provider. The deterministic `ExtractiveVLMProvider` stays the offline/test default (pluggable per
  Constitution IV / ADR-006). Model id is read from env (same pattern as `BEDROCK_CLAUDE_SONNET_MODEL_ID`),
  `anthropic_version = "bedrock-2023-05-31"`, image passed as a Converse/`invokeModel` image content block.
- **Non-Japan / dev fallback**: the repo's current bare id `anthropic.claude-sonnet-4-6` (no geo prefix) is
  the non-residency fallback; production in Japan pins the `jp.` profile. If/when a `jp.` profile for a
  newer Sonnet (e.g. `sonnet-4-6`) is published, prefer the latest while preserving residency.

### D3 — Reuse boundary: 001 visual-RAG/manufacturing overlay vs. new 015 build

**REUSE (exists today — call, do not rebuild):**

| Capability | Anchor |
| --- | --- |
| Image ingest (EXIF strip → OCR → layout → caption → visual embed) | `VisualIngestionExecutor` `src/raku_rag/workers/ingestion.py` |
| Image → visual chunks (bbox / crop_uri / ocr_text) | `visual_chunks_from_ingestion()` `src/raku_rag/services/visual.py` |
| OCR / layout abstractions | `OcrEngine`, `LayoutExtractor` `src/raku_rag/interfaces/base.py:91-96` |
| Spatial grounding types | `BoundingBox`, `LayoutRegion`, `VisualCitation`, `Citation(kind=visual)` `src/raku_rag/domain/models.py:143-203` |
| Retrieval + groundedness + answer | `RetrievalService`, `GroundednessGate`, `AnswerService` `src/raku_rag/services/{retrieval,groundedness,answer}.py` |
| Manufacturing overlay (high-risk gate, approval provenance, audit/telemetry) | `ManufacturingAnswerService`, `HighRiskClassifier`, `ManufacturingSafetyGate`, `ManufacturingCitation` `src/raku_rag/manufacturing/...` |
| VLM abstraction + offline default | `VLMProvider` `interfaces/base.py:109-110`; `ExtractiveVLMProvider` `providers/vlms/__init__.py` |
| **No new ACL/tenancy** | all visual chunks/assets/regions inherit `tenant_id` pre-filter |

**BUILD NEW (no equivalent today — Goal 1 work):**

| New piece | Why new |
| --- | --- |
| Bedrock vision `VLMProvider` implementation | production model behind the existing interface (**D2**) |
| `HazardImageAnalyzer` — image+regions → hazard findings | no "find hazards in an image" capability exists |
| Hazard → regulation query construction | hazard-specific retrieval intent over the regulation corpus |
| AnswerSheet verdict composer (OK/PARTIAL/NG/NEEDS_CHECK) | no image→hazard→regulation→verdict formatter exists |
| `POST /v1/manufacturing/answer-workspace/evaluate` endpoint + UI | no image-evaluation route/screen exists |
| Fixtures `tests/fixtures/hazard-sample.*` + contract test | Goal 1 verifier (authored from this frozen schema) |

---

## memo.txt 未解決問い → 決定 対応表

Every question mark in `memo.txt` (5 total: ？×4, ?×1) maps to a frozen decision line or contract field.
**Unreferenced questions = 0.** (Gate: `count([?？] in memo.txt) == count(MEMO-Q rows here)`.)

| # | memo.txt の問い (原文) | 回答（凍結された決定） | 参照 |
| --- | --- | --- | --- |
| MEMO-Q1 | どこか危険？ | 画像+OCR領域を vision Claude で多モーダル推論し、危険箇所を `evidence_region`(bbox) 付きで列挙。 | D1 / D2 / `AnswerSheet.items[].hazard` + `evidence_region` |
| MEMO-Q2 | 何をすればいい？ | 各危険に対する是正アクションを構造化出力する。 | D1 / `AnswerSheet.items[].improvement` |
| MEMO-Q3 | 改善案は? | 同上 — improvement フィールドが「改善案」を担う(MEMO-Q2 と同一決定)。 | D1 / `AnswerSheet.items[].improvement` |
| MEMO-Q4 | その根拠は？ | 根拠は**学習済み重みではなく**、001 retrieval で取得した承認済み・有効な規程引用(法令+条+citation)。高リスクで承認引用が無ければ NG/NEEDS_CHECK でブロック。 | D1 / `AnswerSheet.items[].legal_basis[]{law,article,citation}` / `verdict` |
| MEMO-Q5 | 画像をどうやって学習させるか？ | **学習しない。** 多モーダル推論+規程リトリーバル+構造化出力に置換(D1)。モデルは Bedrock の Japan CRIS vision Claude(D2)で、no-train ガバナンス下で運用。 | D1(却下案A1) / D2 |

---

## Non-goals (this spike)

- No endpoint, UI, provider implementation, code generation, or dependency additions.
- No "nice-to-have" schema expansion — the contract is frozen at the **minimum** needed for Goal 1.
- Audit-export / policy-management / KB-browse screens (audit ① / ②) are out of 015 scope.

## Convergence gate (self-run; see commit/report)

1. `contracts/answer-sheet.schema.json` parses as JSON and carries the required keys
   (`$defs.AnswerSheetRequest` ⊇ {image_ref, collection_id}; `$defs.AnswerSheet` ⊇
   {items, overall_verdict, trace_id}; `$defs.AnswerSheetItem` ⊇ {hazard, improvement, legal_basis,
   verdict}; `Verdict.enum == [OK,PARTIAL,NG,NEEDS_CHECK]`).
2. `count([?？] in memo.txt) == count(MEMO-Q rows in this ADR)` (== 5).

## Consequences

- 015 is now an ordinary vertical slice with a machine-checkable target (Goal 1 can converge).
- The frozen schema is the **single source** from which the Goal-1 contract test (verifier) is authored —
  authored on a path separate from the implementation, preserving verifier-authoring separation.
- Data residency is a first-class model decision (Japan CRIS), consistent with manufacturing customers'
  expectations; the provider stays pluggable so the deterministic default keeps the Tier-A gate fast.
