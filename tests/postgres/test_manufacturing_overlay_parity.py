"""Tier B (real Postgres) — P1-1: the manufacturing safety overlay runs over the DEPLOYED
ProductionSystem, resolving ManufacturingDocumentMetadata from the persisted ``Document.metadata``
jsonb (``to_mapping()`` -> jsonb -> ``from_mapping``).

Closes the PR-003 remaining step: previously the overlay was only exercised over the in-memory
MvpSystem (Tier A). This proves, on real Postgres+pgvector, that (a) ``ProductionSystem.ingest_
manufacturing`` persists the mfg metadata in a jsonb-safe form, (b) the registry resolver reads it back,
and (c) the high-risk safety gate FIRES over the deployed path (a draft-only high-risk corpus is
blocked; an approved+effective corpus answers — no over-block).

Discoverable by the normal suite but SKIPPED unless a Postgres is reachable (mirrors
``tests/postgres/test_production_smoke.py``), so Tier A stays Docker-free. Runs for real in CI
``gate.yml`` tier-b (``scripts/gate.sh b`` with ``POSTGRES_URL`` set).
"""

from __future__ import annotations

import os
import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.wiring import (
    build_manufacturing_answer_service,
    registry_mfg_meta_resolver,
)

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")

_HIGH_RISK_QUERY = "How do I disassemble the press safely?"
_SAFETY_TEXT = (
    "To disassemble the press, first stop the machine, apply lockout tagout, and release the stored "
    "hydraulic pressure before removing any guard."
)


def _postgres_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'chunks'")
                return cur.fetchone() is not None
    except Exception:
        return False


def _meta(tenant: str, document_id: str, status: ApprovalStatus, effective):
    return ManufacturingDocumentMetadata(
        tenant_id=tenant,
        document_id=document_id,
        approval_status=status,
        effective_date=effective,
        document_kind=DocumentKind.WORK_INSTRUCTION,
        safety_category="lockout_tagout",
        hazard_tags=("設備停止", "分解", "高圧"),
    )


@unittest.skipUnless(_postgres_available(), "Postgres not reachable (Tier B / local-only)")
class TestManufacturingOverlayPostgresParity(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.production import ProductionSystem

        self.sys = ProductionSystem(DSN, reset=True)
        self.addCleanup(self.sys.close)
        self.T = "mfg_tier_b"

    def _overlay_answer(self):
        from tests.helpers import claims

        overlay = build_manufacturing_answer_service(self.sys)
        profile = self.sys.profiles.resolve(None)
        ans, classification, decision, _cands = overlay.answer(
            claims(self.T, "op"), _HIGH_RISK_QUERY, profile
        )
        return ans

    def test_resolver_roundtrips_mfg_metadata_through_postgres_jsonb(self) -> None:
        # to_mapping() -> Postgres jsonb -> from_mapping(): the persisted Document.metadata must
        # reconstruct the typed metadata over the deployed registry resolver.
        self.sys.ingest_manufacturing(
            tenant_id=self.T,
            collection_id="c",
            document_id="approved_doc",
            text=_SAFETY_TEXT,
            metadata=_meta(self.T, "approved_doc", ApprovalStatus.APPROVED, "2026-01-10"),
        )
        resolved = registry_mfg_meta_resolver(self.sys)(self.T, "approved_doc")
        self.assertIsNotNone(resolved, "mfg metadata must round-trip from Postgres jsonb")
        self.assertEqual(resolved.approval_status, ApprovalStatus.APPROVED)
        self.assertEqual(resolved.effective_date, "2026-01-10")
        self.assertEqual(resolved.safety_category, "lockout_tagout")
        self.assertEqual(resolved.hazard_tags, ("設備停止", "分解", "高圧"))

    def test_high_risk_draft_only_is_blocked_over_postgres(self) -> None:
        # A high-risk query with only a DRAFT source must NOT assert over the deployed path: the gate
        # reads the (jsonb-persisted) DRAFT status and demotes/blocks. Proves the safety gate fires
        # over ProductionSystem, not only the in-memory MvpSystem.
        self.sys.ingest_manufacturing(
            tenant_id=self.T,
            collection_id="c",
            document_id="draft_doc",
            text=_SAFETY_TEXT,
            metadata=_meta(self.T, "draft_doc", ApprovalStatus.DRAFT, None),
        )
        self.sys.grant(self.T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        ans = self._overlay_answer()
        self.assertTrue(ans.high_risk, "the disassemble-press query must classify high-risk")
        self.assertNotEqual(
            ans.status, "ok", "a high-risk answer backed only by a DRAFT source must not assert"
        )
        for c in ans.citations:
            self.assertNotEqual(getattr(c, "approval_status", None), "draft")

    def test_high_risk_approved_answers_over_postgres(self) -> None:
        # No-over-block positive control: an APPROVED+effective source still answers a high-risk query
        # over the deployed Postgres path (proves the demotion is not a degenerate always-block).
        self.sys.ingest_manufacturing(
            tenant_id=self.T,
            collection_id="c",
            document_id="approved_doc",
            text=_SAFETY_TEXT,
            metadata=_meta(self.T, "approved_doc", ApprovalStatus.APPROVED, "2026-01-10"),
        )
        self.sys.grant(self.T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        ans = self._overlay_answer()
        self.assertTrue(ans.high_risk)
        self.assertEqual(
            ans.status, "ok", "an approved+effective source must answer the high-risk query"
        )
        self.assertTrue(ans.citations, "an ok high-risk answer must carry a citation")
        self.assertEqual(ans.citations[0].approval_status, "approved")


if __name__ == "__main__":
    unittest.main()
