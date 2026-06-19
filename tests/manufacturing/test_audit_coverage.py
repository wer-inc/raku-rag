"""T061 — AUDIT COVERAGE HARD GATE SC-MFG-010 (FR-MFG-021~023, Hard Rule 8, Base CR-001-A).

This is an ABSOLUTE gate (loop-engineering §3 mechanism-pin). The audit log is the single source of
truth: every required event type is recorded with NO gaps (100% coverage), it contains reference IDs
ONLY (no PII / secret / confidential body), and it is tamper-evident via a SHA-256 prev_hash /
entry_hash chain (mutating any stored entry breaks verification). A regression in coverage, a PII
leak, or a tamper-evidence hole MUST fail this test.

Mechanism pinned (do NOT weaken in stage 2):
 (1) CLOSED-ENUMERATION COVERAGE — ``REQUIRED_EVENT_TYPES`` is a CLOSED list of the audited event
     categories (FR-MFG-021). A representative end-to-end flow (ingest/parse/metadata → approval
     transition → draft generate + review → high-risk decision → safety_gate block → answer →
     citation access → ACL denial → no-train/retention setting change → deletion) is driven, then
     EACH required category MUST appear in the audit log. A missing category FAILS (the closed list
     means an un-emitted required event is caught — not just "some events were logged").
 (2) PII = 0 — a confidential document (customer name + secret + body text) is seeded and flows
     through the pipeline; EVERY stored audit entry (all string fields + every client_metadata string)
     is scanned and MUST NOT contain the customer name, the document body, or the secret. Reference
     IDs only (FR-MFG-023, SC-MFG-010 = PII 混入 0). 001 Redactor is reused as defence-in-depth.
 (3) TAMPER-EVIDENCE — the stored log verifies as an intact SHA-256 prev_hash/entry_hash chain;
     MUTATING a stored entry and re-verifying FAILS (chain broken). Base CR-001-A; hashlib is stdlib.

Authoritative: spec FR-MFG-021~023, SC-MFG-010; contracts/mfg-openapi.md §G + "安全・監査";
data-model §H; quickstart S9. Assertion style mirrors tests/security/test_acl_leak.py +
tests/manufacturing/unit/test_audit_writer.py.

Entrypoint contract the stage-2 ``ManufacturingSystem`` must satisfy (additive to the existing
audit wiring; hashlib-based chain on ``AuditLogEntry.prev_hash``/``entry_hash``):

  ManufacturingSystem.audit  — the shared ``InMemoryAuditLogWriter`` (already wired). After this
      phase every governance event also lands here, and the writer maintains the per-tenant hash
      chain on ``record`` (prev_hash = previous entry_hash; entry_hash = SHA-256 over the entry's
      canonical reference-only content). Existing writer guarantees (reference-IDs-only / redaction /
      tenant isolation) are PRESERVED — the chain fields are additive and default-safe.
  ManufacturingSystem.audit.verify_chain(principal) -> bool
      True iff the principal's tenant log is an intact chain (each entry's prev_hash matches the
      previous entry_hash and each entry_hash recomputes). Returns False if any entry was mutated.
  ManufacturingSystem.export_audit(*, principal, fmt="jsonl") -> str | list  (see test_export_contract.py)

  New governance funnels that MUST be audited (FR-MFG-019/020/021):
    update_data_use_policy(*, tenant_id, patch, actor)  — no-train / retention setting change.
    delete_document(*, tenant_id, document_id, actor)   — deletion / tombstone (reuses 001 tombstone).

TDD: RED now because the hash-chain (``audit.verify_chain``) + the governance/deletion audit funnels
are unimplemented, and the end-to-end flow exercises governance entrypoints that do not exist yet
(missing-impl), NOT an unrelated import error.
"""
from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.domain.metadata import (
    ApprovalSource,
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)

T = "tenant_mfg"

# --- The confidential seed. None of these strings may EVER appear in the audit log. ---------------
SECRET_CUSTOMER = "ACME Aerospace Confidential KK"
SECRET_BODY = (
    "PROPRIETARY: the alloy recipe uses 7.3% scandium and the line runs at 412C; "
    "contact engineer alice@acme-secret.example for the sealed spec."
)
SECRET_TOKEN = "sk-CONFIDENTIAL9876543210"


def _admin(tenant: str = T, user: str = "admin-1") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user, roles=("admin",))


def _op(tenant: str = T, user: str = "op") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user)


# CLOSED enumeration of required audited event categories (FR-MFG-021, SC-MFG-010). Each maps to a
# predicate over a stored AuditLogEntry; a category with ZERO matching entries fails coverage.
def _action(e) -> str:
    return (getattr(e, "action", "") or "").lower()


