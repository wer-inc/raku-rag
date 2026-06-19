"""T034–T036 — Similar-trouble-case retrieval (US3; FR-MFG-008/009, Hard Rule 4).

Find SIMILAR past ``TroubleCase`` records for a symptom query and assemble each with its FailureMode
(cause), its Countermeasures (split provisional vs permanent), its recurrence-prevention note and the
001 citations of the source report — on top of the 001 base platform.

This module builds **NO new authorization or retrieval mechanism**:

  * Retrieval is the reused 001 :class:`~raku_rag.services.retrieval.RetrievalService`, which applies
    the deny-by-default ACL/tenant/tombstone **PRE-filter** inside ``InMemoryVectorStore.search``
    BEFORE scoring. The symptom query is embedded and matched against the SAME chunks ingested for
    every other 002 endpoint, so a confidential TroubleCase whose source document the principal cannot
    read is excluded before any cosine score is computed (FR-MFG-008, extends SC-MFG-008). Visibility
    is provisioned through the US6 ``acl_mapping.grant_scope`` / ``apply_scope`` seam — there is no
    parallel authz path here.

  * The knowledge graph (TroubleCase <-> FailureMode <-> Countermeasure <-> source Document) is the
    Phase-2 reference layer. ``InMemoryTroubleCaseStore`` keys each TroubleCase graph by its source
    001 ``Document`` id; a chunk that survives the 001 pre-filter is resolved back to its TroubleCase
    via that source-document FK, so the case is visible to a principal IFF the principal can read its
    source document under the 001 ACL. No bespoke unfiltered scan of the graph.

T036 — Countermeasure 2-axis display normalization (Hard Rule 4, FR-MFG-009). A Countermeasure carries
two INDEPENDENT axes (data-model §D):

  * ``measure_class`` — the NATURE axis (provisional 暫定 / permanent 恒久 / unknown). PRESERVED as
    stored; provisional and permanent are returned in SEPARATE buckets (G4 / FR-MFG-008).
  * ``type`` — the DISPLAY / evidence axis (reference / candidate). A countermeasure sourced from a
    PAST TroubleCase is ALWAYS normalized to ``candidate`` — a past-example, never a definitive work
    instruction — EVEN WHEN ``measure_class=permanent``. A human-readable ``label`` marks it as a
    past-example candidate and never reads as an official/definitive work order.

stdlib only. Authoritative: spec FR-MFG-008/009; Hard Rule 4; quickstart S5; contracts/mfg-openapi.md
§C; contracts/mfg-interfaces.md §5; data-model §D.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from raku_rag.domain.models import IdentityClaims, QueryProfile, ScoredChunk
from raku_rag.manufacturing.domain.entities import (
    Countermeasure,
    CountermeasureType,
    FailureMode,
    MeasureClass,
    TroubleCase,
    TroubleCaseResult,
)
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.services.retrieval import RetrievalService

GetMfgMeta = Callable[[str, str], ManufacturingDocumentMetadata | None]
GetDocument = Callable[[str, str], object]

# The human-readable past-example label applied to every displayed countermeasure (contracts §C).
# It MUST NOT read as a definitive / official work instruction (Hard Rule 4 mechanism check).
PAST_CASE_LABEL = "過去事例に基づく候補・参考"


# ================================================================================================
# Knowledge-graph store (T034): TroubleCase <-> FailureMode <-> Countermeasure <-> source Document.
# ================================================================================================
@dataclass
class _TroubleCaseRecord:
    """One past TroubleCase graph, keyed by its source 001 Document id (the ACL anchor)."""

    trouble_case: TroubleCase
    failure_mode: FailureMode | None = None
    countermeasures: tuple[Countermeasure, ...] = ()
    recurrence_prevention: str | None = None


class InMemoryTroubleCaseStore:
    """Tenant-scoped in-memory persistence for the manufacturing knowledge-graph relations (T034).

    Mirrors the other in-memory 002 stores (DraftService store, ``_mfg_meta``). A TroubleCase graph is
    registered together with the 001 Document that backs it; visibility is NOT decided here — it is
    decided by the 001 ACL pre-filter over that source document. This store only resolves a
    pre-filtered, ACL-visible source-document id back to its TroubleCase graph.
    """

    def __init__(self) -> None:
        # (tenant_id, source_document_id) -> graph record (the source doc is the ACL anchor).
        self._by_document: dict[tuple[str, str], _TroubleCaseRecord] = {}
        # (tenant_id, trouble_case_id) -> graph record (for direct lookup / de-dup by case).
        self._by_case: dict[tuple[str, str], _TroubleCaseRecord] = {}

    def register(
        self,
        *,
        tenant_id: str,
        source_document_id: str,
        trouble_case: TroubleCase,
        failure_mode: FailureMode | None = None,
        countermeasures: tuple[Countermeasure, ...] = (),
        recurrence_prevention: str | None = None,
    ) -> None:
        record = _TroubleCaseRecord(
            trouble_case=trouble_case,
            failure_mode=failure_mode,
            countermeasures=tuple(countermeasures),
            recurrence_prevention=recurrence_prevention,
        )
        self._by_document[(tenant_id, source_document_id)] = record
        self._by_case[(tenant_id, trouble_case.trouble_case_id)] = record

    def resolve_by_document(
        self, tenant_id: str, document_id: str
    ) -> _TroubleCaseRecord | None:
        return self._by_document.get((tenant_id, document_id))


# ================================================================================================
# Display shapes returned to the API layer (contracts §C res 200).
# ================================================================================================
@dataclass(frozen=True)
class DisplayCountermeasure:
    """A countermeasure as displayed: nature axis preserved, display axis normalized (T036)."""

    measure_id: str
    description: str
    type: CountermeasureType  # display/evidence axis (always candidate for a past-case measure)
    measure_class: MeasureClass  # nature axis, PRESERVED (provisional|permanent|unknown)
    label: str  # past-example candidate label (never a definitive/official work order)


@dataclass(frozen=True)
class CountermeasureSplit:
    """provisional vs permanent kept on SEPARATE buckets (the measure_class axis; G4/FR-MFG-008)."""

    provisional: tuple[DisplayCountermeasure, ...] = ()
    permanent: tuple[DisplayCountermeasure, ...] = ()


@dataclass(frozen=True)
class TroubleCaseCitation:
    """001 citation fields + manufacturing approval provenance (contracts §C)."""

    kind: str
    document_id: str
    source_id: str
    version: int
    retrieval_score: float
    chunk_id: str | None = None
    text_range: tuple[int, int] | None = None
    approval_status: str | None = None
    effective_date: str | None = None
    approval_source: str | None = None


@dataclass(frozen=True)
class TroubleCaseMatch:
    """A similar past TroubleCase resolved with cause / split countermeasures / recurrence / cites."""

    trouble_case_id: str
    symptom: str
    equipment_id: str | None
    process_id: str | None
    failure_mode: FailureMode | None
    countermeasures: CountermeasureSplit
    recurrence_prevention: str | None
    citations: tuple[TroubleCaseCitation, ...]
    relevance_score: float = 0.0

    def to_result(self, trouble_case: TroubleCase, raw: tuple[Countermeasure, ...]) -> TroubleCaseResult:
        """Adapt to the Phase-2 :class:`TroubleCaseResult` interface shape (contracts §5)."""
        return TroubleCaseResult(
            trouble_case=trouble_case,
            failure_mode=self.failure_mode,
            countermeasures=raw,
            citation_ids=tuple(c.document_id for c in self.citations),
            relevance_score=self.relevance_score,
        )


@dataclass(frozen=True)
class TroubleCaseSearchResponse:
    """POST /v1/manufacturing/trouble-cases/search response envelope (contracts §C res 200)."""

    status: str  # "ok" | "insufficient_evidence"
    results: tuple[TroubleCaseMatch, ...] = ()
    correlation_id: str = ""


# ================================================================================================
# T036 — Countermeasure 2-axis display normalization (Hard Rule 4, FR-MFG-009).
# ================================================================================================
def normalize_countermeasure(cm: Countermeasure) -> DisplayCountermeasure:
    """Display a past-case countermeasure as candidate/past-example, preserving its measure_class.

    The NATURE axis (``measure_class``) is carried through UNCHANGED — a permanent (恒久) measure stays
    permanent. The DISPLAY axis (``type``) is forced to ``candidate`` so a measure that originates from
    a past TroubleCase is shown as a candidate / past-example and NEVER as a definitive work order,
    even when permanent (Hard Rule 4). The ``label`` reinforces the same: it marks the measure as a
    past-example candidate and must not read as an official/definitive instruction.
    """
    return DisplayCountermeasure(
        measure_id=cm.measure_id,
        description=cm.description,
        type=CountermeasureType.CANDIDATE,  # past-case => candidate display, never definitive
        measure_class=cm.measure_class,  # nature axis preserved (NOT overwritten)
        label=PAST_CASE_LABEL,
    )


def split_countermeasures(countermeasures: tuple[Countermeasure, ...]) -> CountermeasureSplit:
    """Split into the provisional vs permanent buckets (measure_class axis), normalizing each.

    Buckets are DISJOINT by ``measure_class``; an ``unknown`` measure_class lands in neither
    provisional nor permanent (the two named buckets stay clean — G4/FR-MFG-008).
    """
    provisional: list[DisplayCountermeasure] = []
    permanent: list[DisplayCountermeasure] = []
    for cm in countermeasures:
        display = normalize_countermeasure(cm)
        if cm.measure_class == MeasureClass.PROVISIONAL:
            provisional.append(display)
        elif cm.measure_class == MeasureClass.PERMANENT:
            permanent.append(display)
        # MeasureClass.UNKNOWN: not placed in either named bucket (kept off both axes).
    return CountermeasureSplit(
        provisional=tuple(provisional), permanent=tuple(permanent)
    )


# ================================================================================================
# T035 — TroubleCaseRetriever: 001 retrieval (ACL pre-filter) -> resolve graph -> assemble matches.
# ================================================================================================
class TroubleCaseRetriever:
    """Find similar past TroubleCases via the reused 001 retrieval + ACL pre-filter (FR-MFG-008).

    Implements the Phase-2 ``TroubleCaseRetriever`` contract (contracts/mfg-interfaces.md §5) with the
    richer display response. It does NOT scan the knowledge graph directly; it runs the symptom query
    through the 001 RetrievalService (deny-by-default PRE-filter), then resolves only the surviving,
    ACL-visible source documents back to their TroubleCase graph — so an unauthorized confidential case
    can never surface (its source chunk is dropped before scoring).
    """

    def __init__(
        self,
        *,
        retrieval: RetrievalService,
        store: InMemoryTroubleCaseStore,
        get_mfg_meta: GetMfgMeta,
        get_document: GetDocument | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._store = store
        self._get_mfg_meta = get_mfg_meta
        self._get_document = get_document

    def find_similar(
        self,
        principal: IdentityClaims,
        symptom_query: str,
        profile: QueryProfile,
        *,
        manufacturing_filters: dict | None = None,
    ) -> tuple[tuple[TroubleCaseMatch, ...], tuple[str, ...]]:
        """Return (matches, accessed_document_ids). Visibility is the 001 ACL pre-filter's decision."""
        tenant = principal.tenant_id
        # 001 retrieval — the ACL/tenant/tombstone PRE-filter runs inside store.search BEFORE scoring.
        scored: list[ScoredChunk] = list(self._retrieval.retrieve(principal, symptom_query, profile))

        matches: list[TroubleCaseMatch] = []
        accessed: list[str] = []
        seen_cases: set[str] = set()
        for s in scored:
            chunk = s.chunk
            meta = self._get_mfg_meta(tenant, chunk.document_id)
            # Optional candidate post-filter on manufacturing tags (NEVER weakens the ACL pre-filter).
            if not _matches_filters(meta, manufacturing_filters):
                continue
            record = self._store.resolve_by_document(tenant, chunk.document_id)
            if record is None:
                continue  # an ACL-visible chunk that is not a registered TroubleCase source
            case_id = record.trouble_case.trouble_case_id
            if case_id in seen_cases:
                continue
            seen_cases.add(case_id)
            accessed.append(chunk.document_id)
            matches.append(self._assemble(record, s, meta))
        return tuple(matches), tuple(accessed)

    def _assemble(
        self,
        record: _TroubleCaseRecord,
        scored: ScoredChunk,
        meta: ManufacturingDocumentMetadata | None,
    ) -> TroubleCaseMatch:
        tc = record.trouble_case
        split = split_countermeasures(record.countermeasures)
        citation = self._citation(scored, meta)
        return TroubleCaseMatch(
            trouble_case_id=tc.trouble_case_id,
            symptom=tc.symptom,
            equipment_id=tc.equipment_id,
            process_id=tc.process_id,
            failure_mode=record.failure_mode,
            countermeasures=split,
            recurrence_prevention=record.recurrence_prevention,
            citations=(citation,),
            relevance_score=scored.retrieval_score,
        )

    def _citation(
        self, scored: ScoredChunk, meta: ManufacturingDocumentMetadata | None
    ) -> TroubleCaseCitation:
        """Build the 001-shaped citation + approval provenance for the matched source report."""
        chunk = scored.chunk
        doc = self._get_document(chunk.tenant_id, chunk.document_id) if self._get_document else None
        return TroubleCaseCitation(
            kind="text",
            document_id=chunk.document_id,
            source_id=getattr(doc, "source_id", "") if doc else "",
            version=getattr(doc, "version", 0) if doc else 0,
            retrieval_score=scored.retrieval_score,
            chunk_id=chunk.chunk_id,
            text_range=(0, len(chunk.text)),
            approval_status=(meta.approval_status.value if meta else None),
            effective_date=(meta.effective_date if meta else None),
            approval_source=(meta.approval_source.value if meta else None),
        )


def _matches_filters(meta: ManufacturingDocumentMetadata | None, filters: dict | None) -> bool:
    """Candidate post-filter on manufacturing tags (mirrors search_ext; never weakens ACL)."""
    if not filters:
        return True
    if meta is None:
        return False
    for key, want in filters.items():
        if want is None:
            continue
        got = getattr(meta, key, None)
        if got is None and key == "document_type":
            got = getattr(meta, "document_kind", None)
        if hasattr(got, "value"):
            got = got.value
        if got != want:
            return False
    return True
