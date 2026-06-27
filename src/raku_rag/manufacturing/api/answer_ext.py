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

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Callable, Sequence

from raku_rag.core.errors import AnswerStatus
from raku_rag.domain.models import (
    Answer,
    Citation,
    IdentityClaims,
    QueryProfile,
    ScoredChunk,
)
from raku_rag.manufacturing.domain.metadata import ApprovalStatus, ManufacturingDocumentMetadata
from raku_rag.manufacturing.domain.safety import (
    HighRiskClassification,
    SafetyBlockReason,
    SafetyDecision,
)
from raku_rag.manufacturing.safety.classifier import RuleHighRiskClassifier
from raku_rag.manufacturing.safety.gate import (
    ManufacturingSafetyGate,
    is_approved_effective,
    normalize_block_reason,
)
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
GetMfgMeta = Callable[[str, str], ManufacturingDocumentMetadata | None]


_METADATA_RISK_REASON_PREFIX = "metadata:"
_METADATA_RISK_REASON_CODES = {"hazard_tag"}


class _PreselectedRetrieval:
    """Retrieval facade for reusing AnswerService with already filtered evidence."""

    def __init__(self, base: RetrievalService, scored: Sequence[ScoredChunk]) -> None:
        self._base = base
        self._scored = tuple(scored)
        self.last_prefiltered_count = len(self._scored)

    def retrieve(
        self,
        principal: IdentityClaims,
        query: str,
        profile: QueryProfile,
        *,
        correlation_id: str = "",
    ) -> list[ScoredChunk]:
        return list(self._scored)

    def is_visible(self, principal: IdentityClaims, chunk) -> bool:
        is_visible = getattr(self._base, "is_visible", None)
        if callable(is_visible):
            return bool(is_visible(principal, chunk))
        return chunk.tenant_id == principal.tenant_id and not getattr(chunk, "tombstone", False)


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


def _is_metadata_only_high_risk(classification: HighRiskClassification) -> bool:
    """True when risk came from document metadata, not a dangerous user intent."""
    if not classification.is_high_risk or not classification.reason_codes:
        return False
    return all(
        code in _METADATA_RISK_REASON_CODES or code.startswith(_METADATA_RISK_REASON_PREFIX)
        for code in classification.reason_codes
    )


def _is_approved(meta: ManufacturingDocumentMetadata | None) -> bool:
    status = getattr(meta, "approval_status", None)
    if hasattr(status, "value"):
        status = status.value
    return status == ApprovalStatus.APPROVED.value