REQUIRED_EVENT_TYPES: dict[str, callable] = {
    "ingest_parse_metadata": lambda e: any(
        k in _action(e) for k in ("ingest", "parse", "metadata")
    ),
    "approval_transition": lambda e: "approval" in _action(e) or "approval" in (getattr(e, "resource_type", "") or ""),
    "draft_generate": lambda e: "draft" in _action(e) and ("generate" in _action(e) or "create" in _action(e)),
    "draft_review": lambda e: "draft" in _action(e) and ("review" in _action(e) or "assign" in _action(e) or "transition" in _action(e)),
    "high_risk_decision": lambda e: getattr(e, "high_risk_classification_result", None) is True,
    "safety_gate_block": lambda e: getattr(e, "safety_block_reason", None) is not None,
    "answer": lambda e: "answer" in _action(e),
    "citation_access": lambda e: bool(getattr(e, "citation_ids", ())) or "citation" in _action(e),
    "acl_denied": lambda e: "acl" in _action(e) and ("deni" in _action(e) or "denied" in _action(e)),
    "policy_setting_change": lambda e: "policy" in _action(e) or "no_train" in _action(e) or "retention" in _action(e),
    "deletion": lambda e: "delet" in _action(e) or "tombstone" in _action(e),
}


def _all_strings(entry) -> list[str]:
    """Every string value carried by a stored audit entry (fields + client_metadata values)."""
    out: list[str] = []
    for value in vars(entry).values():
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            out.extend(v for v in value.values() if isinstance(v, str))
        elif isinstance(value, (tuple, list)):
            out.extend(v for v in value if isinstance(v, str))
    return out


def _drive_end_to_end(sys: ManufacturingSystem) -> None:
    """Drive a representative flow that should emit EVERY required audit event category."""
    admin = _admin()
    # 1) ingest a confidential doc (ingest / parse / metadata enrichment).
    meta = ManufacturingDocumentMetadata(
        tenant_id=T,
        document_id="conf1",
        customer=SECRET_CUSTOMER,
        approval_status=ApprovalStatus.PENDING_REVIEW,
        effective_date=None,
        approval_source=ApprovalSource.WORKFLOW,
        document_kind=DocumentKind.WORK_INSTRUCTION,
        safety_category="lockout_tagout",
        hazard_tags=("設備停止", "分解", "高圧"),
    )
    sys.ingest_manufacturing(
        tenant_id=T, collection_id="c", document_id="conf1", text=SECRET_BODY, metadata=meta
    )
    sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")

    # 2) approval transition (pending_review -> approved) + sets an effective date.
    sys.transition_approval(
        tenant_id=T, document_id="conf1", to_status=ApprovalStatus.APPROVED.value, actor=admin
    )

    # 3) draft generation + review (assign + decide) — AI output, reviewer-approved.
    from raku_rag.manufacturing.domain.draft import DraftType

    art = sys.generate_draft(
        principal=admin, kind=DraftType.CHECKLIST, source_document_ids=("conf1",)
    )
    sys.assign_reviewer(tenant_id=T, artifact_id=art.artifact_id, reviewer_id="rev_1")
    sys.review_draft(
        tenant_id=T,
        artifact_id=art.artifact_id,
        reviewer=IdentityClaims(tenant_id=T, user_id="rev_1", roles=("reviewer",)),
        decision="approved",
        comment="ok",
    )

    # 4) high-risk answer that ASSERTS (approved+effective citation) — high_risk decision + answer +
    #    citation access. Then a BLOCKED high-risk answer for the safety_gate_block category.
    sys.answer(_op(), "How do I disassemble the press safely after lockout?")

    # A high-risk query whose only evidence is a DRAFT doc → blocked (approved_citation_missing).
    draft_meta = ManufacturingDocumentMetadata(
        tenant_id=T,
        document_id="draftdoc",
        approval_status=ApprovalStatus.DRAFT,
        effective_date=None,
        document_kind=DocumentKind.WORK_INSTRUCTION,
        safety_category="lockout_tagout",
        hazard_tags=("感電", "高圧"),
    )
    sys.ingest_manufacturing(
        tenant_id=T,
        collection_id="c2",
        document_id="draftdoc",
        text="Draft note about working on the 400V panel — not yet approved.",
        metadata=draft_meta,
    )
    sys.grant(T, ScopeType.COLLECTION, "c2", SubjectType.USER, "op")
    sys.answer(_op(), "How do I work on the 400V panel without getting electrocuted?")

    # 5) ACL denial — a user with NO grant to a private collection is denied (001 pre-filter).
    sys.ingest_manufacturing(
        tenant_id=T,
        collection_id="private",
        document_id="priv1",
        text="Private process note.",
        metadata=ManufacturingDocumentMetadata(tenant_id=T, document_id="priv1"),
    )
    sys.answer(_op(tenant=T, user="stranger"), "what is in the private process note?", collection_id="private")

    # 6) no-train / retention setting change (governance) — audited (FR-MFG-019).
    sys.update_data_use_policy(
        tenant_id=T, patch={"retention_customer": 730}, actor=admin
    )

    # 7) deletion / tombstone (reuses 001 tombstone) — audited.
    sys.delete_document(tenant_id=T, document_id="conf1", actor=admin)


