# Ingestion — Parsers, Cell Anchors, and Approval Metadata

The manufacturing ingestion path **reuses the 001 ingestion pipeline** (parse → chunk → embed →
index) and adds two things: multi-format parsing (DOCX/XLSX/CSV) behind the 001 `Parser` abstraction,
and the attachment of `ManufacturingDocumentMetadata` (manufacturing tags + approval metadata) to the
already-persisted 001 `Document` / `Chunk` objects.

## Parsers (`src/raku_rag/providers/parsers.py`)

`ManufacturingSystem` wires a `CompositeParser([TextParser(), DocxParser(), SpreadsheetParser()])`
into its own `IngestionService`. 001's `TextParser` alone rejects OOXML types, so the composite is
used for the manufacturing path. Content types (mirrored in `app.py._EXT_CONTENT_TYPE`):

- `DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"`
- `XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"`
- `text/csv`, `text/plain`, `text/markdown`, `text/html`

### `DocxParser`

Extracts **both** body paragraphs and **table-cell** content so a citation can be grounded in tabular
data. Table rows are joined cell-by-cell (`" | ".join(...)`) into normalized text.

### `SpreadsheetParser` — the `sheet!R{row}C{col}` cell anchor (FR-MFG-002)

XLSX is read via `openpyxl`; CSV via the stdlib `csv` module (CSV has no sheet name, so a stable
logical sheet name `"sheet1"` is used for the anchor).

The anchor convention (header row = R1, rows/cols **1-based**):

- `cell_anchor(sheet, row, col) -> "{sheet}!R{row}C{col}"` builds the canonical token.
- `parse_cell_anchor(text) -> (sheet, row, col) | None` extracts the first such token back out.

Every **non-empty data cell** (rows below the header) becomes its own `\n\n`-delimited block of the
form `"{sheet}!R{row}C{col} {header}: {value}"`. One cell per block means the `SentenceChunker` yields
**one chunk per cell**, so a citation resolves to a single cell and distinct cells resolve to distinct
anchors. The leading anchor token preserves the exact coordinate through the 001
chunk/citation/offset path; the manufacturing search overlay parses the anchor back out to expose the
cell coordinate.

## Chunking profiles (`providers/chunkers.py`)

The reused 001 `SentenceChunker` remains the default, but it is now metadata-aware for manufacturing
ingest. When `ManufacturingDocumentMetadata.document_kind` is available, ingestion calls
`chunk_document(...)` and records the selected `chunking_profile`, `max_chunk_chars`, and
`chunk_overlap_chars` on both `Document.metadata` and `Chunk.metadata`.

Current local profiles:

- `work_instruction`: 520 chars with 80-char overlap.
- `inspection`: 460 chars with 60-char overlap.
- `quality_report` / `trouble_report`: 700 chars with 100-char overlap.
- `minutes`: 560 chars with 60-char overlap.
- `ledger`: 360 chars with 40-char overlap.
- `drawing`: 320 chars with no overlap.
- `training`: 600 chars with 80-char overlap.

The plain `chunk(text)` method keeps its prior no-overlap behavior for existing callers and tests.

## Metadata model (`domain/metadata.py`)

`ManufacturingDocumentMetadata` is a stdlib `@dataclass` stored in the 001 `Document.metadata` /
`Chunk.metadata` JSON. It carries `tenant_id` (the hard isolation boundary) + `document_id` (FK into
the 001 Document). Field groups:

- **Manufacturing tags**: `equipment`, `model_no`, `alarm_code`, `defect_type`, `process`, `part_no`,
  `customer` (high-sensitivity, ACL-relevant), `document_kind` (`DocumentKind`).
- **Entity FKs**: `process_id`, `equipment_id` (used by both ACL mapping and the high-risk classifier).
- **Safety / quality classification tags** (HighRiskClassifier input): `safety_category`,
  `quality_category`, `equipment_operation_category`, `hazard_tags`.
