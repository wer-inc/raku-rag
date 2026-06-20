# Safety Gating, Drafts, and Trouble Cases

This is the heart of the solution-layer hard rules: **high-risk answers require an approved+effective
citation or assert nothing**, **AI output is always a draft requiring human review**, and **past-case
countermeasures are shown only as candidates/reference**.

## High-risk classification (`safety/classifier.py`)

`RuleHighRiskClassifier` is a 3-stage cascade with OR-logic and a fail-safe default ("迷えば
high-risk"). Its `classify(query, candidate_metadata, intent_hint=None) -> HighRiskClassification`:

1. **METADATA stage** (`_metadata_reason_codes`) — any candidate document carrying a non-empty
   `safety_category` / `quality_category` / `equipment_operation_category` / `process_id` /
   `equipment_id` (the `_HIGH_RISK_METADATA_FIELDS` set), or `hazard_tags`, marks the query high-risk.
2. **RULE + KEYWORD stage** (`_intent_reason_codes`) — the lower-cased query plus the optional
   structured `intent_hint` is matched against `_INTENT_KEYWORDS` (bilingual EN/JA): `equipment_stop`,
   `disassembly`, `electric_shock`, `high_temp`, `pressure`, `chemical`, `heavy_object`,
   `safety_device`, `quality_judgment`, `shipment_decision`, `customer_impact`, `corrective_action`.
3. **AMBIGUOUS tie-break (LLM only here)** — only when stages 1+2 found nothing **and** the query is
   `intent_hint == "ambiguous"` or too terse (`< _AMBIGUOUS_MIN_TOKENS = 3` content tokens) does it
   consult the reused 001 `LLMProvider` to try to **rule danger out**. `_llm_rules_danger_out`
   returns `True` only on a confident `SAFE` verdict; any uncertainty / no LLM / provider error →
   `False` → still flagged high-risk.

Any stage firing ⇒ `is_high_risk=True` (OR). The result carries `reason_codes` (the labels that
fired) and the `classification_source` of the **first** stage that fired (`metadata` > `keyword` >
`llm`/`rule`), so audit/telemetry can attribute the decision. The classifier only **labels** the
query; the SafetyGate enforces the citation requirement.

## SafetyGate (`safety/gate.py`)

`ManufacturingSafetyGate` runs **after** the 001 `GroundednessGate` — it is an overlay stage, not a
new security mechanism. `evaluate(classification, candidate_citations, candidate_metadata) ->
SafetyDecision`:

- Effectiveness predicates: `is_effective(effective_date, today=...)` is `True` iff the date is set
  and **not in the future** (missing/malformed → invalid, fail-safe). `is_approved_effective(meta,
  today=...)` is `True` iff `approval_status == APPROVED` **and** the effective date is valid.
- **HIGH-RISK + no approved+effective citation** ⇒ `blocked=True`,
  `safety_block_reason=APPROVED_CITATION_MISSING`, `requires_onsite_confirmation=True`. The answer
  becomes `insufficient_evidence` and must not assert (FR-MFG-005, SC-MFG-006).
- **NON-high-risk**: the approved-citation requirement does **not** apply; only draft/obsolete are
  excluded as primary evidence. If the **only** candidate evidence is draft/obsolete (`has_usable_primary`
  is `False`), the gate blocks with `INSUFFICIENT_EVIDENCE` (FR-MFG-006, SC-MFG-011). Approved /
  pending_review / unclassified evidence is a usable primary basis.
- **Obsolete** evidence among candidates ⇒ `obsolete_warning=True`; obsolete is never primary evidence.
- `requires_onsite_confirmation` is `True` for any high-risk answer (FR-MFG-007).
- `approval_status_at_use` records the status of the evidence actually relied upon.

`normalize_block_reason(*reasons)` collapses several applicable reasons to a single highest-priority
code in order `approved_citation_missing → insufficient_evidence → other_block` (FR-MFG-030). The
value objects (`SafetyBlockReason`, `SafetyDecision`, `HighRiskClassification`, `ClassificationSource`)
live in `domain/safety.py`.

### Answer-path integration (`api/answer_ext.py`)

`ManufacturingAnswerService.answer(...)` orchestrates the reused 001 services and the overlay:

1. Retrieve via 001 `RetrievalService` (ACL pre-filter already applied), then apply
   `manufacturing_filters` as a candidate **post**-filter (`_matches_filters`) — never weakening ACL.
2. Pre-gate via 001 `GroundednessGate`; resolve each candidate's metadata.
3. Classify high-risk; run the SafetyGate.
4. If blocked ⇒ return `insufficient_evidence` with the normalized `safety_block_reason`, **empty
   text, empty used_chunks** (FR-MFG-005).
5. Otherwise run the reused 001 `AnswerService` and decorate citations with approval provenance
   (`ManufacturingCitation`: `approval_status` / `effective_date` / `approval_source`).

There is one extra safety check (the **T066 capstone** glue, tested by `test_obsolete_draft_evidence.py`):
when 001 returns `ok` but the **primary (top) citation is obsolete** and **no** approved+effective doc
is among the actually-cited evidence, the answer is **demoted** to `insufficient_evidence` with
`obsolete_warning=True` (reference-only). This closes the multi-doc gap the single-doc pre-gate misses
(an unrelated approved doc satisfies `has_usable_primary` even though 001 still ranks the obsolete doc
#1).

The result is a `ManufacturingAnswer` (additive over the 001 `Answer`): adds `high_risk`,
`high_risk_reason_codes`, `safety_block_reason`, `obsolete_warning`, `requires_onsite_confirmation`,
`notice` (the on-site confirmation notice when applicable).

## Drafts — draft-only + reviewer workflow (US4)

### `DraftArtifact` (`domain/draft.py`)

The default `status` is `DraftStatus.DRAFT` (the central safety invariant). Enums: `DraftType`
(`checklist` / `trouble_report` / `quality_report` / `training` / `faq`), `DraftStatus`
(`draft` / `in_review` / `approved` / `rejected` / `archived`), `CreatedBy` (`ai` / `user`). State
machine: `draft → in_review → approved | rejected | archived ; draft → archived`.

### `DraftGenerator` (`drafts/generator.py`)

`generate(...)` **always** returns `status=DraftStatus.DRAFT` and `created_by=CreatedBy.AI` — Hard
Rule 1. It never auto-approves and never sets reviewer fields. Content is built safe-side:

- Provenance: union of citation `document_id`s + explicitly-passed `source_document_ids` (ordered,
  de-duped); `source_citations` are string refs to the 001 citations.
- Unconfirmed items (caller hypotheses with no citation) are **marked** `confirmed=False` /
  `status="needs_review"`, not asserted as fact.
- A **safety** item is only `confirmed=True` when backed by an approved+effective citation — decided
  by **reusing** `safety.gate.is_approved_effective` (FR-MFG-005). Without such evidence the item is
  held back (`status="needs_review"`, `requires_approved_evidence=True`).

### `ReviewWorkflow` (`drafts/review.py`)

Operates on the **stored** artifact (the system of record) — it never trusts a status set on a
detached copy. `assign(...)` moves `draft → in_review` and records who must review (single
`reviewer_id` or `reviewer_group`) + `assigned_at`. `decide(...)` records a reviewer decision; valid
decisions are `approved` / `rejected` / `archived`.

**The only path to `approved` is an explicit, attributable human reviewer action** (SC-MFG-007):
`decide(..., decision="approved")` with `reviewer is None` or no `reviewer.user_id` raises
`PermissionError` and the artifact stays `draft`. `created_by=ai` is provenance and is never rewritten
by an approval — the approval is attributed to the reviewer. Single reviewer / group only — no
multi-stage approval, no e-signature. All transitions are audited.

## Trouble cases — Hard Rule 4 (US3, `knowledge/trouble_cases.py`)

`TroubleCaseRetriever.find_similar(...)` finds similar past `TroubleCase` records via the reused 001
`RetrievalService` (deny-by-default ACL **pre-filter**) — it builds **no new authorization or
retrieval mechanism**. The knowledge graph (`InMemoryTroubleCaseStore`) keys each case by its source
001 `Document` id (the ACL anchor); a chunk that survives the 001 pre-filter is resolved back to its
case via that FK, so a confidential case the principal cannot read is excluded **before** any cosine
score (extends SC-MFG-008).

**Hard Rule 4** is enforced by `normalize_countermeasure` / `split_countermeasures`. A countermeasure
has two independent axes:

- `measure_class` (the **nature** axis: `provisional` / `permanent` / `unknown`) is **preserved** as
  stored; provisional and permanent are returned in **separate** buckets (`unknown` lands in neither).
- `type` (the **display / evidence** axis) is forced to `CountermeasureType.CANDIDATE` for any
  past-case measure — a past-example, **never** a definitive work instruction — **even when**
  `measure_class=permanent`. A human-readable `label = "過去事例に基づく候補・参考"` reinforces this
  and must not read as an official/definitive work order.

`ManufacturingSystem` exposes `register_trouble_case(...)` (ingests the report body via the reused 001
ingestion path so it is ACL-pre-filtered, then registers the graph) and `search_trouble_cases(...)`
(audited; returns a `TroubleCaseSearchResponse`).