class TestAuditCoverageClosedEnumeration(unittest.TestCase):
    """(1) Every REQUIRED event category appears in the audit log — 0 gaps (closed enumeration)."""

    def test_all_required_event_types_present(self) -> None:
        sys = ManufacturingSystem()
        _drive_end_to_end(sys)
        entries = sys.audit.read_all(_admin())
        self.assertTrue(entries, "the end-to-end flow must produce audit entries")
        missing = [
            name
            for name, pred in REQUIRED_EVENT_TYPES.items()
            if not any(pred(e) for e in entries)
        ]
        self.assertEqual(
            missing,
            [],
            f"audit coverage gap (SC-MFG-010 requires 100%, 0 gaps): missing event types {missing}. "
            f"observed actions={sorted({_action(e) for e in entries})}",
        )


class TestAuditNoPII(unittest.TestCase):
    """(2) PII = 0 — no customer name / document body / secret appears anywhere in the audit log."""

    def test_no_confidential_content_in_any_audit_entry(self) -> None:
        sys = ManufacturingSystem()
        _drive_end_to_end(sys)
        entries = sys.audit.read_all(_admin())
        forbidden_substrings = [
            SECRET_CUSTOMER,
            SECRET_TOKEN,
            "alice@acme-secret.example",
            "scandium",
            "412C",
            SECRET_BODY,
        ]
        for e in entries:
            for s in _all_strings(e):
                for bad in forbidden_substrings:
                    self.assertNotIn(
                        bad,
                        s,
                        f"audit log leaked confidential content {bad!r} in field value {s!r} "
                        f"(SC-MFG-010 = PII/secret/body 混入 0; reference IDs only)",
                    )

    def test_evidence_is_referenced_by_id_only(self) -> None:
        # Reference IDs (document_ids_used / citation_ids) survive verbatim so the trail is intact.
        sys = ManufacturingSystem()
        _drive_end_to_end(sys)
        entries = sys.audit.read_all(_admin())
        self.assertTrue(
            any("conf1" in (getattr(e, "document_ids_used", ()) or ()) for e in entries)
            or any(getattr(e, "resource_id", None) == "conf1" for e in entries),
            "the confidential document must be tracked by its reference ID (document_id) in the audit log",
        )


class TestAuditTamperEvidence(unittest.TestCase):
    """(3) SHA-256 prev_hash/entry_hash chain verifies intact; a mutation breaks verification."""

    def test_chain_verifies_intact(self) -> None:
        sys = ManufacturingSystem()
        _drive_end_to_end(sys)
        self.assertTrue(
            sys.audit.verify_chain(_admin()),
            "a freshly-written audit log must verify as an intact hash chain (Base CR-001-A)",
        )

    def test_every_entry_is_hash_chained(self) -> None:
        sys = ManufacturingSystem()
        _drive_end_to_end(sys)
        entries = sys.audit.read_all(_admin())
        self.assertTrue(entries)
        prev = None
        for e in entries:
            self.assertTrue(getattr(e, "entry_hash", None), "every entry must carry an entry_hash")
            self.assertEqual(
                getattr(e, "prev_hash", None),
                prev,
                "each entry's prev_hash must equal the previous entry's entry_hash (chain link)",
            )
            prev = e.entry_hash

    def test_mutating_a_stored_entry_breaks_verification(self) -> None:
        sys = ManufacturingSystem()
        _drive_end_to_end(sys)
        self.assertTrue(sys.audit.verify_chain(_admin()), "precondition: chain intact before mutation")
        # Mutate a stored entry's content WITHOUT recomputing its hash → chain must no longer verify.
        entries = sys.audit.read_all(_admin())
        target = entries[len(entries) // 2]
        target.decision = "TAMPERED"
        self.assertFalse(
            sys.audit.verify_chain(_admin()),
            "mutating a stored audit entry MUST break hash-chain verification (tamper-evidence)",
        )


if __name__ == "__main__":
    unittest.main()