- **Regulation / standard anchors**: `regulation_refs` carries explicit review anchors such as
  `ISO_12100_2010`, `JIS_B_9700_2013`, `ISO_45001_2018`, or `JP_ISHA`. The helper catalog in
  `domain/regulations.py` can infer likely review anchors from safety/quality/hazard metadata; this is
  an SME review aid, not a legal-compliance decision.
- **Approval metadata**: `approval_status` (`ApprovalStatus`), `effective_date` (ISO date),
  `approved_by`, `approved_at`, `obsolete_at`, `superseded_by`, `approval_source` (`ApprovalSource`).

Enums:

- `DocumentKind`: `work_instruction` / `inspection` / `quality_report` / `trouble_report` /
  `minutes` / `ledger` / `drawing` / `training`.
- `ApprovalStatus`: `draft` / `pending_review` / `approved` / `obsolete`.
- `ApprovalSource`: `imported` (upstream is source of truth) / `workflow` (this layer's flow).

## Enrichment (`ingestion/metadata_enrichment.py`)

`MetadataEnricher` decorates the **already-persisted** 001 objects — it defines **no new store**:

- `attach(tenant_id, document_id, metadata)` stashes the metadata on `Document.metadata` under
  `MFG_META_KEY = "_mfg_meta"` and calls `propagate_to_chunks(...)`. A cross-tenant attach (metadata
  `tenant_id` ≠ document `tenant_id`) raises `TenantIsolationError`.
- `propagate_to_chunks(...)` writes the same metadata reference onto every indexed
  `Chunk.metadata["_mfg_meta"]` so the 001 metadata-filter path and the HighRiskClassifier / SafetyGate
  can read it without a second lookup (FR-MFG-003). Returns the chunk count.

The `ManufacturingSystem` also keeps a fast resolver map `self._mfg_meta: dict[(tenant_id, document_id) ->
metadata]`, read by search / answer / classifier / gate via `get_mfg_meta(...)`.

## Ingestion entrypoints (`app.py`)

- `ingest_manufacturing(*, tenant_id, collection_id, document_id, text, metadata, source_id="src")`
  — calls `self._mvp.ingest_text(...)`, attaches the metadata to the Document + resolver map,
  `propagate_to_chunks(...)`, then audits the ingest (`_audit_ingest`, action
  `ingest.parse_metadata`, reference IDs only).
- `ingest_manufacturing_file(*, ..., path, content_type=None, metadata, source_id="src")` — reads the
  file bytes, routes by extension / `content_type` to the right 001 `Parser` (dispatched by the
  CompositeParser), runs parse → chunk → embed → index via `self._ingestion.ingest(...)`, attaches
  metadata via `self._enricher.attach(...)`, and audits the parse. An unsupported extension raises
  `ValueError`.

## Approval lifecycle (`ingestion/approval.py`)

`ApprovalWorkflow` has two responsibilities:

1. **Lightweight workflow** — `transition(tenant_id, document_id, to_status, actor)` drives
   `draft → pending_review → approved → obsolete`. It updates the same
   `ManufacturingDocumentMetadata` the reused 001 path reads and sets `approval_source = workflow`.
   On a workflow `approved` with no explicit `effective_date`, today's date is set so the document
   becomes a valid approved+effective citation (an already-set future window is preserved). Approval
   stamps `approved_by` (the actor) and `approved_at`; obsolete stamps `obsolete_at`.

2. **Imported approval = source of truth** — `import_external(tenant_id, document_id, external, actor)`
   imports an upstream approval, sets `approval_source = imported`, and **overrides** whatever state
   the lightweight workflow reached (e.g. an imported `approved`+effective approval wins even after the
   local workflow marked the doc `obsolete`). FR-MFG-004a.

Both paths persist via `_persist`, which re-decorates the Document + indexed Chunks through the
`MetadataEnricher` so search/answer immediately read the new approval state. **Every** transition and
every external import is recorded to the shared `AuditLogWriter` with reference IDs only (action
`approval.transition` / `approval.import_external`), never body text — FR-MFG-021.

`ManufacturingSystem` exposes these as `transition_approval(...)` and `import_external_approval(...)`,
both returning an `ApprovalState`.
