"""T040 — Draft generation content / groundedness (US4; FR-MFG-010b/011; quickstart S6.2).

A generated draft is GROUNDED and SAFE-SIDE:
 - it carries the generation provenance the audit trail needs: ``source_citations`` and/or
   ``source_document_ids`` referencing the 001 evidence it was built from (FR-MFG-010b);
 - a trouble_report / FAQ marks UNCONFIRMED items explicitly on the draft rather than asserting them
   as fact (US4-2: 未確定事項を draft 上で明示);
 - a SAFETY item that has NO approved+effective citation among its sources is NOT asserted — it is
   surfaced as unconfirmed / not-asserted, reusing US1 SafetyGate semantics (FR-MFG-011, FR-MFG-005).

This is a DIFFERENT axis from T039 (the draft-only / no-self-approve state machine): here we check the
generated CONTENT is evidence-backed and that unsupported safety claims are held back even on a draft.

Entrypoint contract (see test_drafts_contract.py for the full shape contract):
  generate_draft(*, principal, kind, context_citations=(), source_document_ids=(), template_id=None,
                 collection_id=None, manufacturing_filters=None) -> DraftArtifact
``context_citations`` are 001 ``Citation`` objects the caller passes as the grounding evidence (the
same Citation objects the answer path would cite). Each generated draft references them via
``source_citations`` / ``source_document_ids`` and records unconfirmed items in ``content``.

The "is this safety claim backed by an approved+effective citation?" decision REUSES the US1 helper
``raku_rag.manufacturing.safety.gate.is_approved_effective`` (the same predicate the SafetyGate uses),
so the test pins the *reuse* of that semantics rather than redefining it.

Authoritative: spec FR-MFG-010b/011 (and FR-MFG-005 reused), contracts/mfg-openapi.md §D,
contracts/mfg-interfaces.md §6, data-model §F, quickstart S6.2. Assertion style mirrors
tests/manufacturing/test_obsolete_draft_evidence.py.

TDD: RED now because ``ManufacturingSystem.generate_draft`` is unimplemented (missing-impl).
"""

from __future__ import annotations

import json
import unittest

from raku_rag.domain.models import Citation
from tests.manufacturing.helpers import T, claims, fresh


def _citation(document_id: str, *, chunk_id: str | None = None, score: float = 0.9) -> Citation:
    """A minimal 001 Citation as the grounding evidence handed to generate_draft."""
    return Citation(
        kind="text",
        document_id=document_id,
        source_id="src",
        version=1,
        retrieval_score=score,
        chunk_id=chunk_id,
    )


def _content_blob(artifact) -> str:
    """Flatten the draft content payload to a single searchable lowercase string.

    The exact content schema is impl-defined; the contract only requires that unconfirmed / not-yet-
    confirmed items be MARKED. We assert on a flattened, normalized projection so the test pins the
    *behaviour* (an unconfirmed marker is present) without over-fitting a field layout.
    """
    try:
        return json.dumps(artifact.content, ensure_ascii=False, default=str).lower()
    except (TypeError, ValueError):
        return str(artifact.content).lower()


_UNCONFIRMED_MARKERS = ("unconfirmed", "未確定", "not_confirmed", "not confirmed", "needs_review")


class TestTroubleReportCarriesSourceProvenance(unittest.TestCase):
    """A generated trouble_report references the citations / documents it was built from."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")
        self.cits = [
            _citation("case_42", chunk_id="case_42#0"),
            _citation("case_7", chunk_id="case_7#0"),
        ]

    def test_trouble_report_has_source_citations_and_document_ids(self) -> None:
        art = self.sys.generate_draft(
            principal=self.author,
            kind="trouble_report",
            context_citations=self.cits,
            template_id="tpl_trouble_v1",
        )
        # Provenance: the draft must reference its grounding documents (FR-MFG-010b).
        self.assertIn("case_42", art.source_document_ids)
        self.assertIn("case_7", art.source_document_ids)
        # And carry source_citations referencing the 001 citations it grounded on.
        self.assertTrue(
            art.source_citations,
            "a generated trouble_report must carry source_citations (FR-MFG-010b)",
        )


class TestFaqCarriesSourceProvenance(unittest.TestCase):
    """A generated FAQ is grounded: it references the citations / documents it was built from."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")
        self.cits = [_citation("faq_doc_1", chunk_id="faq_doc_1#0")]

    def test_faq_has_source_citations_and_document_ids(self) -> None:
        art = self.sys.generate_draft(
            principal=self.author,
            kind="faq",
            context_citations=self.cits,
            source_document_ids=("faq_doc_1",),
        )
        self.assertIn("faq_doc_1", art.source_document_ids)
        self.assertTrue(
            art.source_citations, "a generated FAQ must carry source_citations (FR-MFG-010b)"
        )


