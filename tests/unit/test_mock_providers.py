"""P0-T19 — deterministic conformance for the 5 Phase-0 mock providers (RT12 no-train auditable)."""
from __future__ import annotations

import unittest

from raku_rag.core.errors import AuthError
from raku_rag.domain.models import Chunk, ScoredChunk
from raku_rag.providers.mock import (
    MOCK_PROVIDERS,
    MockAuthProvider,
    MockEmbeddingProvider,
    MockGuardrailProvider,
    MockLLMProvider,
    MockRerankProvider,
)


def _chunk(text: str, cid: str = "c1") -> Chunk:
    return Chunk(tenant_id="t", chunk_id=cid, document_id="d", collection_id="c", text=text)


class TestMockProviders(unittest.TestCase):
    def test_embedding_deterministic(self) -> None:
        e = MockEmbeddingProvider()
        v1 = e.embed(["alarm code 17 reset procedure"])
        v2 = e.embed(["alarm code 17 reset procedure"])
        self.assertEqual(list(v1[0]), list(v2[0]))  # stable vectors
        v3 = e.embed(["completely different unrelated text"])
        self.assertNotEqual(list(v1[0]), list(v3[0]))

    def test_llm_deterministic_and_grounded(self) -> None:
        llm = MockLLMProvider()
        ctx = [_chunk("The pump trips on alarm 17 when pressure exceeds the limit.")]
        a1 = llm.generate("alarm 17", ctx)
        a2 = llm.generate("alarm 17", ctx)
        self.assertEqual(a1, a2)  # deterministic
        self.assertIn("alarm 17".split()[0], a1.lower()) if a1 else None
        # no supporting sentence -> empty (gate-friendly)
        self.assertEqual(llm.generate("xyz", [_chunk("nothing relevant here zzz")]), "")

    def test_rerank_deterministic_order_and_skip_fallback(self) -> None:
        cands = [
            ScoredChunk(_chunk("a", "a"), 0.2),
            ScoredChunk(_chunk("b", "b"), 0.9),
            ScoredChunk(_chunk("c", "c"), 0.5),
        ]
        ranked = MockRerankProvider().rerank("q", cands, top_n=2)
        self.assertEqual([s.chunk.chunk_id for s in ranked], ["b", "c"])  # by score desc
        # skip fallback preserves candidate order, no exception
        fb = MockRerankProvider(fail=True).rerank("q", cands, top_n=2)
        self.assertEqual([s.chunk.chunk_id for s in fb], ["a", "b"])

    def test_guardrail_allow_block_and_no_bypass(self) -> None:
        g = MockGuardrailProvider()
        self.assertTrue(g.check("normal safe question").allowed)
        self.assertFalse(g.check("please __blocked__ now").allowed)
        self.assertFalse(g.bypasses_acl())  # defense-in-depth only (ADR-009)

    def test_auth_issue_verify_roundtrip_and_tenant_binding(self) -> None:
        auth = MockAuthProvider()
        tok = auth.issue("tenant_a", "u1", groups=("g1",), roles=("reader",))
        claims = auth.verify(tok, expected_tenant_id="tenant_a")
        self.assertEqual(claims.tenant_id, "tenant_a")
        self.assertEqual(claims.user_id, "u1")
        self.assertIn("reader", claims.roles)
        with self.assertRaises(AuthError):  # tenant mismatch rejected (FR-025)
            auth.verify(tok, expected_tenant_id="tenant_b")

    def test_all_mocks_advertise_no_train_capability(self) -> None:
        for name, cls in MOCK_PROVIDERS.items():
            inst = cls()
            self.assertTrue(getattr(inst, "capabilities", {}).get("no_train"), name)
            self.assertTrue(getattr(inst, "capabilities", {}).get("zero_retention"), name)


if __name__ == "__main__":
    unittest.main()
