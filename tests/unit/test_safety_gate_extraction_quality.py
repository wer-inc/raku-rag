"""ADR 018 §11.4 — extraction quality is an AND-gate on high-risk approved citations.

A citation whose extraction is only ``accepted_with_warnings`` (high_risk_citation_eligible=False)
may be retrieved, but must NOT satisfy the high-risk approved+effective citation requirement, even
when the document's manufacturing approval metadata is approved & effective. Citations with no
extraction-quality metadata (legacy) keep the prior behaviour (additive change).
"""

from __future__ import annotations

import unittest
from datetime import date

from raku_rag.domain.models import Citation
from raku_rag.manufacturing.domain.metadata import ApprovalStatus, ManufacturingDocumentMetadata
from raku_rag.manufacturing.domain.safety import HighRiskClassification, SafetyBlockReason
from raku_rag.manufacturing.safety.gate import (
    ManufacturingSafetyGate,
    citation_is_approved_effective,
)
from raku_rag.services.ingestion_quality import (
    accepted_quality_metadata,
    accepted_with_warnings_quality_metadata,
)

_TODAY = date(2026, 6, 19)


def _approved_meta() -> ManufacturingDocumentMetadata:
    return ManufacturingDocumentMetadata(
        tenant_id="t",
        document_id="d",
        approval_status=ApprovalStatus.APPROVED,
        effective_date="2026-01-01",
    )


def _cite(metadata: dict) -> Citation:
    return Citation(
        kind="text",
        document_id="d",
        source_id="s",
        version=1,
        retrieval_score=0.9,
        metadata=metadata,
    )


class ExtractionQualityHighRiskGateTest(unittest.TestCase):
    def test_accepted_citation_satisfies_high_risk(self) -> None:
        self.assertTrue(
            citation_is_approved_effective(
                _cite(accepted_quality_metadata()), _approved_meta(), today=_TODAY
            )
        )

    def test_legacy_citation_without_quality_metadata_still_satisfies(self) -> None:
        self.assertTrue(
            citation_is_approved_effective(_cite({}), _approved_meta(), today=_TODAY)
        )

    def test_accepted_with_warnings_does_not_satisfy_high_risk(self) -> None:
        self.assertFalse(
            citation_is_approved_effective(
                _cite(accepted_with_warnings_quality_metadata(reasons=("minor_mojibake",))),
                _approved_meta(),
                today=_TODAY,
            )
        )

    def test_gate_blocks_high_risk_answer_backed_only_by_warned_extraction(self) -> None:
        gate = ManufacturingSafetyGate(today=_TODAY)
        classification = HighRiskClassification(is_high_risk=True, reason_codes=("electrical",))
        decision = gate.evaluate(
            classification,
            [_cite(accepted_with_warnings_quality_metadata(reasons=("minor_mojibake",)))],
            [_approved_meta()],
        )
        self.assertTrue(decision.blocked)
        self.assertEqual(
            decision.safety_block_reason, SafetyBlockReason.APPROVED_CITATION_MISSING
        )

    def test_gate_allows_high_risk_answer_backed_by_accepted_extraction(self) -> None:
        gate = ManufacturingSafetyGate(today=_TODAY)
        classification = HighRiskClassification(is_high_risk=True, reason_codes=("electrical",))
        decision = gate.evaluate(
            classification,
            [_cite(accepted_quality_metadata())],
            [_approved_meta()],
        )
        self.assertFalse(decision.blocked)


if __name__ == "__main__":
    unittest.main()