def _should_answer_from_approved_lookup_evidence(
    query: str,
    intent_hint: str | None,
    *,
    classification: HighRiskClassification,
) -> bool:
    if _is_metadata_only_high_risk(classification):
        return True
    if classification.is_high_risk:
        return False
    hint = (intent_hint or "").strip().lower()
    if hint in {"equipment_lookup", "metadata_lookup", "asset_lookup"}:
        return True
    q = query or ""
    return "設備" in q and any(
        field in q
        for field in (
            "担当部門",
            "担当部署",
            "設置ライン",
            "保全コード",
            "記録先",
            "発効日",
            "点検計画日",
            "次回点検",
            "について",
        )
    )


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
        self._today = today

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
            if _matches_filters(
                self._get_mfg_meta(tenant, s.chunk.document_id), manufacturing_filters
            )
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
        # Metadata-only high-risk often means "the document is about equipment/safety", not that the
        # user's request asks for an operation. For those lookups, keep the high-risk label but force
        # generation to approved+effective evidence only so draft/obsolete noise cannot poison the
        # answer or cause an avoidable approved_citation_missing demotion.
        answer_service, approved_lookup_evidence = self._answer_service_for_metadata_lookup(
            principal,
            profile,
            query=query,
            intent_hint=intent_hint,
            classification=classification,
            evidence=evidence,
        )
        if approved_lookup_evidence:
            filtered_citations = [self._candidate_citation(s) for s in approved_lookup_evidence]
            filtered_meta = [
                m
                for c in filtered_citations
                if (m := self._get_mfg_meta(tenant, c.document_id)) is not None
            ]
            filtered_decision = self._safety_gate.evaluate(
                classification, filtered_citations, filtered_meta
            )
            if decision.obsolete_warning and not filtered_decision.obsolete_warning:
                filtered_decision = replace(filtered_decision, obsolete_warning=True)
            decision = filtered_decision
            notice = ONSITE_CONFIRMATION_NOTICE if decision.requires_onsite_confirmation else None

        base: Answer = answer_service.answer(principal, query, profile)

        mfg_citations = tuple(
            ManufacturingCitation.from_base(c, self._get_mfg_meta(tenant, c.document_id))
            for c in base.citations
        )

        # (FR-MFG-006 / SC-MFG-011) T066 integration glue: the pre-gate ``has_usable_primary`` check
        # confirms SOME candidate is non-draft/non-obsolete, but the REUSED 001 answer path may still
        # rank an OBSOLETE document as the TOP cited evidence (when an unrelated approved doc only
        # shares generic tokens). The gate's documented invariant is "an obsolete document is NEVER
        # primary evidence": so if the answer asserted with an obsolete PRIMARY (top) citation and NO
        # approved+effective document is among the actually-cited evidence, the obsolete doc would be
        # the real basis of the assertion — demote to insufficient_evidence (reference-only + warning).
        # The REUSED 001 answer path ranks evidence by score and may place a DRAFT/OBSOLETE document
        # as the TOP (primary) citation even though the SafetyGate only surveyed that *some* approved
        # doc exists among candidates. Two demotions guard the PRIMARY-evidence invariant:
        #  - (FR-MFG-006/SC-MFG-011) obsolete PRIMARY with no approved+effective among the CITED
        #    evidence => an obsolete doc is never primary (existing behavior; applies to any answer).
        #  - (GAP-S3/SC-MFG-006) a HIGH-RISK assertion must rest ENTIRELY on approved+effective
        #    evidence. Guarding only the PRIMARY (citations[0]) slot is insufficient: the REUSED 001
        #    answer path composes the answer TEXT from ALL context chunks and then cites every chunk
        #    whose terms appear in that text, so a draft/obsolete/pending source in ANY cited slot can
        #    still contaminate a high-risk answer's text and citation list (source poisoning via a
        #    SECONDARY citation, even when an approved doc is primary). Demote to insufficient_evidence
        #    unless EVERY cited source is approved+effective.
        if base.status == AnswerStatus.OK.value and mfg_citations:
            primary = mfg_citations[0]
            cited_approved_effective = [
                is_approved_effective(self._get_mfg_meta(tenant, c.document_id), today=self._today)
                for c in mfg_citations
            ]
            cited_has_approved_effective = any(cited_approved_effective)
            high_risk_unsupported = classification.is_high_risk and not all(
                cited_approved_effective
            )
            obsolete_primary_unsupported = (
                primary.approval_status == ApprovalStatus.OBSOLETE.value
                and not cited_has_approved_effective
            )
            if high_risk_unsupported or obsolete_primary_unsupported:
                block_reason = (
                    SafetyBlockReason.APPROVED_CITATION_MISSING
                    if high_risk_unsupported
                    else SafetyBlockReason.INSUFFICIENT_EVIDENCE
                )
                blocked = ManufacturingAnswer(
                    status=AnswerStatus.INSUFFICIENT_EVIDENCE.value,
                    text=None,
                    citations=(),
                    used_chunks=(),
                    correlation_id=base.correlation_id,
                    high_risk=classification.is_high_risk,
                    high_risk_reason_codes=classification.reason_codes,
                    safety_block_reason=block_reason.value,
                    obsolete_warning=(
                        primary.approval_status == ApprovalStatus.OBSOLETE.value
                        or decision.obsolete_warning
                    ),
                    requires_onsite_confirmation=decision.requires_onsite_confirmation,
                    notice=notice,
                )
                return blocked, classification, decision, tuple(candidate_doc_ids)

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

    def _answer_service_for_metadata_lookup(
        self,
        principal: IdentityClaims,
        profile: QueryProfile,
        *,
        query: str,
        intent_hint: str | None,
        classification: HighRiskClassification,
        evidence: Sequence[ScoredChunk],
    ) -> tuple[AnswerService, tuple[ScoredChunk, ...]]:
        if not _should_answer_from_approved_lookup_evidence(
            query, intent_hint, classification=classification
        ):
            return self._answer_service, ()

        require_effective = _is_metadata_only_high_risk(classification)
        approved_lookup = [
            s
            for s in evidence
            if (
                is_approved_effective(
                    self._get_mfg_meta(principal.tenant_id, s.chunk.document_id),
                    today=self._today,
                )
                if require_effective
                else _is_approved(self._get_mfg_meta(principal.tenant_id, s.chunk.document_id))
            )
        ]
        if not approved_lookup:
            return self._answer_service, ()
        pre = self._groundedness.pre_gate(approved_lookup, profile)
        if not pre.passed:
            return self._answer_service, ()

        retrieval = _PreselectedRetrieval(self._retrieval, pre.evidence)
        # Reuse the existing AnswerService implementation so generation, prompt-injection defense,
        # post-grounding, citation revalidation, cost, metrics, and audit behavior stay identical.
        return (
            AnswerService(
                retrieval=retrieval,  # type: ignore[arg-type]
                llm=self._answer_service._llm,
                gate=self._answer_service._gate,
                cost=self._answer_service._cost,
                get_document=self._answer_service._get_document,
                metrics=self._answer_service._metrics,
                tracer=self._answer_service._tracer,
                audit=self._answer_service._audit,
                vlm=self._answer_service._vlm,
                injection_guard=self._answer_service._injection_guard,
                output_guardrail=self._answer_service._output_guardrail,
                structured_tool=self._answer_service._structured_tool,
            ),
            tuple(pre.evidence),
        )

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
