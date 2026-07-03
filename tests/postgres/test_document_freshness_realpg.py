"""★G4 Tier B — document freshness columns + metadata round-trip over real Postgres.

Skipped unless a Postgres with the 0024 migration applied is reachable (same conditional-skip
posture as test_query_trace_realpg). Verifies:
  - the 0024 columns (owner / review_cycle_days / last_verified_at) exist on
    manufacturing_document_metadata and round-trip through an RLS-scoped INSERT/SELECT,
  - the freshness fields survive the deployed jsonb round-trip (Document.metadata) that the
    manufacturing overlay actually reads (ingest_manufacturing -> get_mfg_meta), and the
    dashboard/KPI views derive review_overdue from them.
"""

from __future__ import annotations

import os
import unittest
import uuid

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")


def _freshness_columns_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'manufacturing_document_metadata' "
                    "AND column_name IN ('owner', 'review_cycle_days', 'last_verified_at')"
                )
                return (cur.fetchone() or (0,))[0] == 3
    except Exception:
        return False


@unittest.skipUnless(
    _freshness_columns_available(),
    "Postgres with 0024_document_freshness not reachable (Tier B / local-only)",
)
class TestDocumentFreshnessRealPg(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.production import ProductionSystem

        self.sys = ProductionSystem(DSN, reset=True)
        self.addCleanup(self.sys.close)

    def test_0024_columns_round_trip_under_tenant_rls(self) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        metadata_id = f"freshness-test-{uuid.uuid4().hex[:12]}"
        _use_tenant(self.sys._conn, "tenant_a")
        with self.sys._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO manufacturing_document_metadata "
                "(metadata_id, tenant_id, document_id, document_kind, "
                " owner, review_cycle_days, last_verified_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    metadata_id,
                    "tenant_a",
                    "doc-freshness-1",
                    "work_instruction",
                    "press-maint",
                    90,
                    "2026-03-01",
                ),
            )
            cur.execute(
                "SELECT owner, review_cycle_days, last_verified_at "
                "FROM manufacturing_document_metadata WHERE metadata_id = %s",
                (metadata_id,),
            )
            row = cur.fetchone()
            # Clean up: the shared local DB outlives this run.
            cur.execute(
                "DELETE FROM manufacturing_document_metadata WHERE metadata_id = %s",
                (metadata_id,),
            )
        self.assertIsNotNone(row)
        owner, cycle, last_verified = row
        self.assertEqual(owner, "press-maint")
        self.assertEqual(cycle, 90)
        self.assertEqual(str(last_verified), "2026-03-01")

    def test_freshness_fields_survive_jsonb_round_trip_and_drive_overdue(self) -> None:
        from datetime import date

        from raku_rag.domain.models import IdentityClaims
        from raku_rag.manufacturing.domain.freshness import is_review_overdue
        from raku_rag.manufacturing.domain.metadata import (
            ApprovalStatus,
            ManufacturingDocumentMetadata,
        )
        from raku_rag.production import build_manufacturing_system_for_base

        mfg = build_manufacturing_system_for_base(self.sys)
        meta = ManufacturingDocumentMetadata(
            tenant_id="tenant_a",
            document_id="doc-fresh-rt",
            approval_status=ApprovalStatus.APPROVED,
            effective_date="2026-01-10",
            owner="press-maint",
            review_cycle_days=90,
            last_verified_at="2026-03-01",
        )
        mfg.ingest_manufacturing(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc-fresh-rt",
            text="Torque spec sheet for the press line bracket assembly.",
            metadata=meta,
        )

        # The overlay resolver reads the registry Document.metadata jsonb on every call — the
        # deployed round-trip path (production.py attach_manufacturing_metadata / from_mapping).
        restored = mfg.get_mfg_meta("tenant_a", "doc-fresh-rt")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.owner, "press-maint")
        self.assertEqual(restored.review_cycle_days, 90)
        self.assertEqual(restored.last_verified_at, "2026-03-01")
        # due 2026-05-30 < 2026-07-01 -> the derived review-overdue flag fires post round-trip.
        self.assertTrue(is_review_overdue(restored, today=date(2026, 7, 1)))

        # And the admin KPI view derives the overdue count from the same metadata.
        admin = IdentityClaims(tenant_id="tenant_a", user_id="admin-1", roles=("admin",))
        kpi = mfg.kpi(admin, format="json")
        self.assertGreaterEqual(kpi["review_overdue_document_count"], 1)
        self.assertIn(
            "doc-fresh-rt",
            [row["document_id"] for row in kpi["review_overdue_documents"]],
        )


if __name__ == "__main__":
    unittest.main()
