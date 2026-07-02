"""★1 監査エビデンスパック — aggregation correctness, range filter, tamper verdict, no free text."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.api.evidence_pack import build_evidence_pack
from raku_rag.manufacturing.domain.audit import AuditLogEntry, InMemoryAuditLogWriter

ADMIN = IdentityClaims(tenant_id="tenant_a", user_id="alice", roles=("tenant_admin",))
OTHER = IdentityClaims(tenant_id="tenant_b", user_id="mallory", roles=("tenant_admin",))


def _entry(action: str, decision: str, ts: str, resource: str = "res_1") -> AuditLogEntry:
    return AuditLogEntry(
        tenant_id="tenant_a",
        log_id=f"{action}:{ts}:{resource}",
        timestamp=ts,
        actor_id="alice",
        action=action,
        resource_type="answer",
        resource_id=resource,
        decision=decision,
        reason="test",
    )


class EvidencePackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = InMemoryAuditLogWriter()
        for ts, decision in (
            ("2026-07-01T09:00:00Z", "ok"),
            ("2026-07-01T10:00:00Z", "ok"),
            ("2026-07-01T11:00:00Z", "insufficient_evidence"),
            ("2026-07-01T12:00:00Z", "blocked_high_risk"),
            ("2026-06-01T09:00:00Z", "ok"),  # outside the period
        ):
            self.audit.record(_entry("answer", decision, ts))
        self.audit.record(
            _entry("phone.handoff_created", "customer_requested_human", "2026-07-01T13:00:00Z")
        )
        self.audit.record(
            _entry("phone.quality_evaluated", "hallucination", "2026-07-01T14:00:00Z")
        )
        self.audit.record(
            _entry("phone.transcript_viewed", "redacted_view", "2026-07-01T15:00:00Z")
        )

    def _pack(self, **kw):
        return build_evidence_pack(
            self.audit, ADMIN, from_iso="2026-07-01", to_iso="2026-07-31", **kw
        )

    def test_counts_and_grounded_rate(self) -> None:
        pack = self._pack()
        self.assertEqual(pack["summary"]["question_count"], 4)  # June answer excluded
        self.assertEqual(pack["summary"]["grounded_answer_count"], 2)
        self.assertAlmostEqual(pack["summary"]["grounded_answer_rate"], 0.5)
        self.assertEqual(pack["summary"]["blocked_count"], 2)
        self.assertEqual(
            pack["blocked_by_reason"],
            {"blocked_high_risk": 1, "insufficient_evidence": 1},
        )

    def test_handoffs_qa_and_access_surface(self) -> None:
        pack = self._pack()
        self.assertEqual(pack["summary"]["handoff_count"], 1)
        self.assertEqual(pack["handoffs"][0]["reason"], "customer_requested_human")
        self.assertEqual(pack["qa_flags"], {"hallucination": 1})
        self.assertEqual(pack["access_transparency"], {"phone.transcript_viewed": 1})

    def test_chain_verdict_true_then_tampered_false(self) -> None:
        pack = self._pack()
        self.assertTrue(pack["hash_chain"]["verified"])
        # Tamper with a stored entry -> the pack must report a broken chain.
        entries = self.audit.read_all(ADMIN)
        object.__setattr__(entries[0], "decision", "tampered")
        self.assertFalse(self._pack()["hash_chain"]["verified"])

    def test_tenant_isolation(self) -> None:
        pack = build_evidence_pack(self.audit, OTHER, from_iso="", to_iso="")
        self.assertEqual(pack["summary"]["audit_entry_count"], 0)
        self.assertEqual(pack["hash_chain"]["total_entries"], 0)

    def test_no_free_text_leaks(self) -> None:
        blob = repr(self._pack())
        # Reference-only invariant: no content-bearing fields exist in the schema
        # (action LABELS like phone.transcript_viewed are fine — they carry no text).
        for forbidden in ("answer_text", "redacted_text", "ai_response_text", "suggested_fix"):
            self.assertNotIn(forbidden, blob)


if __name__ == "__main__":
    unittest.main()
