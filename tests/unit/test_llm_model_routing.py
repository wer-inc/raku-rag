"""★G5 — QueryProfile.llm_model routing seam in AnswerService.

With an ``llm_by_model`` registry, a profile can route generation to a registered provider (small
model for cheap profiles, large for high-risk) via the tenant-tunable query-profiles API. Default
stays unchanged; unknown model names fail open to the default provider (logged + metered).
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Sequence

from raku_rag.domain.models import Chunk, ScopeType, SubjectType
from raku_rag.providers.llms import ExtractiveLLMProvider
from raku_rag.services.answer import AnswerService
from tests.helpers import claims, fresh

T = "routing_tenant"
QUERY = "when do backups run and how long are they retained?"


class _MarkedLLM(ExtractiveLLMProvider):
    """Extractive provider (keeps groundedness gates green) that records generate() calls."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.calls = 0

    def generate(self, query: str, context: Sequence[Chunk]) -> str:
        self.calls += 1
        return super().generate(query, context)


class TestLlmModelRouting(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Backups run nightly at 02:00 UTC and are retained for thirty days.",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")
        self.default_llm = _MarkedLLM("default-model")
        self.small_llm = _MarkedLLM("small-x")

    def _answer_service(self, llm_by_model) -> AnswerService:
        base = self.sys.answer_service
        return AnswerService(
            retrieval=self.sys.retrieval,
            llm=self.default_llm,
            gate=self.sys.gate,
            cost=self.sys.cost,
            get_document=self.sys.registry.get,
            metrics=self.sys.metrics,
            tracer=self.sys.tracer,
            settings=self.sys.settings,
            structured_tool=base._structured_tool,
            llm_by_model=llm_by_model,
        )

    def _profile(self, **overrides):
        return replace(self.sys.profiles.resolve(None), **overrides)

    def test_no_registry_default_behaviour_unchanged(self) -> None:
        service = self._answer_service(None)

        # Even an explicit llm_model is inert without a registry — pre-seam behaviour.
        ans = service.answer(self.alice, QUERY, self._profile(llm_model="small-x"))

        self.assertEqual(ans.status, "ok")
        self.assertEqual(self.default_llm.calls, 1)
        self.assertEqual(self.small_llm.calls, 0)

    def test_default_profile_uses_default_provider_without_fallback(self) -> None:
        service = self._answer_service({"small-x": self.small_llm})

        # The profile's dataclass default llm_model means "no preference", not "unknown model".
        ans = service.answer(self.alice, QUERY, self._profile())

        self.assertEqual(ans.status, "ok")
        self.assertEqual(self.default_llm.calls, 1)
        self.assertEqual(self.small_llm.calls, 0)
        fallbacks = [
            value
            for (name, _labels), value in self.sys.metrics._counters.items()
            if name == "answer_llm_model_fallback_total"
        ]
        self.assertEqual(fallbacks, [])

    def test_registered_alternate_model_routes_generation(self) -> None:
        service = self._answer_service({"small-x": self.small_llm})

        ans = service.answer(self.alice, QUERY, self._profile(llm_model="small-x"))

        self.assertEqual(ans.status, "ok")
        self.assertEqual(self.small_llm.calls, 1)
        self.assertEqual(self.default_llm.calls, 0)
        metric = self.sys.metrics.rag_hot_path_metrics(ans.correlation_id)[0]
        self.assertEqual(metric.model, "small-x")

    def test_unknown_model_falls_back_to_default_and_is_metered(self) -> None:
        service = self._answer_service({"small-x": self.small_llm})

        ans = service.answer(self.alice, QUERY, self._profile(llm_model="no-such-model"))

        self.assertEqual(ans.status, "ok")  # fail-open: routing misconfig never breaks answering
        self.assertEqual(self.default_llm.calls, 1)
        self.assertEqual(self.small_llm.calls, 0)
        self.assertEqual(
            self.sys.metrics.counter(
                "answer_llm_model_fallback_total",
                labels={
                    "tenant_id": T,
                    "profile_id": "default",
                    "requested_model": "no-such-model",
                },
            ),
            1.0,
        )
        metric = self.sys.metrics.rag_hot_path_metrics(ans.correlation_id)[0]
        self.assertEqual(metric.model, "default-model")

    def test_requesting_the_default_providers_own_model_name_is_not_a_fallback(self) -> None:
        service = self._answer_service({"small-x": self.small_llm})

        ans = service.answer(self.alice, QUERY, self._profile(llm_model="default-model"))

        self.assertEqual(ans.status, "ok")
        self.assertEqual(self.default_llm.calls, 1)
        self.assertEqual(
            self.sys.metrics.counter(
                "answer_llm_model_fallback_total",
                labels={
                    "tenant_id": T,
                    "profile_id": "default",
                    "requested_model": "default-model",
                },
            ),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
