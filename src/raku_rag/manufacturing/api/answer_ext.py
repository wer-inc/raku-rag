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

import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Callable, Sequence

from raku_rag.core.errors import AnswerStatus
from raku_rag.core.hybrid_retrieval import lexical_query_terms
from raku_rag.domain.models import (
    Answer,
    BoundingBox,
    Citation,
    IdentityClaims,
    Modality,
    QueryProfile,
    ScoredChunk,
)
from raku_rag.manufacturing.domain.metadata import ApprovalStatus, ManufacturingDocumentMetadata
from raku_rag.manufacturing.domain.safety import (
    ClassificationSource,
    HighRiskClassification,
    SafetyBlockReason,
    SafetyDecision,
)
from raku_rag.manufacturing.safety.classifier import RuleHighRiskClassifier
from raku_rag.manufacturing.safety.gate import (
    ManufacturingSafetyGate,
    VISUAL_DERIVED_CITATION_KINDS,
    citation_is_approved_effective,
    is_promotable_evidence,
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
    asset_id: str = ""
    page_number: int = 0
    region_id: str = ""
    bbox: BoundingBox | None = None
    crop_uri: str = ""
    sheet_name: str = ""
    cell_range: str = ""
    row_id: str = ""
    table_id: str = ""
    form_id: str = ""
    field_name: str = ""
    chart_id: str = ""
    series_name: str = ""
    point_index: int = -1
    column_name: str = ""
    pixel_derived: bool = False
    visual_evidence_verified: bool = False
    visual_verifier_verdicts: tuple[dict, ...] = ()
    metadata: dict = field(default_factory=dict)
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
            asset_id=c.asset_id,
            page_number=c.page_number,
            region_id=c.region_id,
            bbox=c.bbox,
            crop_uri=c.crop_uri,
            sheet_name=c.sheet_name,
            cell_range=c.cell_range,
            row_id=c.row_id,
            table_id=c.table_id,
            form_id=c.form_id,
            field_name=c.field_name,
            chart_id=c.chart_id,
            series_name=c.series_name,
            point_index=c.point_index,
            column_name=c.column_name,
            pixel_derived=bool(
                getattr(c, "pixel_derived", False) or c.kind in VISUAL_DERIVED_CITATION_KINDS
            ),
            visual_evidence_verified=c.visual_evidence_verified,
            visual_verifier_verdicts=c.visual_verifier_verdicts,
            metadata=dict(getattr(c, "metadata", {}) or {}),
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
    visual_evidence_audit: tuple[dict, ...] = ()


# document_id -> ManufacturingDocumentMetadata resolver (tenant-scoped by caller).
GetMfgMeta = Callable[[str, str], ManufacturingDocumentMetadata | None]


_METADATA_RISK_REASON_PREFIX = "metadata:"
_METADATA_RISK_REASON_CODES = {"hazard_tag"}
_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[A-Za-z]{1,12}(?:-[A-Za-z0-9]{1,16})+"
    r"|[A-Za-z]{2,12}[0-9]{2,}(?:-[A-Za-z0-9]{1,16})*"
    r")(?![A-Za-z0-9])"
)


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
        return True
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


def _should_defer_visual_promotion(
    decision: SafetyDecision,
    candidate_citations: Sequence[Citation],
    candidate_metadata: Sequence[ManufacturingDocumentMetadata],
    *,
    visual_evidence_promotion: bool,
    today: date | None,
) -> bool:
    """Let approved visual candidates reach answer-time verification instead of deadlocking.

    The pre-gate survey cannot know whether a visual citation grounds the answer, because the
    sentence-level assertion does not exist until generation. Deferring is allowed only for the exact
    approved-citation-missing case and only when an approved+effective visual-derived candidate exists.
    The post-answer demotion still blocks unless the cited visual evidence is verified.
    """

    if not visual_evidence_promotion:
        return False
    if not decision.blocked:
        return False
    if decision.safety_block_reason != SafetyBlockReason.APPROVED_CITATION_MISSING:
        return False
    by_doc = {m.document_id: m for m in candidate_metadata if m is not None}
    return any(
        c.kind in VISUAL_DERIVED_CITATION_KINDS
        and is_approved_effective(by_doc.get(c.document_id), today=today)
        and is_promotable_evidence(getattr(c, "metadata", None))
        for c in candidate_citations
    )


