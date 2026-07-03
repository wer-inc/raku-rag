"""★G4 — document freshness (goal.md §1-4 document lifecycle).

Covers the three new layers this feature adds:
  1. the PURE stale computation (domain/freshness.py) — review_overdue <=> last_verified_at +
     review_cycle_days < today, ONLY when both are set; boundary + garbage-input cases,
  2. the metadata round-trip — owner / review_cycle_days / last_verified_at survive
     to_mapping()/from_mapping() (the Postgres jsonb round-trip shape) and legacy mappings
     (which lack the fields) keep exact previous behaviour via safe defaults,
  3. the surfacing — KPI report / knowledge-ops dashboard expose review_overdue_document_count +
     the reference-row list, and the answer citation carries the last_verified_at / review_overdue
     trust signal (display-only; never a safety-gate input).

stdlib only.
"""

from __future__ import annotations

import unittest
from datetime import date

from raku_rag.domain.models import Citation, IdentityClaims
from raku_rag.manufacturing.api.answer_ext import ManufacturingCitation
from raku_rag.manufacturing.domain.freshness import (
    is_review_overdue,
    review_due_date,
    review_overdue_entries,
)
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)

T = "tenant_mfg"
TODAY = date(2026, 7, 1)


def _meta(document_id: str = "doc1", **kwargs) -> ManufacturingDocumentMetadata:
    return ManufacturingDocumentMetadata(tenant_id=T, document_id=document_id, **kwargs)


class ReviewOverdueComputationTest(unittest.TestCase):
    """Boundary cases of the pure stale computation (never raises, fail-open on garbage)."""

    def test_no_fields_is_never_overdue(self) -> None:
        self.assertFalse(is_review_overdue(_meta(), today=TODAY))

    def test_only_cycle_set_is_not_overdue(self) -> None:
        self.assertFalse(is_review_overdue(_meta(review_cycle_days=30), today=TODAY))

    def test_only_last_verified_set_is_not_overdue(self) -> None:
        self.assertFalse(is_review_overdue(_meta(last_verified_at="2020-01-01"), today=TODAY))

    def test_due_strictly_before_today_is_overdue(self) -> None:
        # verified 2026-03-01 + 90d => due 2026-05-30 < 2026-07-01 -> overdue.
        meta = _meta(last_verified_at="2026-03-01", review_cycle_days=90)
        self.assertTrue(is_review_overdue(meta, today=TODAY))

    def test_due_exactly_today_is_not_yet_overdue(self) -> None:
        # verified 2026-04-02 + 90d => due 2026-07-01 == today -> NOT overdue (strict <).
        meta = _meta(last_verified_at="2026-04-02", review_cycle_days=90)
        self.assertEqual(review_due_date("2026-04-02", 90), TODAY)
        self.assertFalse(is_review_overdue(meta, today=TODAY))

    def test_due_tomorrow_is_not_overdue(self) -> None:
        meta = _meta(last_verified_at="2026-04-03", review_cycle_days=90)
        self.assertFalse(is_review_overdue(meta, today=TODAY))

    def test_garbage_inputs_fail_open(self) -> None:
        self.assertIsNone(review_due_date("not-a-date", 30))
        self.assertIsNone(review_due_date("2026-01-01", 0))
        self.assertIsNone(review_due_date("2026-01-01", -5))
        self.assertIsNone(review_due_date("", 30))
        self.assertFalse(
            is_review_overdue(
                {"last_verified_at": "2020-01-01", "review_cycle_days": "abc"}, today=TODAY
            )
        )

    def test_timestamp_form_uses_date_part(self) -> None:
        self.assertEqual(review_due_date("2026-03-01T09:30:00+09:00", 90), date(2026, 5, 30))

    def test_mapping_form_is_supported(self) -> None:
        mapping = _meta(last_verified_at="2026-01-01", review_cycle_days=30).to_mapping()
        self.assertTrue(is_review_overdue(mapping, today=TODAY))

    def test_overdue_entries_shape_and_sort(self) -> None:
        metas = [
            _meta("fresh", last_verified_at="2026-06-01", review_cycle_days=90),
            _meta("late-b", owner="qa-team", last_verified_at="2026-01-01", review_cycle_days=30),
            _meta("late-a", last_verified_at="2025-12-01", review_cycle_days=30),
            _meta("no-cycle"),
            None,
        ]
        entries = review_overdue_entries(metas, today=TODAY)
        self.assertEqual([e["document_id"] for e in entries], ["late-a", "late-b"])
        self.assertEqual(
            entries[1],
            {
                "document_id": "late-b",
                "owner": "qa-team",
                "last_verified_at": "2026-01-01",
                "review_due_date": "2026-01-31",
            },
        )


