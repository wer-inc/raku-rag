"""T009 — unit tests for InMemoryAuditLogWriter (FR-MFG-021/022/023, SC-MFG-010).

Verifies the three hard guarantees:
  (a) entries store only reference IDs — no raw body / PII smuggled in,
  (b) cross-tenant reads raise (001 tenancy reused, no existence disclosure),
  (c) the reused 001 Redactor is applied to free-text fields at write time.
"""
from __future__ import annotations

import unittest

from raku_rag.core.errors import TenantIsolationError
from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import (
    AuditLogEntry,
    InMemoryAuditLogWriter,
)
from raku_rag.manufacturing.domain.safety import SafetyBlockReason


def _claims(tenant_id: str, user_id: str = "u1") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant_id, user_id=user_id)


def _entry(tenant_id: str, log_id: str = "log-1", **overrides) -> AuditLogEntry:
    base = dict(
        tenant_id=tenant_id,
        log_id=log_id,
        timestamp="2026-06-19T00:00:00Z",
        action="answer.generated",
        resource_type="answer",
        resource_id="ans-9",
        citation_ids=("cit-1", "cit-2"),
        document_ids_used=("doc-1",),
        high_risk_classification_result=True,
        safety_block_reason=SafetyBlockReason.APPROVED_CITATION_MISSING,
        approval_status_at_use="approved",
    )
    base.update(overrides)
    return AuditLogEntry(**base)


class TestAuditWriterReferenceIdsOnly(unittest.TestCase):
    def test_only_reference_ids_stored_no_body_fields(self) -> None:
        writer = InMemoryAuditLogWriter()
        writer.record(_entry("A"))
        stored = writer.read_all(_claims("A"))
        self.assertEqual(len(stored), 1)
        e = stored[0]
        # Evidence is referenced by ID only.
        self.assertEqual(e.citation_ids, ("cit-1", "cit-2"))
        self.assertEqual(e.document_ids_used, ("doc-1",))
        # The schema must not carry any document body / answer text fields at all.
        forbidden = {"body", "text", "content", "answer_text", "document_body", "chunk_text"}
        self.assertEqual(forbidden & set(vars(e).keys()), set())

    def test_reference_id_fields_are_not_mangled_by_redaction(self) -> None:
        # Reference IDs must survive verbatim — redaction must not touch them.
        writer = InMemoryAuditLogWriter()
        writer.record(_entry("A", resource_id="ans-9", citation_ids=("cit-1",)))
        e = writer.read_all(_claims("A"))[0]
        self.assertEqual(e.resource_id, "ans-9")
        self.assertEqual(e.citation_ids, ("cit-1",))


class TestAuditWriterTenantIsolation(unittest.TestCase):
    def test_read_all_only_sees_own_tenant(self) -> None:
        writer = InMemoryAuditLogWriter()
        writer.record(_entry("A", log_id="a1"))
        writer.record(_entry("B", log_id="b1"))
        a_entries = writer.read_all(_claims("A"))
        self.assertEqual([e.log_id for e in a_entries], ["a1"])
        for e in a_entries:
            self.assertEqual(e.tenant_id, "A")

    def test_cross_tenant_read_raises_without_disclosure(self) -> None:
        writer = InMemoryAuditLogWriter()
        writer.record(_entry("B", log_id="b1"))
        # Principal of tenant A may not read tenant B's entries.
        with self.assertRaises(TenantIsolationError) as ctx:
            writer.read_for_tenant(_claims("A"), tenant_id="B")
        # Generic message — no leak of the other tenant's identifier.
        self.assertIn("not found", str(ctx.exception))
        self.assertNotIn("B", str(ctx.exception))

    def test_read_for_tenant_allows_own_tenant(self) -> None:
        writer = InMemoryAuditLogWriter()
        writer.record(_entry("A", log_id="a1"))
        own = writer.read_for_tenant(_claims("A"), tenant_id="A")
        self.assertEqual([e.log_id for e in own], ["a1"])

    def test_untenanted_entry_rejected(self) -> None:
        writer = InMemoryAuditLogWriter()
        with self.assertRaises(TenantIsolationError):
            writer.record(_entry(""))


class TestAuditWriterRedaction(unittest.TestCase):
    def test_redaction_applied_to_free_text_fields(self) -> None:
        writer = InMemoryAuditLogWriter()
        writer.record(
            _entry(
                "A",
                reason="denied for user alice@example.com over the limit",
                action="contact 03-1234-5678 for override",
            )
        )
        e = writer.read_all(_claims("A"))[0]
        self.assertNotIn("alice@example.com", e.reason)
        self.assertIn("[REDACTED:email]", e.reason)
        self.assertNotIn("03-1234-5678", e.action)
        self.assertIn("[REDACTED:jp_phone]", e.action)

    def test_redaction_applied_to_client_metadata_string_values(self) -> None:
        writer = InMemoryAuditLogWriter()
        writer.record(
            _entry(
                "A",
                client_metadata={"note": "key sk-ABCDEFGH123456 leaked", "count": 3},
            )
        )
        e = writer.read_all(_claims("A"))[0]
        self.assertNotIn("sk-ABCDEFGH123456", e.client_metadata["note"])
        self.assertIn("[REDACTED:api_key]", e.client_metadata["note"])
        # Non-string metadata values are preserved untouched.
        self.assertEqual(e.client_metadata["count"], 3)

    def test_record_does_not_mutate_caller_entry(self) -> None:
        writer = InMemoryAuditLogWriter()
        original = _entry("A", reason="alice@example.com flagged")
        writer.record(original)
        # The caller's object must be left intact; only the stored copy is redacted.
        self.assertEqual(original.reason, "alice@example.com flagged")
        stored = writer.read_all(_claims("A"))[0]
        self.assertIn("[REDACTED:email]", stored.reason)


if __name__ == "__main__":
    unittest.main()
