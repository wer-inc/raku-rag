"""T025b — Security hard-gate: テナント分離 (FR-021a). MVP 必須 6ケース.

visual artifact のクロステナント参照ケースは US6 (MVP対象外) のため skip。
"""
from __future__ import annotations

import unittest

from raku_rag.core.errors import AuthError, TenantIsolationError
from raku_rag.core.security.token import sign_token
from raku_rag.core.tenancy import enforce_same_tenant
from raku_rag.domain.models import ScopeType, SubjectType
from tests.helpers import claims, fresh

SAME_TEXT = "The rocket fuel mixing ratio is documented in section four."


class TestTenantIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        # Tenant A and Tenant B both hold an identically-worded document.
        self.sys.ingest_text(tenant_id="A", collection_id="ca", document_id="dA", text=SAME_TEXT)
        self.sys.ingest_text(tenant_id="B", collection_id="cb", document_id="dB", text=SAME_TEXT)
        self.sys.grant("A", ScopeType.COLLECTION, "ca", SubjectType.USER, "alice")
        self.sys.grant("B", ScopeType.COLLECTION, "cb", SubjectType.USER, "bob")
        self.alice = claims("A", "alice")

    def test_case1_search_cannot_see_other_tenant(self) -> None:
        results = self.sys.search(self.alice, "rocket fuel mixing ratio")
        self.assertTrue(results, "alice should see her own tenant's doc")
        for r in results:
            self.assertEqual(r.chunk.tenant_id, "A")
            self.assertNotEqual(r.chunk.document_id, "dB")

    def test_case2_answer_excludes_other_tenant_from_context_and_citation(self) -> None:
        ans = self.sys.answer(self.alice, "what is the rocket fuel mixing ratio?")
        self.assertEqual(ans.status, "ok")
        for c in ans.citations:
            self.assertEqual(c.document_id, "dA")
            self.assertNotEqual(c.document_id, "dB")

    @unittest.skip("visual artifacts are US6 (out of MVP scope)")
    def test_case3_visual_artifact_cross_tenant(self) -> None:  # pragma: no cover
        ...

    def test_case4_token_tenant_mismatch_rejected(self) -> None:
        token = sign_token(self.alice, self.sys.settings.token_signing_secret)
        # An API client authenticated as tenant B presents tenant A's user token.
        with self.assertRaises(AuthError):
            self.sys.token_verifier.verify(token, expected_tenant_id="B")
        # Same token verifies fine for its real tenant.
        c = self.sys.token_verifier.verify(token, expected_tenant_id="A")
        self.assertEqual(c.user_id, "alice")

    def test_case5_prefilter_boundary_not_postfilter(self) -> None:
        # Pre-filter must exclude tenant B BEFORE scoring: only A's candidates are considered.
        self.sys.search(self.alice, "rocket fuel mixing ratio")
        self.assertEqual(
            self.sys.store.last_prefiltered_count,
            1,
            "exactly tenant A's single visible chunk should be pre-filtered in",
        )

    def test_case6_no_existence_disclosure_on_cross_tenant(self) -> None:
        # Touching tenant B as alice yields a generic error (no existence/identifier leak).
        with self.assertRaises(TenantIsolationError) as ctx:
            enforce_same_tenant(self.alice, resource_tenant_id="B")
        self.assertIn("not found", str(ctx.exception))
        self.assertNotIn("B", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