def _normalize_identifier(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _query_identifiers(query: str) -> tuple[str, ...]:
    seen: set[str] = set()
    identifiers: list[str] = []
    for match in _IDENTIFIER_RE.finditer(query or ""):
        normalized = _normalize_identifier(match.group(0))
        if len(normalized) < 3 or normalized in seen:
            continue
        seen.add(normalized)
        identifiers.append(normalized)
    return tuple(identifiers)


def _evidence_identifier_blob(
    evidence: Sequence[ScoredChunk],
    metadata: Sequence[ManufacturingDocumentMetadata],
) -> str:
    parts: list[str] = []
    for scored in evidence:
        chunk = scored.chunk
        parts.extend(
            [
                chunk.document_id,
                chunk.chunk_id,
                chunk.text,
            ]
        )
        parts.extend(str(value) for value in chunk.metadata.values() if value is not None)
    for meta in metadata:
        parts.extend(
            str(value)
            for value in (
                meta.document_id,
                getattr(meta, "equipment_id", None),
                getattr(meta, "factory_id", None),
                getattr(meta, "line_id", None),
                getattr(meta, "process_id", None),
            )
            if value
        )
    return _normalize_identifier(" ".join(parts))


def _missing_query_identifiers(
    query: str,
    evidence: Sequence[ScoredChunk],
    metadata: Sequence[ManufacturingDocumentMetadata],
) -> tuple[str, ...]:
    identifiers = _query_identifiers(query)
    if not identifiers:
        return ()
    blob = _evidence_identifier_blob(evidence, metadata)
    return tuple(identifier for identifier in identifiers if identifier not in blob)


def _visual_grounding_method(verdicts: Sequence[dict]) -> str:
    """Audit-safe grounding category for visual evidence.

    The audit event records how visual evidence was grounded, but never OCR/caption text or crop
    bytes. Keep these values coarse so they are useful for review without becoming a content leak.
    """

    lexical_reason = ""
    for verdict in verdicts:
        if verdict.get("verifier_kind") == "lexical":
            lexical_reason = str(verdict.get("reason_code") or "")
            break
    if lexical_reason == "substring_match":
        return "ocr_verbatim"
    if lexical_reason in {
        "term_subset_match",
        "assertion_terms_empty",
        "identifier_anchor_missing",
        "ocr_subset_missing_terms",
    }:
        return "ocr_subset"
    if lexical_reason == "ocr_empty":
        return "ocr_unavailable"
    return "visual_verifier"


def _visual_evidence_audit_payload(
    citations: Sequence[ManufacturingCitation],
    *,
    quorum: int,
) -> tuple[dict, ...]:
    payload: list[dict] = []
    for citation in citations:
        if citation.kind not in VISUAL_DERIVED_CITATION_KINDS and not citation.asset_id:
            continue
        verifier_payload = [dict(item) for item in citation.visual_verifier_verdicts]
        payload.append(
            {
                "citation_id": citation.chunk_id
                or ":".join(part for part in (citation.asset_id, citation.region_id) if part),
                "document_id": citation.document_id,
                "kind": citation.kind,
                "asset_id": citation.asset_id,
                "region_id": citation.region_id,
                "page_number": citation.page_number,
                "has_bbox": citation.bbox is not None,
                "approval_status_at_use": citation.approval_status,
                "grounding_method": _visual_grounding_method(verifier_payload),
                "promoted": citation.visual_evidence_verified,
                "verifiers": verifier_payload,
                "quorum": max(1, int(quorum)),
            }
        )
    return tuple(payload)


def _visual_page_key(citation: ManufacturingCitation) -> tuple[str, int, str]:
    return (citation.document_id, int(citation.page_number or 0), citation.asset_id or "")


def _collapse_visual_page_citations(
    citations: Sequence[ManufacturingCitation],
) -> tuple[ManufacturingCitation, ...]:
    """Use verified page-level visual evidence as the primary citation for same-page line crops.

    OCR line regions are still useful for retrieval, but a high-risk manufacturing assertion may
    span several lines. When a verified, promotable page aggregate exists for the same document page
    and asset, the aggregate is the evidence reviewed by the verifier; same-page line crops become
    redundant and should not make the post-answer safety gate fail as unverified secondary citations.
    """

    verified_page_keys = {
        _visual_page_key(citation)
        for citation in citations
        if citation.kind in VISUAL_DERIVED_CITATION_KINDS
        and citation.visual_evidence_verified
        and bool(citation.metadata.get("page_aggregate"))
        and is_promotable_evidence(citation.metadata)
    }
    if not verified_page_keys:
        return tuple(citations)

    collapsed: list[ManufacturingCitation] = []
    for citation in citations:
        if (
            citation.kind in VISUAL_DERIVED_CITATION_KINDS
            and not bool(citation.metadata.get("page_aggregate"))
            and _visual_page_key(citation) in verified_page_keys
        ):
            continue
        collapsed.append(citation)
    return tuple(collapsed)


def _lexically_responsive(text: str, intent_terms: set[str]) -> bool:
    """True when `text` shares at least one lexical retrieval term with the raw intent's terms.

    Used to distinguish evidence genuinely on-topic for what the USER asked from evidence seated only
    by prior-turn terms an upstream coreference rewrite carried (which `lexical_match_score`'s flat
    base score admits on a single shared term). See `ManufacturingAnswerService.answer`'s handling of
    `intent_query`. Empty intent terms => nothing is responsive (fail-safe: a query with no usable
    signal cannot vouch for any carried-in document)."""
    if not intent_terms:
        return False
    return bool(intent_terms & set(lexical_query_terms(text)))


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
        visual_evidence_promotion: bool = False,
    ) -> None:
        self._retrieval = retrieval
        self._groundedness = groundedness
        self._answer_service = answer_service
        self._get_mfg_meta = get_mfg_meta
        self._get_document = get_document
        self._classifier = classifier or RuleHighRiskClassifier()
        self._visual_evidence_promotion = visual_evidence_promotion
        self._safety_gate = safety_gate or ManufacturingSafetyGate(
            today=today,
            visual_evidence_promotion=visual_evidence_promotion,
        )
        self._today = today

    def classify_query_signal(self, query: str) -> bool:
        """Retrieval-independent, CONCRETE high-risk signal for raw query text alone.

        Used by ``chatbot/coreference.py``'s pre-rewrite safety check (see that module's docstring
        and ``ManufacturingSystem.is_high_risk_query_signal``): a chatbot-layer rung decides whether
        it is safe to fold prior-turn context into a follow-up's outgoing query string BEFORE any
        retrieval has run this turn, so this must be answerable from query text alone, with no
        candidate evidence yet -- exactly what ``self._classifier.classify(query, ())`` (empty
        candidate metadata) gives: only the METADATA stage (vacuous here, no candidates) and the
        KEYWORD stage (a query text match against ``_INTENT_KEYWORDS``) can ever fire.

        Deliberately NARROWER than plain ``classification.is_high_risk``: this excludes the
        classifier's stage-3 "ambiguous" fail-safe (``classification_source`` RULE/LLM), which fires
        on ANY short/terse query -- and empirically, on nearly every short Japanese sentence, since
        ``core.text.content_tokens`` cannot word-segment CJK text (no spaces) below the classifier's
        3-token floor, regardless of actual content (confirmed: "その締付トルクは?", P3's own benign
        flagship follow-up, hits this fail-safe too). Treating that catch-all as a danger SIGNAL here
        would make this check fire for nearly every short referential follow-up in the language this
        product primarily serves, silently starving the coreference rewrite of its value with no
        safety upside (the real classifier + safety gate still run for real, once, inside
        ``inner.answer()`` regardless of this decision). "Ambiguous => assert nothing without
        approved evidence" is the right fail-safe for the FINAL answer; it is not evidence that THIS
        query text is the kind of concrete hazard statement that must not be diluted by appending
        unrelated prior-turn terms to it. Only a METADATA/KEYWORD hit -- an explicit, concrete
        signal -- counts here.
        """
        classification = self._classifier.classify(query, ())
        return classification.is_high_risk and classification.classification_source in (
            ClassificationSource.METADATA,
            ClassificationSource.KEYWORD,
        )

    def _enforce_intent_responsive_approved_citation(
        self,
        decision: SafetyDecision,
        classification: HighRiskClassification,
        evidence: Sequence[ScoredChunk],
        *,
        query: str,
        effective_intent: str,
    ) -> SafetyDecision:
        """Root-cause fix for the L2/L3 coreference bypass (chatbot/coreference.py's Finding).

        No-op unless the outgoing query was REWRITTEN (``effective_intent != query``) for a HIGH-RISK
        intent the base gate did NOT already block. In that window the enriched ``query`` may have
        seated an unrelated APPROVED document as evidence (``lexical_match_score`` gives any document
        sharing even one query term a flat base score), which would wrongly satisfy the high-risk
        approved-citation requirement. Require instead that at least one approved+effective evidence
        chunk be RESPONSIVE to the raw intent — sharing a lexical term with it — else block
        APPROVED_CITATION_MISSING, the SAME fail-safe the gate already produces when no approved
        citation exists at all. Purely additive: it can only turn an allow into a block.
        """
        if effective_intent == query or not classification.is_high_risk or decision.blocked:
            return decision
        intent_terms = set(lexical_query_terms(effective_intent))
        responsive_approved = any(
            _lexically_responsive(s.chunk.text, intent_terms)
            and is_approved_effective(
                self._get_mfg_meta(s.chunk.tenant_id, s.chunk.document_id), today=self._today
            )
            for s in evidence
        )
        if responsive_approved:
            return decision
        return replace(
            decision,
            blocked=True,
            safety_block_reason=SafetyBlockReason.APPROVED_CITATION_MISSING,
            requires_onsite_confirmation=True,
            approval_status_at_use=None,
        )

    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        profile: QueryProfile,
        *,
        intent_hint: str | None = None,
        manufacturing_filters: dict | None = None,
        intent_query: str | None = None,
    ) -> tuple[ManufacturingAnswer, HighRiskClassification, SafetyDecision, tuple[str, ...]]:
        """Return (answer, classification, safety_decision, candidate_document_ids) for audit.

        ``query`` drives RETRIEVAL and generation. ``intent_query`` (keyword-only; default None => the
        raw intent IS ``query``) is the UN-enriched user query when an upstream chatbot rung rewrote
        ``query`` to carry prior-turn context (see chatbot/coreference.py's Finding). The high-risk
        CLASSIFICATION and the high-risk approved-citation requirement are bound to this raw intent,
        NOT the enriched query, so appending prior-turn terms can never (a) launder a high-risk query
        into a non-high-risk one nor (b) let a document seated purely by carried terms satisfy the
        approved-citation gate. Omitted for every non-rewriting caller => byte-identical to before.
        """
        tenant = principal.tenant_id
        # The query whose OWN text/intent the safety decisions must reflect (not the recall-enriched
        # one). ``or`` handles both None and an empty string defensively.
        effective_intent = intent_query or query

        # (1)+(2) retrieve + 001 metadata filter (ACL pre-filter already applied inside retrieval).
        scored: list[ScoredChunk] = list(self._retrieval.retrieve(principal, query, profile))
        candidate_scored = [
            s
            for s in scored
            if _matches_filters(
                self._get_mfg_meta(tenant, s.chunk.document_id), manufacturing_filters
            )
        ]
        candidate_scored = self._with_visual_page_aggregate_candidates(
            principal, candidate_scored, profile
        )

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
        # Use the RAW intent, not the enriched query: the "does the evidence cover the identifiers
        # the query named?" check must judge the identifiers the USER named, never a document id an
        # upstream coreference rewrite carried in (which would otherwise demand that carried id be
        # present in evidence). Identical to `query` for every non-rewriting caller.
        missing_identifiers = _missing_query_identifiers(effective_intent, evidence, candidate_meta)

        # (4) high-risk classification over the RAW intent + candidate metadata. Using
        # `effective_intent` (not the enriched `query`) is what keeps a rewritten high-risk follow-up
        # classified high-risk: the enriched query is longer and can slip below the classifier's
        # "ambiguous, too terse to rule danger out" fail-safe, silently downgrading it.
        classification = self._classifier.classify(
            effective_intent, candidate_meta, intent_hint=intent_hint
        )

        # (5) safety gate over candidate citations + metadata.
        decision = self._safety_gate.evaluate(classification, candidate_citations, candidate_meta)
        # (5b) intent-responsiveness override (root-cause fix for the L2/L3 coreference bypass — see
        # chatbot/coreference.py's Finding). Only bites when an upstream rung actually rewrote the
        # query: for a HIGH-RISK intent, an approved+effective citation may satisfy the gate ONLY if
        # it is genuinely responsive to the raw intent, never one seated purely by carried prior-turn
        # terms via lexical_match_score's flat base score. Additive — it can only turn an allow into
        # a block, never the reverse — so it cannot weaken the gate for any existing caller.
        decision = self._enforce_intent_responsive_approved_citation(
            decision, classification, evidence, query=query, effective_intent=effective_intent
        )
        deferred_visual_promotion = _should_defer_visual_promotion(
            decision,
            candidate_citations,
            candidate_meta,
            visual_evidence_promotion=self._visual_evidence_promotion,
            today=self._today,
        )

        notice = ONSITE_CONFIRMATION_NOTICE if decision.requires_onsite_confirmation else None

        if missing_identifiers:
            blocked = ManufacturingAnswer(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE.value,
                text=None,
                citations=(),
                used_chunks=(),
                correlation_id="",
                high_risk=classification.is_high_risk,
                high_risk_reason_codes=classification.reason_codes,
                safety_block_reason=SafetyBlockReason.INSUFFICIENT_EVIDENCE.value,
                obsolete_warning=decision.obsolete_warning,
                requires_onsite_confirmation=decision.requires_onsite_confirmation,
                notice=notice,
            )
            return blocked, classification, decision, tuple(candidate_doc_ids)

        # (6) blocked => MUST NOT assert (FR-MFG-005).
        if decision.blocked and not deferred_visual_promotion:
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
        # High-risk generation must not see draft/obsolete/pending evidence. The overlay pre-filters
        # to approved+effective candidates before reusing the base AnswerService; post-generation
        # demotion still verifies that every cited source remains admissible.
        answer_service, approved_lookup_evidence = self._answer_service_for_metadata_lookup(
            principal,
            profile,
            query=query,
            intent_hint=intent_hint,
            classification=classification,
            evidence=evidence,
            effective_intent=effective_intent,
        )
        if approved_lookup_evidence:
            approved_lookup_meta = [
                m
                for s in approved_lookup_evidence
                if (m := self._get_mfg_meta(principal.tenant_id, s.chunk.document_id)) is not None
            ]
            if _missing_query_identifiers(
                effective_intent, approved_lookup_evidence, approved_lookup_meta
            ):
                block_reason = (
                    SafetyBlockReason.APPROVED_CITATION_MISSING
                    if classification.is_high_risk
                    else SafetyBlockReason.INSUFFICIENT_EVIDENCE
                )
                blocked = ManufacturingAnswer(
                    status=AnswerStatus.INSUFFICIENT_EVIDENCE.value,
                    text=None,
                    citations=(),
                    used_chunks=(),
                    correlation_id="",
                    high_risk=classification.is_high_risk,
                    high_risk_reason_codes=classification.reason_codes,
                    safety_block_reason=block_reason.value,
                    obsolete_warning=decision.obsolete_warning,
                    requires_onsite_confirmation=decision.requires_onsite_confirmation,
                    notice=notice,
                )
                return blocked, classification, decision, tuple(candidate_doc_ids)
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
        final_citations = (
            _collapse_visual_page_citations(mfg_citations)
            if classification.is_high_risk and self._visual_evidence_promotion
            else mfg_citations
        )
        final_used_chunks = (
            tuple(c.chunk_id for c in final_citations if c.chunk_id is not None) or base.used_chunks
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
        if base.status == AnswerStatus.OK.value and final_citations:
            primary = final_citations[0]
            cited_approved_effective = [
                citation_is_approved_effective(
                    c,
                    self._get_mfg_meta(tenant, c.document_id),
                    today=self._today,
                    visual_evidence_promotion=self._visual_evidence_promotion,
                )
                for c in final_citations
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
                    visual_evidence_audit=_visual_evidence_audit_payload(
                        final_citations,
                        quorum=self._answer_service._settings.visual_evidence_verifier_quorum,
                    ),
                )
                return blocked, classification, decision, tuple(candidate_doc_ids)
            if deferred_visual_promotion:
                decision = replace(
                    decision,
                    blocked=False,
                    safety_block_reason=None,
                    approval_status_at_use=ApprovalStatus.APPROVED.value,
                    obsolete_warning=decision.obsolete_warning,
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
            citations=final_citations,
            used_chunks=final_used_chunks,
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
            visual_evidence_audit=_visual_evidence_audit_payload(
                final_citations,
                quorum=self._answer_service._settings.visual_evidence_verifier_quorum,
            ),
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
        effective_intent: str | None = None,
    ) -> tuple[AnswerService, tuple[ScoredChunk, ...]]:
        if not _should_answer_from_approved_lookup_evidence(
            query, intent_hint, classification=classification
        ):
            return self._answer_service, ()

        require_effective = classification.is_high_risk
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
        # When an upstream rung rewrote the outgoing query (effective_intent != query), the enriched
        # query may have seated a document responsive ONLY to the carried prior-turn terms. Prefer the
        # approved evidence genuinely responsive to the raw intent so generation cites the on-topic
        # document, not the carried-in one — but only when such responsive evidence EXISTS, so a
        # legitimate same-topic follow-up whose target is found solely via the carried identifier still
        # keeps its recall. (The high-risk gate already blocked the case where none is responsive.)
        if effective_intent is not None and effective_intent != query:
            intent_terms = set(lexical_query_terms(effective_intent))
            responsive = [
                s for s in approved_lookup if _lexically_responsive(s.chunk.text, intent_terms)
            ]
            if responsive:
                approved_lookup = responsive
        if not approved_lookup:
            if classification.is_high_risk:
                return self._answer_service_for_preselected(())
            return self._answer_service, ()
        pre = self._groundedness.pre_gate(approved_lookup, profile)
        if not pre.passed:
            if classification.is_high_risk:
                return self._answer_service_for_preselected(())
            return self._answer_service, ()

        return self._answer_service_for_preselected(pre.evidence)

    def _with_visual_page_aggregate_candidates(
        self,
        principal: IdentityClaims,
        scored: Sequence[ScoredChunk],
        profile: QueryProfile,
    ) -> list[ScoredChunk]:
        """Include page-level visual evidence for retrieved visual line regions.

        Visual search often retrieves line-level OCR regions first. For high-risk promotion, the
        verifier needs a page-level crop/OCR surface when the asserted procedure spans multiple OCR
        lines. This only enriches the manufacturing answer path and preserves the same ACL predicate.
        """

        if not self._visual_evidence_promotion:
            return list(scored)
        store = getattr(self._retrieval, "_store", None)
        get_visual_chunks = getattr(store, "visual_chunks_for_document", None)
        if not callable(get_visual_chunks):
            return list(scored)
        is_visible = getattr(self._retrieval, "is_visible", None)
        seen: set[str] = set()
        enriched: list[ScoredChunk] = []
        aggregate_cache: dict[str, tuple[object, ...]] = {}

        def add(item: ScoredChunk) -> None:
            if item.chunk.chunk_id in seen:
                return
            seen.add(item.chunk.chunk_id)
            enriched.append(item)

        for item in scored:
            chunk = item.chunk
            if chunk.modality == Modality.VISUAL and not chunk.metadata.get("page_aggregate"):
                siblings = aggregate_cache.get(chunk.document_id)
                if siblings is None:
                    siblings = tuple(get_visual_chunks(principal.tenant_id, chunk.document_id))
                    aggregate_cache[chunk.document_id] = siblings
                page_number = int(chunk.metadata.get("page_number") or 0)
                for sibling in siblings:
                    if not getattr(sibling, "metadata", {}).get("page_aggregate"):
                        continue
                    if page_number and int(sibling.metadata.get("page_number") or 0) != page_number:
                        continue
                    if callable(is_visible) and not is_visible(principal, sibling):
                        continue
                    score = max(item.retrieval_score, profile.score_threshold)
                    add(ScoredChunk(chunk=sibling, retrieval_score=score))
            add(item)
        return enriched

    def _answer_service_for_preselected(
        self, evidence: Sequence[ScoredChunk]
    ) -> tuple[AnswerService, tuple[ScoredChunk, ...]]:
        retrieval = _PreselectedRetrieval(self._retrieval, evidence)
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
                settings=self._answer_service._settings,
                visual_verifiers=self._answer_service._visual_verifiers,
            ),
            tuple(evidence),
        )

    def _candidate_citation(self, s: ScoredChunk) -> Citation:
        """Build the Citation shape the SafetyGate surveys for approval."""
        c = s.chunk
        doc = self._get_document(c.tenant_id, c.document_id) if self._get_document else None
        is_visual = c.modality == Modality.VISUAL
        return Citation(
            kind="visual" if is_visual else str(c.metadata.get("structured_kind") or "text"),
            document_id=c.document_id,
            source_id=doc.source_id if doc else "",
            version=doc.version if doc else 0,
            retrieval_score=s.retrieval_score,
            chunk_id=c.chunk_id,
            text_range=(0, len(c.text)) if not is_visual else None,
            asset_id=str(c.metadata.get("asset_id", "")) if is_visual else "",
            page_number=int(c.metadata.get("page_number") or 0) if is_visual else 0,
            region_id=str(c.metadata.get("region_id", "")) if is_visual else "",
            bbox=_bbox_from_chunk(c) if is_visual else None,
            crop_uri=str(c.metadata.get("crop_uri", "")) if is_visual else "",
            pixel_derived=is_visual or bool(c.metadata.get("pixel_derived")),
            visual_evidence_verified=bool(c.metadata.get("visual_evidence_verified")),
            metadata=dict(c.metadata),
        )


def _bbox_from_chunk(chunk) -> BoundingBox | None:
    raw = chunk.metadata.get("bbox")
    if isinstance(raw, BoundingBox):
        return raw
    if isinstance(raw, dict):
        return BoundingBox(
            x=float(raw.get("x", 0.0)),
            y=float(raw.get("y", 0.0)),
            width=float(raw.get("width", 0.0)),
            height=float(raw.get("height", 0.0)),
        )
    return None


def _as_reason(status: str):
    from raku_rag.manufacturing.domain.safety import SafetyBlockReason

    if status == AnswerStatus.INSUFFICIENT_EVIDENCE.value:
        return SafetyBlockReason.INSUFFICIENT_EVIDENCE
    return SafetyBlockReason.OTHER_BLOCK
