"""★G5 — query-embedding cache: hit/miss metrics, tenant/model-version keys, fail-open, LRU cap.

The cache saves the per-request query-embedding call (a paid API call with real providers). It must
never change retrieval results, never break retrieval when the cache itself fails, and never serve
vectors across tenants or embedding-model versions.
"""

from __future__ import annotations

import unittest
from typing import Sequence

from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import (
    ACLGrant,
    Chunk,
    IdentityClaims,
    QueryProfile,
    ScopeType,
    SubjectType,
)
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.providers.vectorstores import InMemoryVectorStore
from raku_rag.services.cache import CacheService
from raku_rag.services.retrieval import RetrievalService

T = "cache_tenant"
LABELS = {"tenant_id": T, "profile_id": "default"}


class _CountingEmbedder:
    def __init__(self, model_version: str = "counting-v1") -> None:
        self.model_version = model_version
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return [[1.0, 0.0] for _ in texts]


class _BrokenCache:
    def get(self, tenant_id: str, key: str):
        raise RuntimeError("cache backend down")

    def put(self, *args, **kwargs) -> None:
        raise RuntimeError("cache backend down")


def _chunk(chunk_id: str = "ch1") -> Chunk:
    return Chunk(
        tenant_id=T,
        chunk_id=chunk_id,
        document_id="d1",
        collection_id="c",
        text="Backups run nightly at 02:00 UTC.",
    )


