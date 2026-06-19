"""T064 — Audit export API SHAPE contract (contracts/mfg-openapi.md §G, FR-MFG-021~023).

Response-shape contract for GET /v1/manufacturing/audit/export (admin):
  - structured AuditLogEntry export, tenant-scoped, reference IDs only (no PII/secret), tamper-evident.

This is the SHAPE axis only; the load-bearing PII=0 / coverage / tamper-evidence behaviour is pinned
by T061 (test_audit_coverage.py). Here we pin: the export is tenant-scoped, reuses the 001 Redactor,
carries no confidential content, and exposes the hash-chain fields so an importer can re-verify.

Entrypoint contract the stage-2 ManufacturingSystem must satisfy:

  export_audit(*, principal, fmt="jsonl") -> str | list[dict]
      GET /v1/manufacturing/audit/export. Returns the principal's OWN tenant's structured entries
      (tenant-scoped — cross-tenant references impossible). fmt in {"jsonl", "csv", "dict"}; entries
      carry reference IDs + the prev_hash/entry_hash chain fields (re-verifiable downstream).

TDD: RED now because export_audit is unimplemented on ManufacturingSystem (missing-impl), NOT an
unrelated import error. Assertion style mirrors tests/manufacturing/test_drafts_contract.py.
"""
from __future__ import annotations

import json
import unittest

from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata

T = "tenant_mfg"
SECRET_CUSTOMER = "ACME Aerospace Confidential KK"
SECRET_BODY = "PROPRIETARY alloy recipe contact alice@acme-secret.example"


def _admin(tenant: str = T, user: str = "admin-1") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user, roles=("admin",))


def _seed(sys: ManufacturingSystem, tenant: str = T) -> None:
    sys.ingest_manufacturing(
        tenant_id=tenant,
        collection_id="c",
        document_id="conf1",
        text=SECRET_BODY,
        metadata=ManufacturingDocumentMetadata(
            tenant_id=tenant, document_id="conf1", customer=SECRET_CUSTOMER
        ),
    )
    sys.grant(tenant, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
    sys.answer(IdentityClaims(tenant_id=tenant, user_id="op"), "what is the recipe?")


class TestAuditExportShape(unittest.TestCase):
    def test_jsonl_export_is_parseable_and_reference_only(self) -> None:
        sys = ManufacturingSystem()
        _seed(sys)
        out = sys.export_audit(principal=_admin(), fmt="jsonl")
        self.assertIsInstance(out, str)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertTrue(lines, "export must contain at least one entry")
        for ln in lines:
            rec = json.loads(ln)  # each line is a JSON object
            self.assertIn("tenant_id", rec)
            self.assertEqual(rec["tenant_id"], T)
            # Reference-only + tamper-evidence fields surfaced for downstream re-verification.
            self.assertIn("entry_hash", rec)
        # No confidential content anywhere in the serialized export.
        for bad in (SECRET_CUSTOMER, SECRET_BODY, "alice@acme-secret.example"):
            self.assertNotIn(bad, out, f"export leaked confidential content {bad!r} (SC-MFG-010)")

    def test_export_is_tenant_scoped(self) -> None:
        sys = ManufacturingSystem()
        _seed(sys, tenant=T)
        _seed(sys, tenant="tenant_other")
        out = sys.export_audit(principal=_admin(), fmt="dict")
        # dict format returns a list of dict records for the admin's OWN tenant only.
        self.assertTrue(out)
        for rec in out:
            self.assertEqual(rec["tenant_id"], T, "export must not include another tenant's entries")


if __name__ == "__main__":
    unittest.main()
