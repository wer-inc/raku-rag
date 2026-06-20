"""T032 — POST /v1/manufacturing/trouble-cases/search SHAPE contract (US3; contracts/mfg-openapi.md §C).

Response-shape contract for the NEW similar-trouble-case endpoint (FR-MFG-008/009). It asserts the
shape of the result of the in-memory ``ManufacturingSystem`` trouble-case entrypoint: a list of
similar past ``TroubleCase`` matches, each carrying its FailureMode (cause), its Countermeasures
SPLIT into a provisional vs permanent axis, a recurrence-prevention note, and citations that carry
the 001 approval provenance (``approval_status``).

This is the SHAPE axis only. The load-bearing behaviour — (a) Hard Rule 4: a past-case Countermeasure
is labelled candidate/past-example even when ``measure_class=permanent`` and is never a definitive
work order; (b) ACL: a confidential TroubleCase never leaks to an unauthorized user, routed through
the SAME US6 ``grant_scope``/``acl_mapping`` seam + the 001 retrieval PRE-filter — is pinned by T033
(test_trouble_cases.py).

Entrypoint contract the stage-2 ``ManufacturingSystem`` must satisfy (analog of .answer/.search/
.generate_draft; mirrors contracts/mfg-openapi.md §C and contracts/mfg-interfaces.md §5 —
TroubleCaseRetriever.find_similar):

  register_trouble_case(*, tenant_id, collection_id, source_document_id, text, metadata,
                        trouble_case, failure_mode=None, countermeasures=(),
                        recurrence_prevention=None, source_id="src") -> None
      Seed a past TroubleCase: ingest the source report body via the REUSED 001 ingestion path (so
      its TroubleCase-derived chunks are retrievable AND subject to the 001 ACL PRE-filter) and
      register the TroubleCase/FailureMode/Countermeasure relation graph + recurrence note.

  search_trouble_cases(principal, symptom_query, *, collection_id=None,
                       manufacturing_filters=None, top_k=None) -> TroubleCaseSearchResponse
      POST /v1/manufacturing/trouble-cases/search. Finds similar past TroubleCases via the 001
      RetrievalService (ACL pre-filter) and resolves each to its FailureMode + split Countermeasures
      + recurrence note + citations. Result fields (contracts §C res 200):
        .status: "ok" | "insufficient_evidence"
        .results: tuple[TroubleCaseMatch, ...]
        .correlation_id: str
      Each TroubleCaseMatch:
        .trouble_case_id / .symptom / .equipment_id / .process_id
        .failure_mode: object with .name / .description (or None)
        .countermeasures: object with .provisional (tuple) and .permanent (tuple) — the
            measure_class axis kept SEPARATE (G4, FR-MFG-008). Each item carries .measure_id /
            .description / .type / .measure_class / .label.
        .recurrence_prevention: str | None
        .citations: tuple of citations, each with .approval_status (+ effective_date / approval_source)

TDD: RED now because ``raku_rag.manufacturing.app.ManufacturingSystem`` has no trouble-case
entrypoints yet (missing-impl: AttributeError on register_trouble_case / search_trouble_cases), NOT
an unrelated import error. Assertion style mirrors tests/manufacturing/test_drafts_contract.py.

stdlib only. Authoritative: spec FR-MFG-008/009, Hard Rule 4; quickstart S5; contracts/mfg-openapi.md
§C; contracts/mfg-interfaces.md §5; data-model §D.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.domain.entities import (
    Countermeasure,
    CountermeasureType,
    FailureMode,
    MeasureClass,
    TroubleCase,
)
from tests.manufacturing.helpers import T, claims, fresh, mfg_meta

# A symptom report body that the symptom query overlaps with (so 001 retrieval surfaces it).
TC_BODY = (
    "Trouble report: the gearbox showed vibration increase and abnormal noise during the night "
    "shift. Root cause traced to bearing wear. Provisional countermeasure: reduce feed rate and "
    "monitor. Permanent countermeasure: replace the bearing and add a vibration sensor. "
    "Recurrence prevention: add the bearing to the periodic replacement schedule."
)
SYMPTOM_QUERY = "振動増加 異音 vibration increase abnormal noise gearbox"


def _seed_one_case(sys) -> None:
    """Register one past TroubleCase (FailureMode cause + provisional & permanent Countermeasures)."""
    sys.register_trouble_case(
        tenant_id=T,
        collection_id="c",
        source_document_id="tr_doc_1",
        text=TC_BODY,
        metadata=mfg_meta(tenant_id=T, document_id="tr_doc_1"),
        trouble_case=TroubleCase(
            tenant_id=T,
            trouble_case_id="tc_1",
            symptom="振動増加＋異音",
            equipment_id="eq_3",
            process_id="pr_1",
            failure_mode_id="fm_1",
            source_document_id="tr_doc_1",
        ),
        failure_mode=FailureMode(
            tenant_id=T, failure_mode_id="fm_1", name="軸受摩耗", description="bearing wear"
        ),
        countermeasures=(
            Countermeasure(
                tenant_id=T,
                measure_id="m_prov",
                trouble_case_id="tc_1",
                description="reduce feed rate and monitor",
                measure_class=MeasureClass.PROVISIONAL,
                source_document_id="tr_doc_1",
            ),
            Countermeasure(
                tenant_id=T,
                measure_id="m_perm",
                trouble_case_id="tc_1",
                description="replace the bearing and add a vibration sensor",
                measure_class=MeasureClass.PERMANENT,
                source_document_id="tr_doc_1",
            ),
        ),
        recurrence_prevention="add the bearing to the periodic replacement schedule",
    )


def _status_value(obj) -> str:
    return getattr(obj.status, "value", obj.status)


def _enum_value(v):
    return getattr(v, "value", v)


class TestTroubleCaseSearchResponseShape(unittest.TestCase):
    """POST /v1/manufacturing/trouble-cases/search response shape (contracts §C)."""

    def setUp(self) -> None:
        self.sys = fresh()
        _seed_one_case(self.sys)
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    # --- top-level envelope -----------------------------------------------------------------------
    def test_response_envelope_has_status_results_correlation(self) -> None:
        resp = self.sys.search_trouble_cases(self.op, SYMPTOM_QUERY)
        self.assertIn(_status_value(resp), ("ok", "insufficient_evidence"))
        self.assertIsInstance(resp.results, tuple)
        self.assertIsInstance(resp.correlation_id, str)

    def test_similar_case_is_listed(self) -> None:
        resp = self.sys.search_trouble_cases(self.op, SYMPTOM_QUERY)
        self.assertEqual(
            _status_value(resp), "ok", "seeded similar case should be retrievable (S5)"
        )
        self.assertTrue(resp.results, "must list at least the seeded similar TroubleCase")
        self.assertTrue(
            any(m.trouble_case_id == "tc_1" for m in resp.results),
            "the seeded similar TroubleCase must appear in results",
        )

    # --- each match carries cause / countermeasure-split / recurrence / citation ------------------
    def test_match_carries_cause_failure_mode(self) -> None:
        m = self._match(self.sys.search_trouble_cases(self.op, SYMPTOM_QUERY))
        self.assertEqual(m.symptom, "振動増加＋異音")
        self.assertEqual(m.equipment_id, "eq_3")
        self.assertEqual(m.process_id, "pr_1")
        self.assertIsNotNone(
            m.failure_mode, "the FailureMode (cause) must be resolved on the match"
        )
        self.assertEqual(m.failure_mode.name, "軸受摩耗")
        self.assertTrue(
            m.failure_mode.description, "FailureMode description (cause) must be present"
        )

    def test_match_splits_provisional_and_permanent_countermeasures(self) -> None:
        # G4 / FR-MFG-008: provisional vs permanent shown as a SEPARATE measure_class axis.
        m = self._match(self.sys.search_trouble_cases(self.op, SYMPTOM_QUERY))
        cm = m.countermeasures
        self.assertTrue(
            hasattr(cm, "provisional"), "countermeasures must expose a .provisional split"
        )
        self.assertTrue(hasattr(cm, "permanent"), "countermeasures must expose a .permanent split")
        self.assertTrue(
            cm.provisional, "the provisional countermeasure must be in the provisional bucket"
        )
        self.assertTrue(
            cm.permanent, "the permanent countermeasure must be in the permanent bucket"
        )
        # each bucket only holds its own measure_class
        for c in cm.provisional:
            self.assertEqual(_enum_value(c.measure_class), MeasureClass.PROVISIONAL.value)
        for c in cm.permanent:
            self.assertEqual(_enum_value(c.measure_class), MeasureClass.PERMANENT.value)

    def test_every_countermeasure_carries_candidate_reference_label(self) -> None:
        # FR-MFG-009 / Hard Rule 4: each displayed countermeasure carries a candidate/reference label
        # and type — never presented as a definitive work instruction (shape axis; behaviour in T033).
        m = self._match(self.sys.search_trouble_cases(self.op, SYMPTOM_QUERY))
        all_cms = tuple(m.countermeasures.provisional) + tuple(m.countermeasures.permanent)
        self.assertTrue(all_cms, "match must carry at least one countermeasure")
        for c in all_cms:
            self.assertTrue(
                getattr(c, "label", None), "every countermeasure must carry a display label"
            )
            self.assertEqual(
                _enum_value(c.type),
                CountermeasureType.CANDIDATE.value,
                "a past-case countermeasure's display type is candidate (never a definitive order)",
            )

    def test_match_carries_recurrence_prevention(self) -> None:
        m = self._match(self.sys.search_trouble_cases(self.op, SYMPTOM_QUERY))
        self.assertTrue(
            m.recurrence_prevention, "the recurrence-prevention note must be present on the match"
        )

    def test_match_citations_carry_approval_status(self) -> None:
        m = self._match(self.sys.search_trouble_cases(self.op, SYMPTOM_QUERY))
        self.assertTrue(m.citations, "a similar case must be cited (出典つき, contracts §C)")
        c = m.citations[0]
        # contracts §C: citation carries 001 fields + approval_status.
        self.assertEqual(c.document_id, "tr_doc_1")
        self.assertEqual(c.approval_status, "approved")
        self.assertEqual(c.effective_date, "2026-01-10")
        self.assertEqual(c.approval_source, "imported")

    # --- helper -----------------------------------------------------------------------------------
    def _match(self, resp):
        self.assertTrue(resp.results, "expected at least one similar TroubleCase")
        for m in resp.results:
            if m.trouble_case_id == "tc_1":
                return m
        self.fail("seeded TroubleCase tc_1 not present in results")


if __name__ == "__main__":
    unittest.main()