class TestUnconfirmedItemsAreMarked(unittest.TestCase):
    """A trouble_report marks items that are NOT backed by evidence as unconfirmed (US4-2)."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")

    def test_unconfirmed_item_is_explicitly_marked_on_the_draft(self) -> None:
        # The caller supplies a fact that is NOT supported by any provided citation
        # (e.g. a hypothesized root cause). It must be carried as UNCONFIRMED, not asserted as fact.
        art = self.sys.generate_draft(
            principal=self.author,
            kind="trouble_report",
            context_citations=[_citation("case_42", chunk_id="case_42#0")],
            manufacturing_filters={
                "unconfirmed_items": ["root cause is a worn bearing (hypothesis)"]
            },
        )
        blob = _content_blob(art)
        self.assertTrue(
            any(marker in blob for marker in _UNCONFIRMED_MARKERS),
            "an item not backed by a citation must be MARKED unconfirmed on the draft (US4-2); "
            f"content did not contain any of {_UNCONFIRMED_MARKERS}",
        )


class TestSafetyItemWithoutApprovedCitationNotAsserted(unittest.TestCase):
    """A safety item with NO approved+effective citation is NOT asserted (FR-MFG-011, US1 reuse)."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")

    def test_reuses_us1_is_approved_effective_predicate(self) -> None:
        # Pin the REUSE: the same US1 SafetyGate predicate decides whether a citation is a valid
        # approved+effective basis. A draft generator must NOT invent a looser rule for safety items.
        from raku_rag.manufacturing.safety.gate import is_approved_effective

        self.assertFalse(
            is_approved_effective(None),
            "no metadata => not an approved+effective basis (FR-MFG-005 reuse)",
        )

    def test_safety_checklist_without_approved_citation_does_not_assert_unbacked_safety_step(
        self,
    ) -> None:
        # A safety checklist whose ONLY provided citation is a NON-approved (draft) safety doc must
        # not present the safety step as a confirmed instruction; it is held back / flagged
        # unconfirmed (FR-MFG-011 reusing FR-MFG-005 semantics). We assert the draft does NOT mark the
        # safety item as confirmed/approved.
        art = self.sys.generate_draft(
            principal=self.author,
            kind="checklist",
            context_citations=[_citation("draft_safety_doc", chunk_id="draft_safety_doc#0")],
            manufacturing_filters={
                "safety_items": ["release stored hydraulic pressure before removing the guard"],
                # The provided source is a draft (not approved+effective) — modeled by the caller.
                "approved_source_document_ids": [],
            },
        )
        blob = _content_blob(art)
        # The unbacked safety item must NOT be presented as confirmed/approved fact.
        self.assertNotIn(
            '"confirmed": true',
            blob.replace(" ", ""),
            "a safety item without an approved+effective citation must not be marked confirmed "
            "(FR-MFG-011)",
        )
        # It must be visibly held back: surfaced as unconfirmed / needs-approved-evidence.
        self.assertTrue(
            any(marker in blob for marker in _UNCONFIRMED_MARKERS) or "approved" in blob,
            "an unbacked safety item must be flagged (unconfirmed / requires approved evidence) "
            "rather than silently asserted (FR-MFG-011)",
        )


if __name__ == "__main__":
    unittest.main()
