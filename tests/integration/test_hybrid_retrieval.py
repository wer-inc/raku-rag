"""P1-7 / PR-007 — core retrieval has an identifier exact-match leg.

The deployed answer path must not rely on vector similarity alone for business identifiers such as
equipment IDs and alarm codes. These tests pin the core RetrievalService behavior, not a facade-only
implementation.
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
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.providers.rerankers import ScoreOrderReranker
from raku_rag.providers.vectorstores import InMemoryVectorStore
from raku_rag.services.retrieval import RetrievalService

T = "hybrid_tenant"


class _StaticEmbedder:
    model_version = "static-test"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _chunk(
    *,
    chunk_id: str,
    document_id: str,
    collection_id: str,
    text: str,
    metadata: dict | None = None,
    tombstone: bool = False,
) -> Chunk:
    return Chunk(
        tenant_id=T,
        chunk_id=chunk_id,
        document_id=document_id,
        collection_id=collection_id,
        text=text,
        metadata=metadata or {},
        tombstone=tombstone,
    )


class TestHybridRetrieval(unittest.TestCase):
    def _service(self, acl: AclPolicy, metrics: MetricsRecorder, tracer: InMemoryTracer):
        return RetrievalService(
            self.store,
            _StaticEmbedder(),
            acl,
            ScoreOrderReranker(),
            metrics=metrics,
            tracer=tracer,
        )

    def setUp(self) -> None:
        self.store = InMemoryVectorStore()
        self.alice = IdentityClaims(tenant_id=T, user_id="alice")

    def test_identifier_metadata_exact_match_beats_vector_only_order(self) -> None:
        target_meta = ManufacturingDocumentMetadata(
            tenant_id=T,
            document_id="target",
            equipment_id="EQ-PRESS-100",
            alarm_code="E-142",
        )
        target = _chunk(
            chunk_id="target:0",
            document_id="target",
            collection_id="c",
            text="Reset the thermal sensor after confirming the press is locked out.",
            metadata={MFG_META_KEY: target_meta},
        )
        vector_favorite = _chunk(
            chunk_id="distractor:0",
            document_id="distractor",
            collection_id="c",
            text="Generic maintenance notes with stronger vector similarity.",
        )
        self.store.upsert(
            [
                (target, [0.0, 1.0]),
                (vector_favorite, [1.0, 0.0]),
            ]
        )
        acl = AclPolicy([ACLGrant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")])
        metrics = MetricsRecorder()
        tracer = InMemoryTracer()
        profile = QueryProfile(top_k=1, rerank_enabled=True, rerank_top_n=5)

        result = self._service(acl, metrics, tracer).retrieve(
            self.alice,
            "What should I check for alarm E-142 on EQ-PRESS-100?",
            profile,
            correlation_id="hybrid-cid",
        )

        self.assertEqual([s.chunk.document_id for s in result], ["target"])
        labels = {"tenant_id": T, "profile_id": profile.profile_id}
        self.assertEqual(
            metrics.observations("retrieval_metadata_exact_match_count", labels=labels)[-1],
            1,
        )
        span = tracer.spans(correlation_id="hybrid-cid")[0]
        self.assertEqual(span.attributes.get("metadata_exact_match_count"), 1)
        self.assertEqual(span.attributes.get("query_intent"), "procedure")
        self.assertGreaterEqual(span.attributes.get("query_identifier_count"), 2)
        self.assertIn("business_identifiers", span.attributes.get("query_filter_hints"))

    def test_identifier_exact_match_still_respects_acl_prefilter(self) -> None:
        hidden_exact = _chunk(
            chunk_id="hidden:0",
            document_id="hidden",
            collection_id="secret",
            text="Secret handling for alarm E-999 on EQ-SECRET-1.",
            metadata={"equipment_id": "EQ-SECRET-1", "alarm_code": "E-999"},
        )
        visible_vector = _chunk(
            chunk_id="visible:0",
            document_id="visible",
            collection_id="visible",
            text="Public maintenance note.",
        )
        self.store.upsert(
            [
                (hidden_exact, [0.0, 1.0]),
                (visible_vector, [1.0, 0.0]),
            ]
        )
        acl = AclPolicy([ACLGrant(T, ScopeType.COLLECTION, "visible", SubjectType.USER, "alice")])
        metrics = MetricsRecorder()
        tracer = InMemoryTracer()
        profile = QueryProfile(top_k=5, rerank_enabled=False)

        result = self._service(acl, metrics, tracer).retrieve(
            self.alice,
            "How do we resolve E-999 on EQ-SECRET-1?",
            profile,
            correlation_id="hybrid-acl-cid",
        )

        self.assertEqual([s.chunk.document_id for s in result], ["visible"])
        self.assertNotIn("hidden", {s.chunk.document_id for s in result})
        labels = {"tenant_id": T, "profile_id": profile.profile_id}
        self.assertEqual(
            metrics.observations("retrieval_metadata_exact_match_count", labels=labels)[-1],
            0,
        )

    def test_lexical_match_beats_vector_only_order_for_keyword_query(self) -> None:
        target = _chunk(
            chunk_id="lexical:0",
            document_id="lexical",
            collection_id="c",
            text="The torque cascade resonance procedure requires a guarded shutdown.",
        )
        vector_favorite = _chunk(
            chunk_id="distractor:0",
            document_id="distractor",
            collection_id="c",
            text="Generic maintenance notes with stronger vector similarity.",
        )
        self.store.upsert(
            [
                (target, [0.0, 1.0]),
                (vector_favorite, [1.0, 0.0]),
            ]
        )
        acl = AclPolicy([ACLGrant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")])
        metrics = MetricsRecorder()
        tracer = InMemoryTracer()
        profile = QueryProfile(top_k=1, rerank_enabled=True, rerank_top_n=5)

        result = self._service(acl, metrics, tracer).retrieve(
            self.alice,
            "torque cascade resonance procedure",
            profile,
            correlation_id="lexical-cid",
        )

        self.assertEqual([s.chunk.document_id for s in result], ["lexical"])
        labels = {"tenant_id": T, "profile_id": profile.profile_id}
        self.assertEqual(
            metrics.observations("retrieval_lexical_match_count", labels=labels)[-1], 1
        )
        span = tracer.spans(correlation_id="lexical-cid")[0]
        self.assertEqual(span.attributes.get("lexical_match_count"), 1)
        self.assertEqual(span.attributes.get("query_intent"), "procedure")

    def test_lexical_match_uses_recency_as_tie_breaker(self) -> None:
        current = _chunk(
            chunk_id="current:0",
            document_id="current",
            collection_id="c",
            text="Inspection cadence for the sealing station is weekly.",
            metadata={"effective_date": "2026-01-01"},
        )
        stale = _chunk(
            chunk_id="stale:0",
            document_id="stale",
            collection_id="c",
            text="Inspection cadence for the sealing station is weekly.",
            metadata={"effective_date": "2020-01-01"},
        )
        self.store.upsert(
            [
                (stale, [0.0, 1.0]),
                (current, [0.0, 1.0]),
            ]
        )
        acl = AclPolicy([ACLGrant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")])
        profile = QueryProfile(top_k=1, rerank_enabled=True, rerank_top_n=5)

        result = self._service(acl, MetricsRecorder(), InMemoryTracer()).retrieve(
            self.alice,
            "inspection cadence sealing station",
            profile,
            correlation_id="lexical-recency-cid",
        )

        self.assertEqual([s.chunk.document_id for s in result], ["current"])

    def test_query_plan_document_kind_hint_boosts_visible_candidate_order(self) -> None:
        procedure_doc = _chunk(
            chunk_id="procedure:0",
            document_id="procedure",
            collection_id="c",
            text="Pump maintenance details.",
            metadata={"document_kind": "work_instruction"},
        )
        vector_favorite = _chunk(
            chunk_id="generic:0",
            document_id="generic",
            collection_id="c",
            text="Generic maintenance details.",
            metadata={"document_kind": "quality_report"},
        )
        self.store.upsert(
            [
                (procedure_doc, [0.98, 0.20]),
                (vector_favorite, [1.0, 0.0]),
            ]
        )
        acl = AclPolicy([ACLGrant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")])
        metrics = MetricsRecorder()
        tracer = InMemoryTracer()
        profile = QueryProfile(top_k=1, rerank_enabled=False)

        result = self._service(acl, metrics, tracer).retrieve(
            self.alice,
            "procedure steps for pump maintenance",
            profile,
            correlation_id="planner-boost-cid",
        )

        self.assertEqual([s.chunk.document_id for s in result], ["procedure"])
        span = tracer.spans(correlation_id="planner-boost-cid")[0]
        self.assertEqual(span.attributes.get("query_intent"), "procedure")


if __name__ == "__main__":
    unittest.main()
