"""GAP-S2 — a source-deleted (tombstoned) document must not resurface as approved evidence in a draft.

Top risk (CLAUDE.md): deleted-content reappearance. The answer/search/trouble paths are protected
because they obtain candidates through the reused 001 retrieval pre-filter (tombstone-excluding). The
DRAFT path does NOT go through retrieval: ``DraftService`` resolves a citation's approval state via
``ManufacturingSystem.get_mfg_meta`` directly. Before the fix, ``delete_document`` tombstoned the base
store but never invalidated the manufacturing metadata resolver, so a deleted APPROVED+effective
document's stale metadata could still flip a draft SAFETY item to ``confirmed: true`` — a withdrawn /
recalled procedure reappearing as the approved basis of generated safety content.

The fix makes ``get_mfg_meta`` tombstone-aware (returns ``None`` for a deleted document); a later
restore (re-ingest) un-tombstones the registry doc and re-enables the resolver.

Assertion style mirrors tests/manufacturing/test_draft_generation.py /
tests/manufacturing/test_obsolete_draft_evidence.py.
"""

from __future__ import annotations

import json
import unittest

from raku_rag.domain.models import Citation, ScopeType, SubjectType
from raku_rag.manufacturing.domain.metadata import ApprovalStatus
from tests.manufacturing.helpers import T, claims, fresh, mfg_meta


def _citation(document_id: str, *, chunk_id: str | None = None, score: float = 0.9) -> Citation:
    return Citation(
        kind="text",
        document_id=document_id,
        source_id="src",
        version=1,
        retrieval_score=score,
        chunk_id=chunk_id,
    )


def _content_blob(artifact) -> str:
    try:
        return json.dumps(artifact.content, ensure_ascii=False, default=str).lower()
    except (TypeError, ValueError):
        return str(artifact.content).lower()


_DOC = "appr_proc"
_SAFETY_ITEM = "release stored hydraulic pressure before removing the guard"


class TestDeletedDocNotApprovedEvidenceInDraft(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        # The grounding source is APPROVED + effective (the safe baseline) and safety-categorized.
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id=_DOC,
            text="Release stored hydraulic pressure before removing the guard panel.",
            metadata=mfg_meta(
                tenant_id=T,
                document_id=_DOC,
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-01-10",
                safety_category="LOTO",
            ),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def _draft_confirmed_blob(self) -> str:
        art = self.sys.generate_draft(
            principal=self.op,
            kind="checklist",
            context_citations=[_citation(_DOC, chunk_id=f"{_DOC}#0")],
            manufacturing_filters={"safety_items": [_SAFETY_ITEM]},
        )
        return _content_blob(art).replace(" ", "")

    def test_get_mfg_meta_is_none_after_delete_and_returns_after_restore(self) -> None:
        self.assertIsNotNone(self.sys.get_mfg_meta(T, _DOC))
        self.sys.delete_document(tenant_id=T, document_id=_DOC, actor=self.op)
        self.assertIsNone(
            self.sys.get_mfg_meta(T, _DOC),
            "a tombstoned document must not resolve manufacturing metadata (GAP-S2)",
        )
        # Restore path: re-ingesting the same document un-tombstones it and re-enables the resolver.
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id=_DOC,
            text="Release stored hydraulic pressure before removing the guard panel.",
            metadata=mfg_meta(
                tenant_id=T,
                document_id=_DOC,
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-01-10",
                safety_category="LOTO",
            ),
        )
        self.assertIsNotNone(self.sys.get_mfg_meta(T, _DOC))

    def test_get_mfg_meta_reflects_out_of_band_registry_change_no_stale_cache(self) -> None:
        # 0017-D: get_mfg_meta resolves from the registry SSOT on EVERY call. An out-of-band change
        # (another instance / connector sync writes the registry document but not this process's cache)
        # must be reflected immediately — a stale APPROVED entry must not survive an obsolete change.
        from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY

        first = self.sys.get_mfg_meta(T, _DOC)  # primes any cache; seed is APPROVED
        self.assertEqual(first.approval_status, ApprovalStatus.APPROVED)
        # Mutate the registry document directly, WITHOUT going through _set_mfg_meta.
        doc = self.sys._mvp.registry.get(T, _DOC)
        doc.metadata[MFG_META_KEY] = mfg_meta(
            tenant_id=T, document_id=_DOC, approval_status=ApprovalStatus.OBSOLETE
        ).to_mapping()
        self.sys._mvp.registry.put(doc)
        self.assertEqual(
            self.sys.get_mfg_meta(T, _DOC).approval_status,
            ApprovalStatus.OBSOLETE,
            "get_mfg_meta must reflect the registry SSOT, not a stale process-local cache (0017-D)",
        )

    def test_deleted_approved_doc_does_not_confirm_a_draft_safety_item(self) -> None:
        # POSITIVE CONTROL: while the approved source is live, the safety item IS confirmable — so a
        # degenerate "never confirm" implementation cannot pass this test.
        self.assertIn(
            '"confirmed":true',
            self._draft_confirmed_blob(),
            "an APPROVED+effective source should be able to confirm a draft safety item (control)",
        )
        # Delete the source document via the reused 001 tombstone path.
        self.sys.delete_document(tenant_id=T, document_id=_DOC, actor=self.op)
        # GAP-S2: the deleted document's stale approved metadata must NOT confirm the safety item.
        self.assertNotIn(
            '"confirmed":true',
            self._draft_confirmed_blob(),
            "a deleted (tombstoned) document must not resurface as approved evidence in a draft "
            "(GAP-S2: deleted-content reappearance)",
        )


if __name__ == "__main__":
    unittest.main()
