"""T069 — focused unit tests for InMemoryAuditLogWriter redaction / reference-IDs-only (SC-MFG-010).

Complements the existing tests/manufacturing/unit/test_audit_writer.py (NOT modified) with additional
UNIT coverage of:
  - free-text fields (decision / actor_role / actor_group / source_ip) redacted via the reused 001
    Redactor at write time,
  - reference-ID fields (document_ids_used, citation_ids, resource_id, factory_id, department_id)
    preserved verbatim — redaction must never corrupt opaque identifiers,
  - the schema carries NO document-body field (reference IDs only),
  - the per-tenant SHA-256 hash chain is intact after writes and a post-hoc mutation breaks it.

stdlib only; additive (new file). Does not touch the existing audit-writer unit test.
"""
from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import (
    AuditLogEntry,
    InMemoryAuditLogWriter,
)


def _claims(tenant_id: str = "t1") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant_id, user_id="u1")


def _entry(**overrides) -> AuditLogEntry:
    base = dict(
        tenant_id="t1",
        log_id="log-1",
        timestamp="2026-06-19T00:00:00Z",
        action="approval.transition",
        resource_type="document",
        resource_id="doc-7",
        document_ids_used=("doc-7",),
        citation_ids=("cit-1", "cit-2"),
        factory_id="factory-3",
        department_id="dept-9",
    )
    base.update(overrides)
    return AuditLogEntry(**base)


class TestFreeTextRedaction(unittest.TestCase):
    def test_decision_field_redacted(self) -> None:
        w = InMemoryAuditLogWriter()
        w.record(_entry(decision="approved by alice@example.com"))
        e = w.read_all(_claims())[0]
        self.assertNotIn("alice@example.com", e.decision)
        self.assertIn("[REDACTED:email]", e.decision)

    def test_actor_role_and_group_redacted(self) -> None:
        w = InMemoryAuditLogWriter()
        w.record(_entry(actor_role="lead bob@corp.com", actor_group="grp 03-1234-5678"))
        e = w.read_all(_claims())[0]
        self.assertNotIn("bob@corp.com", e.actor_role)
        self.assertNotIn("03-1234-5678", e.actor_group)

    def test_source_ip_field_passed_through_redactor(self) -> None:
        # source_ip is a free-text field; an embedded secret must be masked.
        w = InMemoryAuditLogWriter()
        w.record(_entry(source_ip="key sk-ABCDEFGH123456"))
        e = w.read_all(_claims())[0]
        self.assertNotIn("sk-ABCDEFGH123456", e.source_ip)


class TestReferenceIdsPreserved(unittest.TestCase):
    def test_reference_id_fields_verbatim(self) -> None:
        w = InMemoryAuditLogWriter()
        w.record(_entry())
        e = w.read_all(_claims())[0]
        # Opaque identifiers must survive untouched — redaction would corrupt the audit chain.
        self.assertEqual(e.document_ids_used, ("doc-7",))
        self.assertEqual(e.citation_ids, ("cit-1", "cit-2"))
        self.assertEqual(e.resource_id, "doc-7")
        self.assertEqual(e.factory_id, "factory-3")
        self.assertEqual(e.department_id, "dept-9")

    def test_no_document_body_field_in_schema(self) -> None:
        w = InMemoryAuditLogWriter()
        w.record(_entry())
        e = w.read_all(_claims())[0]
        forbidden = {"body", "text", "content", "answer_text", "document_body", "chunk_text"}
        self.assertEqual(forbidden & set(vars(e).keys()), set())

    def test_record_does_not_mutate_caller_entry(self) -> None:
        w = InMemoryAuditLogWriter()
        original = _entry(reason="contact carol@example.com")
        w.record(original)
        # Only the stored copy is redacted; the caller's object is left intact.
        self.assertEqual(original.reason, "contact carol@example.com")
        self.assertIn("[REDACTED:email]", w.read_all(_claims())[0].reason)


class TestHashChainIntegrity(unittest.TestCase):
    def test_chain_intact_after_multiple_writes(self) -> None:
        w = InMemoryAuditLogWriter()
        w.record(_entry(log_id="a1"))
        w.record(_entry(log_id="a2"))
        w.record(_entry(log_id="a3"))
        self.assertTrue(w.verify_chain(_claims()))

    def test_post_hoc_mutation_breaks_chain(self) -> None:
        w = InMemoryAuditLogWriter()
        w.record(_entry(log_id="a1"))
        w.record(_entry(log_id="a2"))
        # Tamper with a stored entry's content without re-hashing.
        stored = w.read_all(_claims())
        stored[0].resource_id = "doc-EVIL"
        self.assertFalse(w.verify_chain(_claims()))


if __name__ == "__main__":
    unittest.main()
