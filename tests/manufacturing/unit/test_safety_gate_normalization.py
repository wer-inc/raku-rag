"""T069 — focused unit tests for ManufacturingSafetyGate helpers (FR-MFG-005/006/030).

Tests the gate's pure helpers in isolation:
  - ``normalize_block_reason`` priority order (FR-MFG-030, 1 block = 1 primary cause),
  - ``is_effective`` effective-date validity (missing/future/malformed => invalid),
  - ``is_approved_effective`` (approved AND effective),
  - ``ManufacturingSafetyGate.evaluate`` safe-side outcomes with an injected clock.

stdlib only; additive (new file). Uses an injected ``today`` so assertions are deterministic.
"""

from __future__ import annotations

import unittest
from datetime import date

from raku_rag.domain.models import Citation
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.domain.safety import (
    HighRiskClassification,
    SafetyBlockReason,
)
from raku_rag.manufacturing.safety.gate import (
    ManufacturingSafetyGate,
    is_approved_effective,
    is_effective,
    normalize_block_reason,
)

_TODAY = date(2026, 6, 19)


def _meta(**overrides) -> ManufacturingDocumentMetadata:
    base = dict(tenant_id="t", document_id="d")
    base.update(overrides)
    return ManufacturingDocumentMetadata(**base)


def _cite(document_id: str) -> Citation:
    return Citation(
        kind="text", document_id=document_id, source_id="s", version=1, retrieval_score=0.9
    )


class TestNormalizeBlockReason(unittest.TestCase):
    """FR-MFG-030: collapse several block reasons to the single highest-priority one."""

    def test_priority_approved_citation_missing_wins(self) -> None:
        out = normalize_block_reason(
            SafetyBlockReason.OTHER_BLOCK,
            SafetyBlockReason.INSUFFICIENT_EVIDENCE,
            SafetyBlockReason.APPROVED_CITATION_MISSING,
        )
        self.assertEqual(out, SafetyBlockReason.APPROVED_CITATION_MISSING)

    def test_insufficient_evidence_beats_other_block(self) -> None:
        out = normalize_block_reason(
            SafetyBlockReason.OTHER_BLOCK, SafetyBlockReason.INSUFFICIENT_EVIDENCE
        )
        self.assertEqual(out, SafetyBlockReason.INSUFFICIENT_EVIDENCE)

    def test_single_reason_passthrough(self) -> None:
        self.assertEqual(
            normalize_block_reason(SafetyBlockReason.OTHER_BLOCK),
            SafetyBlockReason.OTHER_BLOCK,
        )

    def test_all_none_returns_none(self) -> None:
        self.assertIsNone(normalize_block_reason(None, None))

    def test_no_args_returns_none(self) -> None:
        self.assertIsNone(normalize_block_reason())


class TestIsEffective(unittest.TestCase):
    """An effective_date is valid iff set and not in the future."""

    def test_past_date_is_effective(self) -> None:
        self.assertTrue(is_effective("2026-01-01", today=_TODAY))

    def test_today_is_effective(self) -> None:
        self.assertTrue(is_effective("2026-06-19", today=_TODAY))

    def test_future_date_not_effective(self) -> None:
        self.assertFalse(is_effective("2030-01-01", today=_TODAY))

    def test_missing_date_invalid(self) -> None:
        self.assertFalse(is_effective(None, today=_TODAY))

    def test_empty_string_invalid(self) -> None:
        self.assertFalse(is_effective("", today=_TODAY))

    def test_malformed_date_fails_safe_to_invalid(self) -> None:
        self.assertFalse(is_effective("not-a-date", today=_TODAY))

    def test_iso_timestamp_prefix_is_parsed(self) -> None:
        # Only the leading YYYY-MM-DD is used, so a full ISO timestamp is accepted.
        self.assertTrue(is_effective("2026-01-01T08:30:00Z", today=_TODAY))


class TestIsApprovedEffective(unittest.TestCase):
    """A valid approved citation is approved AND has a valid effective_date."""

    def test_approved_and_effective(self) -> None:
        m = _meta(approval_status=ApprovalStatus.APPROVED, effective_date="2026-01-01")
        self.assertTrue(is_approved_effective(m, today=_TODAY))

    def test_approved_but_future_effective_invalid(self) -> None:
        m = _meta(approval_status=ApprovalStatus.APPROVED, effective_date="2030-01-01")
        self.assertFalse(is_approved_effective(m, today=_TODAY))

    def test_pending_review_not_valid_even_if_effective(self) -> None:
        m = _meta(approval_status=ApprovalStatus.PENDING_REVIEW, effective_date="2026-01-01")
        self.assertFalse(is_approved_effective(m, today=_TODAY))

    def test_none_metadata_invalid(self) -> None:
        self.assertFalse(is_approved_effective(None, today=_TODAY))


class TestGateEvaluate(unittest.TestCase):
    """End-to-end safe-side outcomes of ManufacturingSafetyGate.evaluate (deterministic clock)."""

    def setUp(self) -> None:
        self.gate = ManufacturingSafetyGate(today=_TODAY)
        self.hr = HighRiskClassification(is_high_risk=True)
        self.lr = HighRiskClassification(is_high_risk=False)

    def test_high_risk_without_approved_effective_blocks(self) -> None:
        m = _meta(approval_status=ApprovalStatus.DRAFT)
        d = self.gate.evaluate(self.hr, [_cite("d")], [m])
        self.assertTrue(d.blocked)
        self.assertEqual(d.safety_block_reason, SafetyBlockReason.APPROVED_CITATION_MISSING)
        self.assertTrue(d.requires_onsite_confirmation)
        self.assertIsNone(d.approval_status_at_use)

    def test_high_risk_with_approved_effective_allowed_but_onsite(self) -> None:
        m = _meta(approval_status=ApprovalStatus.APPROVED, effective_date="2026-01-01")
        d = self.gate.evaluate(self.hr, [_cite("d")], [m])
        self.assertFalse(d.blocked)
        self.assertTrue(d.requires_onsite_confirmation)
        self.assertEqual(d.approval_status_at_use, ApprovalStatus.APPROVED.value)

    def test_non_high_risk_draft_only_blocks_insufficient_evidence(self) -> None:
        m = _meta(approval_status=ApprovalStatus.DRAFT)
        d = self.gate.evaluate(self.lr, [_cite("d")], [m])
        self.assertTrue(d.blocked)
        self.assertEqual(d.safety_block_reason, SafetyBlockReason.INSUFFICIENT_EVIDENCE)
        self.assertFalse(d.requires_onsite_confirmation)

    def test_non_high_risk_obsolete_raises_warning(self) -> None:
        m = _meta(approval_status=ApprovalStatus.OBSOLETE)
        d = self.gate.evaluate(self.lr, [_cite("d")], [m])
        self.assertTrue(d.obsolete_warning)

    def test_non_high_risk_unclassified_evidence_is_usable_primary(self) -> None:
        # No manufacturing metadata for the cited doc => usable as primary basis, not blocked.
        d = self.gate.evaluate(self.lr, [_cite("x")], [])
        self.assertFalse(d.blocked)


if __name__ == "__main__":
    unittest.main()