class FreshnessMetadataRoundTripTest(unittest.TestCase):
    """owner / review_cycle_days / last_verified_at survive the jsonb mapping round-trip."""

    def test_round_trip_preserves_freshness_fields(self) -> None:
        meta = _meta(
            owner="maint-team",
            review_cycle_days=180,
            last_verified_at="2026-05-20",
            approval_status=ApprovalStatus.APPROVED,
            document_kind=DocumentKind.WORK_INSTRUCTION,
        )
        mapping = meta.to_mapping()
        self.assertEqual(mapping["owner"], "maint-team")
        self.assertEqual(mapping["review_cycle_days"], 180)
        self.assertEqual(mapping["last_verified_at"], "2026-05-20")
        restored = ManufacturingDocumentMetadata.from_mapping(mapping)
        self.assertEqual(restored, meta)

    def test_legacy_mapping_without_fields_gets_safe_defaults(self) -> None:
        legacy = _meta(approval_status=ApprovalStatus.APPROVED).to_mapping()
        for key in ("owner", "review_cycle_days", "last_verified_at"):
            legacy.pop(key, None)
        restored = ManufacturingDocumentMetadata.from_mapping(legacy)
        self.assertEqual(restored.owner, "")
        self.assertEqual(restored.review_cycle_days, 0)
        self.assertEqual(restored.last_verified_at, "")
        self.assertFalse(is_review_overdue(restored, today=TODAY))

    def test_garbage_cycle_value_coerces_to_zero(self) -> None:
        mapping = _meta().to_mapping()
        mapping["review_cycle_days"] = "ninety"
        self.assertEqual(ManufacturingDocumentMetadata.from_mapping(mapping).review_cycle_days, 0)
        mapping["review_cycle_days"] = -7
        self.assertEqual(ManufacturingDocumentMetadata.from_mapping(mapping).review_cycle_days, 0)


class FreshnessKpiDashboardTest(unittest.TestCase):
    """review_overdue_document_count + the overdue list reach the KPI / dashboard views."""

    def setUp(self) -> None:
        from raku_rag.manufacturing.app import ManufacturingSystem

        self.sys = ManufacturingSystem(today=TODAY)
        self.admin = IdentityClaims(tenant_id=T, user_id="admin-1", roles=("admin",))
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="overdue1",
            text="Torque spec sheet for the press line bracket assembly.",
            metadata=_meta(
                "overdue1",
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-01-10",
                owner="press-maint",
                review_cycle_days=90,
                last_verified_at="2026-03-01",  # due 2026-05-30 < 2026-07-01 -> overdue
            ),
        )
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="fresh1",
            text="Inspection checklist for the coating booth filters.",
            metadata=_meta(
                "fresh1",
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-01-10",
                owner="coating-qa",
                review_cycle_days=90,
                last_verified_at="2026-06-01",  # due 2026-08-30 -> fresh
            ),
        )

    def test_kpi_json_carries_overdue_count_and_reference_rows(self) -> None:
        kpi = self.sys.kpi(self.admin, format="json")
        self.assertEqual(kpi["review_overdue_document_count"], 1)
        self.assertEqual(
            kpi["review_overdue_documents"],
            [
                {
                    "document_id": "overdue1",
                    "owner": "press-maint",
                    "last_verified_at": "2026-03-01",
                    "review_due_date": "2026-05-30",
                }
            ],
        )

    def test_kpi_csv_export_includes_freshness_keys(self) -> None:
        csv = self.sys.kpi(self.admin, format="csv")
        self.assertIn("review_overdue_document_count", csv)
        self.assertIn("review_overdue_documents", csv)

    def test_dashboard_carries_overdue_count_and_rows(self) -> None:
        view = self.sys.knowledge_ops_dashboard(self.admin)
        self.assertEqual(view.review_overdue_document_count, 1)
        self.assertEqual(view.review_overdue_documents[0]["document_id"], "overdue1")

    def test_other_tenant_sees_no_overdue_documents(self) -> None:
        other = IdentityClaims(tenant_id="tenant_other", user_id="admin-2", roles=("admin",))
        view = self.sys.knowledge_ops_dashboard(other)
        self.assertEqual(view.review_overdue_document_count, 0)
        self.assertEqual(view.review_overdue_documents, ())


class FreshnessCitationTrustSignalTest(unittest.TestCase):
    """Citations carry 最終確認日 + the derived 要再確認 flag (display-only, additive)."""

    def _base_citation(self) -> Citation:
        return Citation(
            kind="text",
            document_id="doc1",
            source_id="src",
            version=1,
            retrieval_score=0.9,
            chunk_id="doc1:0",
        )

    def test_overdue_metadata_marks_citation(self) -> None:
        meta = _meta(last_verified_at="2026-03-01", review_cycle_days=90)
        c = ManufacturingCitation.from_base(self._base_citation(), meta, today=TODAY)
        self.assertEqual(c.last_verified_at, "2026-03-01")
        self.assertTrue(c.review_overdue)

    def test_fresh_metadata_is_not_flagged(self) -> None:
        meta = _meta(last_verified_at="2026-06-01", review_cycle_days=90)
        c = ManufacturingCitation.from_base(self._base_citation(), meta, today=TODAY)
        self.assertEqual(c.last_verified_at, "2026-06-01")
        self.assertFalse(c.review_overdue)

    def test_no_metadata_keeps_defaults(self) -> None:
        c = ManufacturingCitation.from_base(self._base_citation(), None, today=TODAY)
        self.assertIsNone(c.last_verified_at)
        self.assertFalse(c.review_overdue)

    def test_unset_freshness_fields_are_not_flagged(self) -> None:
        c = ManufacturingCitation.from_base(self._base_citation(), _meta(), today=TODAY)
        self.assertIsNone(c.last_verified_at)  # "" is normalized to None for the payload
        self.assertFalse(c.review_overdue)


if __name__ == "__main__":
    unittest.main()
