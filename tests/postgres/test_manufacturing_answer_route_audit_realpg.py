"""Tier B (real Postgres) — P2-1 / AF-6: the DEPLOYED manufacturing answer path writes a
tamper-evident hash-chain audit entry over real Postgres.

``apps/answer-service/server.py`` ``/internal/manufacturing/answer`` now routes through
``manufacturing_system.answer`` — i.e. ``build_manufacturing_system_for_base(ProductionSystem).answer``,
which records the high-risk classification + safety decision into the
``PostgresManufacturingAuditLogWriter`` (parity with the drafts/approval routes). Previously the route
used the audit-less overlay and discarded the decision (``mfg_ans, *_``), so a deployed safety-gate
answer wrote NO audit row (FR-MFG-021 gap).

This pins the LIVE mechanism on real Postgres:
1. a high-risk answer (blocked, no approved citation) produces an ``answer.safety_evaluated`` event;
2. the hash chain verifies intact;
3. mutating one stored row breaks ``verify_chain`` (tamper-evidence).

Skip-safe without Postgres (mirrors the other ``tests/postgres`` suites), so Tier A stays Docker-free.
Runs for real in CI ``gate.yml`` tier-b (``scripts/gate.sh b`` with ``POSTGRES_URL`` set).
"""

from __future__ import annotations

import os
import unittest

from raku_rag.manufacturing.api.audit import ANSWER_ACTION

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")
T = "mfg_p2_audit"
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
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'manufacturing_audit_events'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@unittest.skipUnless(_postgres_available(), "Postgres not reachable (Tier B / local-only)")
class TestDeployedAnswerRouteAuditRealPG(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.domain.models import ScopeType, SubjectType
        from raku_rag.production import ProductionSystem, build_manufacturing_system_for_base

        self.base = ProductionSystem(DSN, reset=True)
        self.addCleanup(self.base.close)
        # ``reset=True`` resets the 001 core tables but NOT the append-only manufacturing audit table
        # (the app role has INSERT/SELECT only — no DELETE/TRUNCATE — which is the correct
        # append-only audit posture in production). For per-test isolation, truncate it via a
        # short-lived connection as the table-owning login role so accumulation across test
        # methods/runs cannot break the chain check.
        import psycopg

        with psycopg.connect(DSN, autocommit=True) as admin_conn:
            admin_conn.execute("TRUNCATE manufacturing_audit_events")
        # the audited production manufacturing system — exactly what the deployed answer route calls.
        self.sys = build_manufacturing_system_for_base(self.base)
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")

    def _ingest(self, document_id, status, effective) -> None:
        from raku_rag.manufacturing.domain.metadata import (
            DocumentKind,
            ManufacturingDocumentMetadata,
        )

        meta = ManufacturingDocumentMetadata(
            tenant_id=T,
            document_id=document_id,
            approval_status=status,
            effective_date=effective,
            document_kind=DocumentKind.WORK_INSTRUCTION,
            safety_category="lockout_tagout",
            hazard_tags=("設備停止", "分解", "高圧"),
        )
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id=document_id,
            text=_SAFETY_TEXT,
            metadata=meta,
        )

    def _answer(self):
        from tests.helpers import claims

        return self.sys.answer(claims(T, "op"), _HIGH_RISK_QUERY, "c")

    def _admin(self):
        from raku_rag.domain.models import IdentityClaims

        return IdentityClaims(tenant_id=T, user_id="admin", roles=("admin",))

    def test_blocked_high_risk_answer_writes_audit_entry(self) -> None:
        from raku_rag.manufacturing.domain.metadata import ApprovalStatus

        # a DRAFT (not approved) high-risk procedure -> the safety gate blocks (no approved citation)
        self._ingest("draft_proc", ApprovalStatus.DRAFT, None)
        ans = self._answer()
        self.assertTrue(ans.high_risk, "press disassembly must classify high-risk")
        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(ans.safety_block_reason, "approved_citation_missing")

        # THE P2-1 ASSERTION: the deployed answer path wrote a real audit row over Postgres.
        entries = self.sys.audit.read_all(self._admin())
        answer_events = [e for e in entries if e.action == ANSWER_ACTION]
        self.assertTrue(
            answer_events,
            "deployed answer route must write an 'answer.safety_evaluated' audit entry to PG",
        )
        self.assertTrue(
            any(e.high_risk_classification_result for e in answer_events),
            "the high-risk classification must be recorded on the audit entry",
        )
        self.assertTrue(self.sys.audit.verify_chain(self._admin()))

    def test_audit_chain_tamper_is_detected(self) -> None:
        from raku_rag.manufacturing.domain.metadata import ApprovalStatus

        self._ingest("approved_proc", ApprovalStatus.APPROVED, "2026-01-10")
        self._answer()
        # precondition: an answer audit row exists and the chain is intact
        entries = self.sys.audit.read_all(self._admin())
        self.assertTrue(any(e.action == ANSWER_ACTION for e in entries))
        self.assertTrue(
            self.sys.audit.verify_chain(self._admin()), "precondition: chain intact before tamper"
        )

        # tamper one stored row's entry_hash -> verify_chain must now fail (tamper-evidence)
        conn = self.base._conn
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (T,))
            cur.execute(
                "UPDATE manufacturing_audit_events "
                "SET entry_payload = jsonb_set(entry_payload, '{entry_hash}', '\"tampered\"') "
                "WHERE audit_event_id = ("
                "  SELECT audit_event_id FROM manufacturing_audit_events "
                "  ORDER BY created_at DESC, audit_event_id DESC LIMIT 1)"
            )
        conn.commit()
        self.assertFalse(
            self.sys.audit.verify_chain(self._admin()),
            "a mutated audit row must break the hash chain",
        )


if __name__ == "__main__":
    unittest.main()