class TestEmbedQueryCache(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryVectorStore()
        self.store.upsert([(_chunk(), [1.0, 0.0])])
        self.acl = AclPolicy([ACLGrant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")])
        self.alice = IdentityClaims(tenant_id=T, user_id="alice")
        self.metrics = MetricsRecorder()
        self.tracer = InMemoryTracer()
        self.profile = QueryProfile()

    def _service(self, embedder, cache) -> RetrievalService:
        return RetrievalService(
            self.store,
            embedder,
            self.acl,
            metrics=self.metrics,
            tracer=self.tracer,
            cache=cache,
        )

    def test_second_identical_query_hits_cache_and_skips_embedding(self) -> None:
        embedder = _CountingEmbedder()
        service = self._service(embedder, CacheService())

        first = service.retrieve(self.alice, "backup schedule", self.profile, correlation_id="r1")
        second = service.retrieve(self.alice, "backup schedule", self.profile, correlation_id="r2")

        self.assertEqual(embedder.calls, 1)  # the hit skipped the embed call
        self.assertEqual([s.chunk.chunk_id for s in first], [s.chunk.chunk_id for s in second])
        self.assertEqual(self.metrics.counter("embedding_cache_misses_total", labels=LABELS), 1.0)
        self.assertEqual(self.metrics.counter("embedding_cache_hits_total", labels=LABELS), 1.0)
        spans = {
            span.correlation_id: span
            for span in self.tracer.spans()
            if span.name == "retrieval.retrieve"
        }
        self.assertFalse(spans["r1"].attributes["embed_cache_hit"])
        self.assertTrue(spans["r2"].attributes["embed_cache_hit"])

    def test_different_query_misses(self) -> None:
        embedder = _CountingEmbedder()
        service = self._service(embedder, CacheService())

        service.retrieve(self.alice, "backup schedule", self.profile)
        service.retrieve(self.alice, "retention period", self.profile)

        self.assertEqual(embedder.calls, 2)
        self.assertEqual(self.metrics.counter("embedding_cache_hits_total", labels=LABELS), 0.0)

    def test_cache_is_tenant_scoped(self) -> None:
        embedder = _CountingEmbedder()
        service = self._service(embedder, CacheService())
        bob = IdentityClaims(tenant_id="other_tenant", user_id="bob")

        service.retrieve(self.alice, "backup schedule", self.profile)
        service.retrieve(bob, "backup schedule", self.profile)

        # Same query text, different tenant → no cross-tenant hit.
        self.assertEqual(embedder.calls, 2)
        self.assertEqual(self.metrics.counter("embedding_cache_hits_total", labels=LABELS), 0.0)

    def test_embedding_model_version_is_part_of_the_key(self) -> None:
        cache = CacheService()
        old = _CountingEmbedder(model_version="model-v1")
        new = _CountingEmbedder(model_version="model-v2")

        self._service(old, cache).retrieve(self.alice, "backup schedule", self.profile)
        self._service(new, cache).retrieve(self.alice, "backup schedule", self.profile)

        # A provider/version swap must never serve vectors from the old model.
        self.assertEqual(old.calls, 1)
        self.assertEqual(new.calls, 1)

    def test_cache_errors_fail_open(self) -> None:
        embedder = _CountingEmbedder()
        service = self._service(embedder, _BrokenCache())

        result = service.retrieve(self.alice, "backup schedule", self.profile)

        self.assertEqual([s.chunk.chunk_id for s in result], ["ch1"])
        self.assertEqual(embedder.calls, 1)
        self.assertGreaterEqual(
            self.metrics.counter("embedding_cache_errors_total", labels=LABELS), 1.0
        )

    def test_no_cache_default_is_unchanged(self) -> None:
        embedder = _CountingEmbedder()
        service = self._service(embedder, None)

        service.retrieve(self.alice, "backup schedule", self.profile)
        service.retrieve(self.alice, "backup schedule", self.profile)

        self.assertEqual(embedder.calls, 2)
        self.assertEqual(self.metrics.counter("embedding_cache_misses_total", labels=LABELS), 0.0)

    def test_embedding_cost_recorded_only_on_miss(self) -> None:
        from raku_rag.services.cost import CostService

        cost = CostService()
        embedder = _CountingEmbedder()
        service = RetrievalService(
            self.store,
            embedder,
            self.acl,
            cost=cost,
            metrics=self.metrics,
            cache=CacheService(),
        )

        service.retrieve(self.alice, "backup schedule", self.profile)
        service.retrieve(self.alice, "backup schedule", self.profile)

        embed_records = [r for r in cost.records(T) if r.kind == "embedding_tokens"]
        self.assertEqual(len(embed_records), 1)  # a hit incurs no embedding cost


class TestAnswerHotPathCacheHit(unittest.TestCase):
    def test_cache_hit_reaches_rag_hot_path_metric(self) -> None:
        from raku_rag.domain.models import ScopeType as ST
        from raku_rag.domain.models import SubjectType as SU
        from tests.helpers import claims, fresh

        sys = fresh()
        sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Backups run nightly at 02:00 UTC and are retained for thirty days.",
        )
        sys.grant(T, ST.COLLECTION, "c", SU.USER, "alice")
        alice = claims(T, "alice")
        query = "when do backups run and how long are they retained?"

        first = sys.answer(alice, query)
        second = sys.answer(alice, query)

        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "ok")
        first_metric = sys.metrics.rag_hot_path_metrics(first.correlation_id)[0]
        second_metric = sys.metrics.rag_hot_path_metrics(second.correlation_id)[0]
        self.assertFalse(first_metric.cache_hit)
        self.assertTrue(second_metric.cache_hit)


class TestCacheServiceLruCap(unittest.TestCase):
    def test_put_evicts_least_recently_used_per_tenant(self) -> None:
        cache = CacheService(max_entries_per_tenant=2)
        cache.put(T, "k1", "v1", set())
        cache.put(T, "k2", "v2", set())
        cache.put(T, "k3", "v3", set())

        self.assertIsNone(cache.get(T, "k1"))  # oldest evicted
        self.assertEqual(cache.get(T, "k2"), "v2")
        self.assertEqual(cache.get(T, "k3"), "v3")

    def test_get_refreshes_recency(self) -> None:
        cache = CacheService(max_entries_per_tenant=2)
        cache.put(T, "k1", "v1", set())
        cache.put(T, "k2", "v2", set())
        self.assertEqual(cache.get(T, "k1"), "v1")  # k1 becomes most recently used
        cache.put(T, "k3", "v3", set())

        self.assertEqual(cache.get(T, "k1"), "v1")
        self.assertIsNone(cache.get(T, "k2"))  # k2 was the LRU entry
        self.assertEqual(cache.get(T, "k3"), "v3")

    def test_cap_is_per_tenant(self) -> None:
        cache = CacheService(max_entries_per_tenant=1)
        cache.put(T, "k1", "v1", set())
        cache.put("other_tenant", "k1", "other", set())

        # The other tenant's put must not evict this tenant's entry.
        self.assertEqual(cache.get(T, "k1"), "v1")
        self.assertEqual(cache.get("other_tenant", "k1"), "other")

    def test_overwrite_same_key_does_not_evict(self) -> None:
        cache = CacheService(max_entries_per_tenant=2)
        cache.put(T, "k1", "v1", set())
        cache.put(T, "k2", "v2", set())
        cache.put(T, "k1", "v1b", set())  # overwrite, not a new entry

        self.assertEqual(cache.get(T, "k1"), "v1b")
        self.assertEqual(cache.get(T, "k2"), "v2")

    def test_document_invalidation_behaviour_is_preserved(self) -> None:
        cache = CacheService(max_entries_per_tenant=2)
        cache.put(T, "answer:q1", "cached-answer", {"d1"})
        cache.put(T, "embed:v1:qhash", (1.0, 0.0), set())

        removed = cache.invalidate_document(T, "d1")

        self.assertEqual(removed, 1)
        self.assertIsNone(cache.get(T, "answer:q1"))
        # Embedding entries are content-independent and survive document deletion by design.
        self.assertEqual(cache.get(T, "embed:v1:qhash"), (1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
