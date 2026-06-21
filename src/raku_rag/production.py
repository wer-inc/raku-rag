"""Production composition root (001 Step 2): the MVP system on Postgres-backed persistence.

``ProductionSystem`` is the analog of ``app.MvpSystem`` but swaps the three persistence seams
(VectorStore / DocumentRegistry / ACL grants) for the Postgres adapters in ``persistence.postgres``.
Everything else — the services (retrieval/answer/deletion/groundedness), the deterministic
``HashingEmbeddingProvider``, parser/chunker/reranker/LLM, ``AclPolicy`` decision logic, ``TokenVerifier``,
``CacheService`` — is reused unchanged. It therefore exposes the exact public surface the security hard
gates exercise, so they run against real Postgres+RLS via adapter parity (see ``tests/helpers.fresh``).
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings
from raku_rag.core.security.token import TokenVerifier
from raku_rag.domain.models import JobStatus
from raku_rag.domain.models import QueryProfile
from raku_rag.observability.audit import InMemoryAuditSink
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.persistence.postgres import (
    PostgresAclPolicy,
    PostgresDocumentRegistry,
    PostgresIngestionRunStore,
    PostgresVectorStore,
    connect,
)
from raku_rag.providers.chunkers import SentenceChunker
from raku_rag.providers.embeddings import HashingEmbeddingProvider
from raku_rag.providers.llms import ExtractiveLLMProvider
from raku_rag.providers.parsers import TextParser
from raku_rag.providers.rerankers import ScoreOrderReranker
from raku_rag.providers.vlms import ExtractiveVLMProvider
from raku_rag.services.answer import AnswerService
from raku_rag.services.assets import AssetService
from raku_rag.services.cache import CacheService
from raku_rag.services.cost import CostService
from raku_rag.services.crop import CropService
from raku_rag.services.deletion import DeletionService
from raku_rag.services.groundedness import GroundednessGate
from raku_rag.services.ingestion import IngestionService
from raku_rag.services.profile import ProfileRegistry
from raku_rag.services.reindex import InMemoryReindexPlanStore, ReindexService
from raku_rag.services.retrieval import RetrievalService
from raku_rag.workers.ingestion import IngestionJobMessage, IngestionRun

if TYPE_CHECKING:
    from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata

DEFAULT_DSN = "postgresql://raku:raku@127.0.0.1:5432/raku_parity"


class ProductionSystem(MvpSystem):
    """MvpSystem wired onto Postgres (chunks/documents/acl_grants) with RLS.

    Inherits ``grant`` / ``ingest_text`` / ``answer`` / ``search`` from ``MvpSystem`` unchanged — only the
    persistence seams differ. ``reset=True`` is a TEST convenience (clean slate via TRUNCATE on connect).
    """

    def __init__(
        self, dsn: str = DEFAULT_DSN, settings: Settings | None = None, *, reset: bool = False
    ) -> None:
        self.settings = settings or Settings()
        self._conn = connect(dsn, reset=reset)

        # Postgres-backed persistence seams.
        self.registry = PostgresDocumentRegistry(self._conn)
        self.store = PostgresVectorStore(self._conn)
        self.acl = PostgresAclPolicy(self._conn)
        self.ingestion_runs = PostgresIngestionRunStore(self._conn)

        # Reused, unchanged from MvpSystem.
        self.embedder = HashingEmbeddingProvider(dim=self.settings.embedding_dim)
        self.parser = TextParser()
        self.chunker = SentenceChunker()
        self.reranker = ScoreOrderReranker()
        self.llm = ExtractiveLLMProvider()
        self.vlm = ExtractiveVLMProvider()
        self.cost = CostService()
        self.metrics = MetricsRecorder()
        self.tracer = InMemoryTracer()
        self.audit = InMemoryAuditSink()
        self.cache = CacheService()
        self.crops = CropService()
        self.profiles = ProfileRegistry(
            QueryProfile(
                score_threshold=self.settings.default_score_threshold,
                top_k=self.settings.default_top_k,
                minimum_evidence_count=self.settings.default_minimum_evidence_count,
                rerank_top_n=self.settings.rerank_top_n,
                max_context_tokens=self.settings.max_context_tokens,
                max_context_chunks=self.settings.max_context_chunks,
                max_synchronous_llm_calls=self.settings.max_synchronous_llm_calls,
            )
        )
        self.token_verifier = TokenVerifier(self.settings.token_signing_secret)

        # Same service wiring as MvpSystem, over the swapped seams.
        self.retrieval = RetrievalService(
            self.store,
            self.embedder,
            self.acl,
            self.reranker,
            self.cost,
            self.metrics,
            self.tracer,
        )
        self.gate = GroundednessGate()
        self.ingestion = IngestionService(
            self.store,
            self.embedder,
            self.parser,
            self.chunker,
            self.registry,
            self.metrics,
            self.tracer,
        )
        self.answer_service = AnswerService(
            self.retrieval,
            self.llm,
            self.gate,
            self.cost,
            self.registry.get,
            self.metrics,
            self.tracer,
            self.audit,
            self.vlm,
        )
        self.deletion = DeletionService(
            self.store, self.registry, self.cache, crop_store=self.crops.store
        )
        self.assets = AssetService(self.registry, self.store, self.acl, self.crops.store)
        self.reindex_plans = InMemoryReindexPlanStore()
        self.reindex = ReindexService(
            self.store, self.embedder, self.parser, self.chunker, self.registry, self.reindex_plans
        )

    def ingest_document(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        document_ref: str,
        raw: bytes,
        content_type: str = "text/plain",
        manufacturing_metadata: "ManufacturingDocumentMetadata | None" = None,
    ) -> IngestionRun:
        """Run the ingestion service through the same status projection used by the worker.

        P1-1: when ``manufacturing_metadata`` is supplied (the deployed ingest boundary passes it from
        the request's ``manufacturing`` block), persist it onto the Document on success so the safety
        overlay can resolve approval state for production-ingested docs — not just in-memory fixtures.
        """
        checksum = hashlib.sha256(raw).hexdigest()
        message = IngestionJobMessage(
            idempotency_key=f"api:{collection_id}:{source_id}:{document_id}:{checksum}",
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            document_ref=document_ref,
            content_type=content_type,
        )
        run, created = self.ingestion_runs.create_queued(message, trigger="api")
        if not created and run.status == JobStatus.SUCCEEDED.value:
            return run

        self.ingestion_runs.mark_running(run)
        job = self.ingestion.ingest(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            raw=raw,
            content_type=content_type,
        )
        if job.status == JobStatus.SUCCEEDED.value:
            self.ingestion_runs.mark_succeeded(run, chunk_count=job.chunk_count)
            if manufacturing_metadata is not None:
                # Persist mfg approval metadata so the safety overlay (high-risk gate, draft/obsolete
                # demotion) fires for this production-ingested document (P1-1 write path).
                self.attach_manufacturing_metadata(tenant_id, document_id, manufacturing_metadata)
        else:
            self.ingestion_runs.mark_failed(
                run, reason=job.failure_reason or "ingestion failed", retry_count=0
            )

        refreshed = self.ingestion_runs.get_for_tenant(tenant_id, run.ingestion_run_id)
        return refreshed or run

    def attach_manufacturing_metadata(
        self, tenant_id: str, document_id: str, metadata: "ManufacturingDocumentMetadata"
    ) -> "ManufacturingDocumentMetadata | None":
        """P1-1: persist ``ManufacturingDocumentMetadata`` onto the Postgres ``Document.metadata`` as a
        jsonb-safe mapping (``to_mapping()``), so the safety overlay's registry resolver reads it back
        (``from_mapping``) over the DEPLOYED ProductionSystem — not only the in-memory MvpSystem.

        The overlay resolves per-document approval state from ``Document.metadata``; the in-memory path
        can stash the dataclass, but a dataclass does not survive a jsonb round-trip, so the deployed
        path persists the mapping form. Returns the metadata, or ``None`` if the document is absent.
        """
        from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY

        doc = self.registry.get(tenant_id, document_id)
        if doc is None:
            return None
        doc.metadata[MFG_META_KEY] = metadata.to_mapping()
        self.registry.put(doc)
        return metadata

    def ingest_manufacturing(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        document_id: str,
        text: str,
        metadata: "ManufacturingDocumentMetadata",
        source_id: str = "src",
    ):
        """P1-1 deployed manufacturing ingest: run the reused 001 text-ingest path then persist the
        manufacturing metadata (jsonb-safe) so the safety overlay runs over real Postgres. Mirrors
        ``ManufacturingSystem.ingest_manufacturing`` but persists ``to_mapping()`` into
        ``Document.metadata`` for the Postgres round-trip (the resolver reads it via ``from_mapping``).
        """
        job = self.ingest_text(
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            text=text,
            source_id=source_id,
        )
        self.attach_manufacturing_metadata(tenant_id, document_id, metadata)
        return job

    def retry_ingestion_run(
        self, *, tenant_id: str, ingestion_run_id: str, raw: bytes
    ) -> IngestionRun | None:
        previous = self.ingestion_runs.get_for_tenant(tenant_id, ingestion_run_id)
        if previous is None:
            return None
        return self.ingest_document(
            tenant_id=tenant_id,
            collection_id=previous.collection_id,
            source_id=previous.source_id,
            document_id=previous.document_id,
            document_ref=previous.document_ref,
            raw=raw,
            content_type=previous.content_type,
        )

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover - best-effort teardown
            pass

    def __del__(self) -> None:  # pragma: no cover - GC-time best-effort
        self.close()
