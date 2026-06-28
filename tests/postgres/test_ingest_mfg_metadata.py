"""Tier B (real Postgres) — P1-1 WRITE path: manufacturing metadata supplied at ingest is persisted on
the Document so the safety overlay fires for production-ingested docs (not just in-memory fixtures).

`ProductionSystem.ingest_document(..., manufacturing_metadata=...)` is the single funnel the deployed
answer-service `/internal/ingest` route calls (parsing the request's `manufacturing` block). This proves
end-to-end over real Postgres: ingest with a draft high-risk metadata -> the overlay demotes; ingest with
approved+effective -> the overlay answers; ingest without metadata -> the resolver finds none.

Skipped unless Postgres is reachable (mirrors tests/postgres/test_production_smoke.py); runs for real in
CI gate.yml tier-b.
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
class TestIngestMfgMetadataWritePath(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.production import ProductionSystem

        self.sys = ProductionSystem(DSN, reset=True)
        self.addCleanup(self.sys.close)
        self.T = "mfg_ingest_tier_b"

    def _ingest(self, document_id: str, status: ApprovalStatus, effective):
        # The deployed /internal/ingest route calls exactly this with manufacturing_metadata parsed
        # from the request's `manufacturing` block.
        return self.sys.ingest_document(
            tenant_id=self.T,
            collection_id="c",
            source_id="src",
            document_id=document_id,
            document_ref=f"inline:{document_id}",
            raw=_SAFETY_TEXT.encode("utf-8"),
            content_type="text/plain",
            manufacturing_metadata=_meta(self.T, document_id, status, effective),
        )

    def _overlay_answer(self):
        from tests.helpers import claims

        overlay = build_manufacturing_answer_service(self.sys)
        profile = self.sys.profiles.resolve(None)
        ans, _classification, _decision, _cands = overlay.answer(
            claims(self.T, "op"), _HIGH_RISK_QUERY, profile
        )
        return ans

    def test_ingest_persists_metadata_for_resolver(self) -> None:
        run = self._ingest("approved_doc", ApprovalStatus.APPROVED, "2026-01-10")
        self.assertEqual(run.status, "succeeded")
        resolved = registry_mfg_meta_resolver(self.sys)(self.T, "approved_doc")
        self.assertIsNotNone(resolved, "metadata supplied at ingest must persist on the Document")
        self.assertEqual(resolved.approval_status, ApprovalStatus.APPROVED)
        self.assertEqual(resolved.safety_category, "lockout_tagout")

    def test_idempotent_reseed_repairs_missing_metadata(self) -> None:
        document_id = "idempotent_draft_doc"
        raw = _SAFETY_TEXT.encode("utf-8")
        initial = self.sys.ingest_document(
            tenant_id=self.T,
            collection_id="c",
            source_id="src",
            document_id=document_id,
            document_ref=f"inline:{document_id}",
            raw=raw,
            content_type="text/plain",
        )
        self.assertEqual(initial.status, "succeeded")
        self.assertIsNone(registry_mfg_meta_resolver(self.sys)(self.T, document_id))

        reseed = self.sys.ingest_document(
            tenant_id=self.T,
            collection_id="c",
            source_id="src",
            document_id=document_id,
            document_ref=f"inline:{document_id}",
            raw=raw,
            content_type="text/plain",
            manufacturing_metadata=_meta(self.T, document_id, ApprovalStatus.DRAFT, None),
        )

        self.assertEqual(reseed.status, "succeeded")
        resolved = registry_mfg_meta_resolver(self.sys)(self.T, document_id)
        self.assertIsNotNone(resolved, "idempotent reseed must backfill mfg metadata")
        self.assertEqual(resolved.approval_status, ApprovalStatus.DRAFT)

    def test_ingest_without_metadata_persists_none(self) -> None:
        run = self.sys.ingest_document(
            tenant_id=self.T,
            collection_id="c",
            source_id="src",
            document_id="plain_doc",
            document_ref="inline:plain_doc",
            raw=_SAFETY_TEXT.encode("utf-8"),
            content_type="text/plain",
        )
        self.assertEqual(run.status, "succeeded")
        self.assertIsNone(registry_mfg_meta_resolver(self.sys)(self.T, "plain_doc"))

    def test_high_risk_draft_ingested_is_blocked(self) -> None:
        self._ingest("draft_doc", ApprovalStatus.DRAFT, None)
        self.sys.grant(self.T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        ans = self._overlay_answer()
        self.assertTrue(ans.high_risk)
        self.assertNotEqual(
            ans.status, "ok", "a high-risk answer from a draft-ingested doc must not assert"
        )

    def test_high_risk_approved_ingested_answers(self) -> None:
        self._ingest("approved_doc", ApprovalStatus.APPROVED, "2026-01-10")
        self.sys.grant(self.T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        ans = self._overlay_answer()
        self.assertTrue(ans.high_risk)
        self.assertEqual(ans.status, "ok")
        self.assertTrue(ans.citations)
        self.assertEqual(ans.citations[0].approval_status, "approved")


if __name__ == "__main__":
    unittest.main()
