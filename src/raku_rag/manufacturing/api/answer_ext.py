"""T018 — Manufacturing answer overlay: HighRiskClassifier -> 001 answer path -> SafetyGate.

Wires the manufacturing safety overlay onto the REUSED 001 answer path. The 001
``RetrievalService`` / ``GroundednessGate`` / ``AnswerService`` are not reimplemented; this module
ORCHESTRATES them and layers the high-risk classification + safety gate decision on top, producing a
``ManufacturingAnswer`` that ADDS fields to the 001 ``Answer`` (additive, non-breaking; contracts §A).

Flow (FR-MFG-005/006/007/015/030):
  1. Map ``manufacturing_filters`` to the 001 metadata filter (applied as a candidate post-filter on
     ACL-pre-filtered retrieval — never weakening ACL/tenancy).
  2. Retrieve candidates via 001 ``RetrievalService`` and pre-gate them via 001 ``GroundednessGate``.
  3. Resolve each candidate's ``ManufacturingDocumentMetadata`` from the 001 document metadata.
  4. Classify high-risk over the query + candidate metadata (HighRiskClassifier).
  5. Run the SafetyGate over the candidate citations + metadata.
  6. If blocked => return ``insufficient_evidence`` with the normalized ``safety_block_reason``,
     empty text, empty used_chunks (MUST NOT assert; FR-MFG-005).
     Else => run the 001 ``AnswerService`` and decorate its citations with approval provenance.
  7. Always carry the high-risk flags + decision through for audit (T020).

stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from raku_rag.core.errors import AnswerStatus
from raku_rag.domain.models import (
    Answer,
    Citation,
    IdentityClaims,
    QueryProfile,
    ScoredChunk,
)
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.manufacturing.domain.safety import HighRiskClassification, SafetyDecision
from raku_rag.manufacturing.safety.classifier import RuleHighRiskClassifier
from raku_rag.manufacturing.safety.gate import ManufacturingSafetyGate, normalize_block_reason
from raku_rag.services.answer import AnswerService
from raku_rag.services.groundedness import GroundednessGate
from raku_rag.services.retrieval import RetrievalService

# On-site confirmation notice surfaced for hazardous high-risk work (contracts §A).
ONSITE_CONFIRMATION_NOTICE = "作業実施前に現場責任者または有資格者の確認が必要です。"


@dataclass(frozen=True)
class ManufacturingCitation:
    """001 Citation + manufacturing approval provenance (FR-MFG-004, contracts §A)."""

    kind: str
    document_id: str
    source_id: str
    version: int
    retrieval_score: float
    chunk_id: str | None = None
    text_range: tuple[int, int] | None = None
    # manufacturing additions
    approval_status: str | None = None
    effective_date: str | None = None
    approval_source: str | None = None

    @classmethod
    def from_base(
        cls, c: Citation, meta: ManufacturingDocumentMetadata | None
    ) -> "ManufacturingCitation":
        return cls(
            kind=c.kind,
            document_id=c.document_id,
            source_id=c.source_id,
            version=c.version,
            retrieval_score=c.retrieval_score,
            chunk_id=c.chunk_id,
            text_range=c.text_range,
            approval_status=(meta.approval_status.value if meta else None),
            effective_date=(meta.effective_date if meta else None),
            approval_source=(meta.approval_source.value if meta else None),
        )


@dataclass(frozen=True)
class ManufacturingAnswer:
    """001 Answer fields + the manufacturing safety extension (contracts §A, additive)."""

    status: str
    text: str | None = None
    confidence: float | None = None
    citations: tuple[ManufacturingCitation, ...] = ()
    used_chunks: tuple[str, ...] = ()
    used_modalities: tuple[str, ...] = ()
    freshness: tuple = ()
    cost: dict = field(default_factory=dict)
    correlation_id: str = ""
    # --- manufacturing extension ---
    high_risk: bool = False
    high_risk_reason_codes: tuple[str, ...] = ()
    safety_block_reason: str | None = None
    obsolete_warning: bool = False
    requires_onsite_confirmation: bool = False
    notice: str | None = None


# document_id -> ManufacturingDocumentMetadata resolver (tenant-scoped by caller).
from typing import Callable

GetMfgMeta = Callable[[str, str], ManufacturingDocumentMetadata | None]


def _matches_filters(meta: ManufacturingDocumentMetadata | None, filters: dict | None) -> bool:
    """Map 001 metadata filter to manufacturing tags: a candidate must match every provided key."""
    if not filters:
        return True
    if meta is None:
        return False
    for key, want in filters.items():
        if want is None:
            continue
        got = getattr(meta, key, None)
        # document_type is the alias for document_kind enum (compare on value).
        if got is None and key == "document_type":
            got = getattr(meta, "document_kind", None)
        if hasattr(got, "value"):
            got = got.value
        if got != want:
            return False
    return True


class ManufacturingAnswerService:
    """Overlay service composing 001 services with the manufacturing safety gate."""

    def __init__(
        self,
        *,
        retrieval: RetrievalService,
        groundedness: GroundednessGate,
        answer_service: AnswerService,
        get_mfg_meta: GetMfgMeta,
        classifier: RuleHighRiskClassifier | None = None,
        safety_gate: ManufacturingSafetyGate | None = None,
        get_document=None,
        today: date | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._groundedness = groundedness
        self._answer_service = answer_service
        self._get_mfg_meta = get_mfg_meta
        self._get_document = get_document
        self._classifier = classifier or RuleHighRiskClassifier()
        self._safety_gate = safety_gate or ManufacturingSafetyGate(today=today)

    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        profile: QueryProfile,
        *,
        intent_hint: str | None = None,
        manufacturing_filters: dict | None = None,
    ) -> tuple[ManufacturingAnswer, HighRiskClassification, SafetyDecision, tuple[str, ...]]:
        """Return (answer, classification, safety_decision, candidate_document_ids) for audit."""
        tenant = principal.tenant_id

        # (1)+(2) retrieve + 001 metadata filter (ACL pre-filter already applied inside retrieval).
        scored: list[ScoredChunk] = list(self._retrieval.retrieve(principal, query, profile))
        candidate_scored = [
            s
            for s in scored
            if _matches_filters(self._get_mfg_meta(tenant, s.chunk.document_id), manufacturing_filters)
        ]

        # (3) candidate metadata + the citations the 001 path would consider (pre-gate evidence).
        pre = self._groundedness.pre_gate(candidate_scored, profile)
        evidence = list(pre.evidence) if pre.passed else []

        candidate_doc_ids: list[str] = []
        candidate_meta: list[ManufacturingDocumentMetadata] = []
        seen: set[str] = set()
        for s in evidence:
            did = s.chunk.document_id
            if did in seen:
                continue
            seen.add(did)
            candidate_doc_ids.append(did)
            m = self._get_mfg_meta(tenant, did)
            if m is not None:
                candidate_meta.append(m)

        candidate_citations = [self._candidate_citation(s) for s in evidence]

        # (4) high-risk classification over query + candidate metadata.
        classification = self._classifier.classify(query, candidate_meta, intent_hint=intent_hint)

        # (5) safety gate over candidate citations + metadata.
        decision = self._safety_gate.evaluate(classification, candidate_citations, candidate_meta)

        notice = ONSITE_CONFIRMATION_NOTICE if decision.requires_onsite_confirmation else None

        # (6) blocked => MUST NOT assert (FR-MFG-005).
        if decision.blocked:
            reason = normalize_block_reason(decision.safety_block_reason)
            blocked = ManufacturingAnswer(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE.value,
                text=None,
                citations=(),
                used_chunks=(),
                correlation_id="",
                high_risk=classification.is_high_risk,
                high_risk_reason_codes=classification.reason_codes,
                safety_block_reason=(reason.value if reason else None),
                obsolete_warning=decision.obsolete_warning,
                requires_onsite_confirmation=decision.requires_onsite_confirmation,
                notice=notice,
            )
            return blocked, classification, decision, tuple(candidate_doc_ids)

        # Not blocked => run the REUSED 001 answer path and decorate citations.
        base: Answer = self._answer_service.answer(principal, query, profile)

        mfg_citations = tuple(
            ManufacturingCitation.from_base(c, self._get_mfg_meta(tenant, c.document_id))
            for c in base.citations
        )

        # If 001 itself could not produce a grounded answer, normalize the block reason.
        base_block_reason = None
        if base.status != AnswerStatus.OK.value:
            base_block_reason = normalize_block_reason(decision.safety_block_reason) or _as_reason(
                base.status
            )

        ans = ManufacturingAnswer(
            status=base.status,
            text=base.text,
            confidence=base.confidence,
            citations=mfg_citations,
            used_chunks=base.used_chunks,
            used_modalities=base.used_modalities,
            freshness=base.freshness,
            cost=base.cost,
            correlation_id=base.correlation_id,
            high_risk=classification.is_high_risk,
            high_risk_reason_codes=classification.reason_codes,
            safety_block_reason=(base_block_reason.value if base_block_reason else None),
            obsolete_warning=decision.obsolete_warning,
            requires_onsite_confirmation=decision.requires_onsite_confirmation,
            notice=notice if base.status == AnswerStatus.OK.value else notice,
        )
        return ans, classification, decision, tuple(candidate_doc_ids)

    def _candidate_citation(self, s: ScoredChunk) -> Citation:
        """Build the 001-shaped Citation for a candidate chunk so the SafetyGate can survey approval."""
        c = s.chunk
        doc = self._get_document(c.tenant_id, c.document_id) if self._get_document else None
        return Citation(
            kind="text",
            document_id=c.document_id,
            source_id=doc.source_id if doc else "",
            version=doc.version if doc else 0,
            retrieval_score=s.retrieval_score,
            chunk_id=c.chunk_id,
            text_range=(0, len(c.text)),
        )


def _as_reason(status: str):
    from raku_rag.manufacturing.domain.safety import SafetyBlockReason

    if status == AnswerStatus.INSUFFICIENT_EVIDENCE.value:
        return SafetyBlockReason.INSUFFICIENT_EVIDENCE
    return SafetyBlockReason.OTHER_BLOCK
