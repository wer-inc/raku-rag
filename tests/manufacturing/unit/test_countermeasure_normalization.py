"""T069 — focused unit tests for Countermeasure 2-axis display normalization (Hard Rule 4, FR-MFG-009).

Tests the pure ``normalize_countermeasure`` / ``split_countermeasures`` units in isolation:
  - a past-case countermeasure is ALWAYS displayed as ``candidate`` even when permanent (Hard Rule 4),
  - the NATURE axis (``measure_class``) is PRESERVED unchanged,
  - provisional and permanent land in SEPARATE, disjoint buckets (G4),
  - the human-readable label marks it as a past-example candidate, not a definitive work order.

stdlib only; additive (new file).
"""

from __future__ import annotations

import unittest

from raku_rag.manufacturing.domain.entities import (
    Countermeasure,
    CountermeasureType,
    MeasureClass,
)
from raku_rag.manufacturing.knowledge.trouble_cases import (
    PAST_CASE_LABEL,
    normalize_countermeasure,
    split_countermeasures,
)


def _cm(measure_id: str, measure_class: MeasureClass, **overrides) -> Countermeasure:
    base = dict(
        tenant_id="t",
        measure_id=measure_id,
        trouble_case_id="tc1",
        description="do the thing",
        measure_class=measure_class,
    )
    base.update(overrides)
    return Countermeasure(**base)


class TestNormalizeCountermeasure(unittest.TestCase):
    def test_permanent_past_case_displayed_as_candidate(self) -> None:
        # Hard Rule 4: a permanent (恒久) past-case measure is shown as a candidate, never definitive.
        cm = _cm("m1", MeasureClass.PERMANENT, type=CountermeasureType.REFERENCE)
        d = normalize_countermeasure(cm)
        self.assertEqual(d.type, CountermeasureType.CANDIDATE)

    def test_measure_class_preserved(self) -> None:
        # The NATURE axis must NOT be overwritten by the display normalization.
        cm = _cm("m1", MeasureClass.PERMANENT)
        self.assertEqual(normalize_countermeasure(cm).measure_class, MeasureClass.PERMANENT)
        cm2 = _cm("m2", MeasureClass.PROVISIONAL)
        self.assertEqual(normalize_countermeasure(cm2).measure_class, MeasureClass.PROVISIONAL)

    def test_label_is_past_case_candidate_label(self) -> None:
        d = normalize_countermeasure(_cm("m1", MeasureClass.PERMANENT))
        self.assertEqual(d.label, PAST_CASE_LABEL)
        # The label must read as a candidate / past-example reference, not an official work order.
        self.assertIn("候補", d.label)
        self.assertIn("参考", d.label)

    def test_identity_fields_carried_through(self) -> None:
        cm = _cm("m9", MeasureClass.PROVISIONAL, description="tighten the bolt")
        d = normalize_countermeasure(cm)
        self.assertEqual(d.measure_id, "m9")
        self.assertEqual(d.description, "tighten the bolt")


class TestSplitCountermeasures(unittest.TestCase):
    def test_provisional_and_permanent_in_separate_buckets(self) -> None:
        prov = _cm("p1", MeasureClass.PROVISIONAL)
        perm = _cm("q1", MeasureClass.PERMANENT)
        split = split_countermeasures((prov, perm))
        self.assertEqual([c.measure_id for c in split.provisional], ["p1"])
        self.assertEqual([c.measure_id for c in split.permanent], ["q1"])

    def test_unknown_measure_class_in_neither_bucket(self) -> None:
        unk = _cm("u1", MeasureClass.UNKNOWN)
        split = split_countermeasures((unk,))
        self.assertEqual(split.provisional, ())
        self.assertEqual(split.permanent, ())

    def test_all_displayed_measures_are_candidates(self) -> None:
        split = split_countermeasures(
            (_cm("p1", MeasureClass.PROVISIONAL), _cm("q1", MeasureClass.PERMANENT))
        )
        for c in (*split.provisional, *split.permanent):
            self.assertEqual(c.type, CountermeasureType.CANDIDATE)
            self.assertEqual(c.label, PAST_CASE_LABEL)

    def test_buckets_are_disjoint(self) -> None:
        split = split_countermeasures(
            (
                _cm("p1", MeasureClass.PROVISIONAL),
                _cm("p2", MeasureClass.PROVISIONAL),
                _cm("q1", MeasureClass.PERMANENT),
                _cm("u1", MeasureClass.UNKNOWN),
            )
        )
        prov_ids = {c.measure_id for c in split.provisional}
        perm_ids = {c.measure_id for c in split.permanent}
        self.assertEqual(prov_ids, {"p1", "p2"})
        self.assertEqual(perm_ids, {"q1"})
        self.assertEqual(prov_ids & perm_ids, set())

    def test_empty_input(self) -> None:
        split = split_countermeasures(())
        self.assertEqual(split.provisional, ())
        self.assertEqual(split.permanent, ())


if __name__ == "__main__":
    unittest.main()
