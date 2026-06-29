"""P1-3 / P1-4 (offline) — runtime-profile selection of reranker + output guardrail.

deterministic (default) keeps ScoreOrderReranker and NO model guardrail (the stdlib PromptInjectionGuard
still runs in the answer flow). production selects the Bedrock adapters, routed through injected invokers
so the wiring is unit-testable offline; the real Bedrock round-trip is verify_live (blocked-needs-infra).
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from raku_rag.core.config import Settings
from raku_rag.domain.models import Chunk, Modality, ScoredChunk
from raku_rag.providers.guardrails import (
    BedrockGuardrailProvider,
    guardrail_from_settings,
)
from raku_rag.providers.rerankers import (
    BedrockCohereReranker,
    ScoreOrderReranker,
    reranker_from_settings,
)


def _sc(chunk_id: str, score: float, text: str) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(
            tenant_id="t",
            chunk_id=chunk_id,
            document_id="d",
            collection_id="c",
            text=text,
            position=0,
            modality=Modality.TEXT,
        ),
        retrieval_score=score,
    )


class RerankProfileTest(unittest.TestCase):
    def test_deterministic_selects_score_order(self) -> None:
        self.assertIsInstance(reranker_from_settings(Settings()), ScoreOrderReranker)

    def test_production_selects_bedrock_cohere(self) -> None:
        r = reranker_from_settings(replace(Settings(), runtime_profile="production"))
        self.assertIsInstance(r, BedrockCohereReranker)

    def test_production_rerank_uses_injected_invoker_to_reorder(self) -> None:
        # score-order would be [a(0.9), b(0.1)]; the invoker flips relevance so b ranks first.
        def invoker(*, query: str, documents):
            return [0.1, 0.9]  # aligned to documents = [a, b]

        r = reranker_from_settings(
            replace(Settings(), runtime_profile="production"), invoker=invoker
        )
        out = r.rerank("q", [_sc("a", 0.9, "alpha"), _sc("b", 0.1, "bravo")], top_n=2)
        self.assertEqual([s.chunk.chunk_id for s in out], ["b", "a"])

    def test_production_rerank_fail_safe_to_score_order_without_invoker(self) -> None:
        r = reranker_from_settings(replace(Settings(), runtime_profile="production"))  # no invoker
        out = r.rerank("q", [_sc("a", 0.2, "x"), _sc("b", 0.8, "y")], top_n=2)
        self.assertEqual([s.chunk.chunk_id for s in out], ["b", "a"])  # FR-030 fail-safe


class GuardrailProfileTest(unittest.TestCase):
    def test_deterministic_has_no_model_guardrail(self) -> None:
        self.assertIsNone(guardrail_from_settings(Settings()))

    def test_production_selects_bedrock_guardrail(self) -> None:
        g = guardrail_from_settings(replace(Settings(), runtime_profile="production"))
        self.assertIsInstance(g, BedrockGuardrailProvider)

    def test_guardrail_can_be_explicitly_disabled_for_staging(self) -> None:
        g = guardrail_from_settings(
            replace(
                Settings(),
                runtime_profile="production",
                output_guardrail_provider="none",
            )
        )
        self.assertIsNone(g)

    def test_production_guardrail_returns_verdict_via_invoker(self) -> None:
        def invoker(*, text: str):
            return {"action": "BLOCK", "reason": "unsafe_instruction"}

        g = guardrail_from_settings(
            replace(Settings(), runtime_profile="production"), invoker=invoker
        )
        verdict = g.check("some answer")
        self.assertTrue(verdict.blocked)
        self.assertEqual(verdict.reason, "unsafe_instruction")

    def test_production_guardrail_fails_closed_without_invoker(self) -> None:
        g = guardrail_from_settings(replace(Settings(), runtime_profile="production"))
        with self.assertRaises(RuntimeError) as ctx:
            g.check("answer")
        self.assertIn("bedrock_guardrail_not_configured", str(ctx.exception))

    def test_production_guardrail_invoker_error_is_blocked(self) -> None:
        def invoker(*, text: str):
            raise RuntimeError("bedrock down")

        g = guardrail_from_settings(
            replace(Settings(), runtime_profile="production"), invoker=invoker
        )
        self.assertTrue(g.check("answer").blocked)  # safe default on error


if __name__ == "__main__":
    unittest.main()
