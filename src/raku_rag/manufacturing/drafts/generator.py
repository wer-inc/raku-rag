"""T041 — DraftGenerator: build a DraftArtifact (US4; FR-MFG-010/010b/011, Hard Rule 1).

Generates one of the five draft kinds (checklist / trouble_report / quality_report / training / faq)
from 001 grounding evidence. The result is ALWAYS ``status=draft`` and ``created_by=ai`` — the
generator NEVER auto-approves and NEVER emits an already-approved artifact (Hard Rule 1, SC-MFG-007).
``approved`` is only reachable via the reviewer ``ReviewWorkflow`` (review.py).

Grounding / safe-side content (FR-MFG-010b/011, reusing the US1 SafetyGate semantics):
  - the draft references the 001 ``Citation`` objects it was built from via ``source_citations`` and
    the union of those citation document_ids + any explicitly-passed ``source_document_ids``;
  - UNCONFIRMED items (caller hypotheses not backed by a citation) are MARKED on ``content`` rather
    than asserted as fact (US4-2: 未確定事項を draft 上で明示);
  - a SAFETY item is only marked ``confirmed`` when it is backed by an approved+effective citation —
    decided by REUSING ``raku_rag.manufacturing.safety.gate.is_approved_effective`` (FR-MFG-005). With
    no such evidence the item is held back as ``needs_review`` / ``needs approved evidence``.

``content`` is always ``json.dumps(default=str)``-serializable (stdlib only).
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Sequence

from raku_rag.domain.models import Citation, IdentityClaims
from raku_rag.manufacturing.domain.draft import (
    CreatedBy,
    DraftArtifact,
    DraftStatus,
    DraftType,
)
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.manufacturing.safety.gate import is_approved_effective

GetMfgMeta = Callable[[str, str], ManufacturingDocumentMetadata | None]

# The unconfirmed marker the draft uses for items not backed by approved+effective evidence.
_UNCONFIRMED = "needs_review"


def _citation_doc_ids(citations: Sequence[Citation]) -> tuple[str, ...]:
    """Ordered, de-duplicated document_ids referenced by the grounding citations."""
    seen: list[str] = []
    for c in citations:
        if c.document_id and c.document_id not in seen:
            seen.append(c.document_id)
    return tuple(seen)


def _citation_ref(c: Citation) -> str:
    """A stable string reference to a 001 Citation (DraftArtifact.source_citations is str refs)."""
    return c.chunk_id or f"{c.document_id}#0"


def coerce_kind(kind: DraftType | str) -> DraftType:
    """Accept either a ``DraftType`` or its string value (contracts §D kind is a string)."""
    if isinstance(kind, DraftType):
        return kind
    return DraftType(kind)


class DraftGenerator:
    """Concrete DraftGenerator (structurally satisfies interfaces.DraftGenerator).

    A reviewer action is the only way past ``draft`` — this class deliberately never sets a status
    other than ``DraftStatus.DRAFT`` and never sets reviewer fields.
    """

    def __init__(
        self,
        *,
        get_mfg_meta: GetMfgMeta | None = None,
        today: date | None = None,
    ) -> None:
        self._get_mfg_meta = get_mfg_meta
        self._today = today

    def generate(
        self,
        *,
        artifact_id: str,
        tenant_id: str,
        kind: DraftType | str,
        actor: IdentityClaims,
        created_at: str,
        context_citations: Sequence[Citation] = (),
        source_document_ids: Sequence[str] = (),
        template_id: str | None = None,
        collection_id: str | None = None,
        manufacturing_filters: dict | None = None,
    ) -> DraftArtifact:
        """Build a DraftArtifact. ALWAYS ``status=draft`` + ``created_by=ai`` (Hard Rule 1)."""
        draft_type = coerce_kind(kind)
        citations = tuple(context_citations or ())

        # Provenance: union of citation document_ids + explicitly-passed ids (ordered, de-duped).
        doc_ids: list[str] = list(_citation_doc_ids(citations))
        for d in source_document_ids or ():
            if d and d not in doc_ids:
                doc_ids.append(d)

        source_citations = tuple(_citation_ref(c) for c in citations)

        content = self._build_content(
            draft_type=draft_type,
            tenant_id=tenant_id,
            citations=citations,
            manufacturing_filters=manufacturing_filters or {},
        )

        return DraftArtifact(
            tenant_id=tenant_id,
            artifact_id=artifact_id,
            type=draft_type,
            collection_id=collection_id,
            # CENTRAL SAFETY INVARIANT: generator output is always a draft authored by ai.
            status=DraftStatus.DRAFT,
            created_by=CreatedBy.AI,
            created_at=created_at,
            source_citations=source_citations,
            source_document_ids=tuple(doc_ids),
            template_id=template_id,
            content=content,
        )

    # --- content (grounded + safe-side; FR-MFG-010b/011) ------------------------------------------
    def _build_content(
        self,
        *,
        draft_type: DraftType,
        tenant_id: str,
        citations: Sequence[Citation],
        manufacturing_filters: dict,
    ) -> dict:
        """Assemble the JSON-serializable draft body, marking unconfirmed/safety items safe-side."""
        content: dict = {
            "kind": draft_type.value,
            # The whole artifact is a draft pending review — make that explicit in the body too.
            "notice": (
                "本ドラフトはレビュー必須です。reviewer の approve まで正式公開物ではありません。"
            ),
            "evidence_citations": [_citation_ref(c) for c in citations],
            "items": [],
        }

        # US4-2: caller-supplied hypotheses with no citation are surfaced as UNCONFIRMED, not fact.
        for text in manufacturing_filters.get("unconfirmed_items", ()) or ():
            content["items"].append(
                {
                    "kind": "unconfirmed",
                    "text": text,
                    "confirmed": False,
                    "status": _UNCONFIRMED,
                }
            )

        # FR-MFG-011 (reusing FR-MFG-005 / US1 SafetyGate): a safety step is only "confirmed" when
        # an approved+effective citation backs it. Decide via the SAME predicate the SafetyGate uses.
        safety_items = manufacturing_filters.get("safety_items", ()) or ()
        if safety_items:
            backed = self._has_approved_effective_evidence(
                tenant_id=tenant_id,
                citations=citations,
            )
            for text in safety_items:
                item = {
                    "kind": "safety",
                    "text": text,
                    "confirmed": bool(backed),
                }
                if not backed:
                    # Held back: not asserted as fact; needs an approved+effective basis.
                    item["status"] = _UNCONFIRMED
                    item["requires_approved_evidence"] = True
                content["items"].append(item)

        return content

    def _has_approved_effective_evidence(
        self,
        *,
        tenant_id: str,
        citations: Sequence[Citation],
    ) -> bool:
        """True iff some grounding citation is an approved+effective basis (US1 reuse, FR-MFG-005).

        The approved/effective decision is made SERVER-SIDE ONLY, via the ManufacturingDocumentMetadata
        resolver, reusing ``is_approved_effective`` — no looser local rule. The caller's request body
        must NOT be able to self-attest a document as approved: the prior ``approved_source_document_ids``
        short-circuit is intentionally removed (0017-C), so this no longer takes ``manufacturing_filters``
        at all. With no resolver wired, nothing is treated as approved (fail-safe).
        """
        if self._get_mfg_meta is None:
            return False
        for c in citations:
            meta = self._get_mfg_meta(tenant_id, c.document_id)
            if is_approved_effective(meta, today=self._today):
                return True
        return False
