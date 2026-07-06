"""MVP composition root: wires the stdlib in-memory adapters into a working RAG system.

This is the single place that assembles interfaces + providers + services for US1/US2. The
production entrypoint will assemble the FastAPI/pgvector/Arq adapters behind the same interfaces.
"""

from __future__ import annotations

from datetime import datetime, timezone

from raku_rag.core.config import Settings
from raku_rag.core.security.acl import AclPolicy
from raku_rag.core.security.token import TokenVerifier
from raku_rag.domain.models import (
    ACLGrant,
    Answer,
    Document,
    IdentityClaims,
    QueryProfile,
    ScopeType,
    SubjectType,
)
from raku_rag.providers.chunkers import SentenceChunker
from raku_rag.providers.embeddings import embedding_provider_from_settings
from raku_rag.providers.llms import ExtractiveLLMProvider
from raku_rag.providers.parsers import CompositeParser, DocxParser, SpreadsheetParser, TextParser
from raku_rag.providers.rerankers import ScoreOrderReranker
from raku_rag.providers.vectorstores import InMemoryVectorStore
from raku_rag.providers.visual_embeddings import HashingVisualEmbeddingProvider
from raku_rag.providers.vlms import ExtractiveVLMProvider
from raku_rag.observability.audit import InMemoryAuditSink
from raku_rag.observability.exporters import exporter_from_settings
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.services.answer import AnswerService
from raku_rag.services.assets import AssetService
from raku_rag.services.cache import CacheService
from raku_rag.services.cost import CostService
from raku_rag.services.crop import CropService
from raku_rag.services.deletion import DeletionService
from raku_rag.services.groundedness import GroundednessGate
from raku_rag.services.ingestion import DocumentRegistry, IngestionService
from raku_rag.services.profile import ProfileRegistry
from raku_rag.services.reindex import InMemoryReindexPlanStore, ReindexService
from raku_rag.services.retrieval import RetrievalService
from raku_rag.services.structured_tables import TableManifestStructuredTool
from raku_rag.services.visual import visual_chunks_from_ingestion
from raku_rag.workers.ingestion import VisualIngestionExecutor, VisualIngestionOptions


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MvpSystem:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.registry = DocumentRegistry()
        self.store = InMemoryVectorStore()
        self.embedder = embedding_provider_from_settings(self.settings)
        self.parser = CompositeParser([TextParser(), DocxParser(), SpreadsheetParser()])
        self.chunker = SentenceChunker()
        self.reranker = ScoreOrderReranker()
        self.llm = ExtractiveLLMProvider()
        self.vlm = ExtractiveVLMProvider()
        self.acl = AclPolicy([])
        self.cost = CostService()
        self.telemetry_exporter = exporter_from_settings(self.settings)
        self.metrics = MetricsRecorder(exporter=self.telemetry_exporter)
        self.tracer = InMemoryTracer(exporter=self.telemetry_exporter)
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

        self.retrieval = RetrievalService(
            self.store,
            self.embedder,
            self.acl,
            self.reranker,
            self.cost,
            self.metrics,
            self.tracer,
            # ★G5: query-embedding cache (same wiring as ProductionSystem so the deterministic
            # gate exercises the cached path; the hashing embedder is cheap but correctness is
            # identical).
            cache=self.cache,
        )
        self.gate = GroundednessGate()
        self.structured_tool = TableManifestStructuredTool(self.registry, self.acl)
        self.ingestion = IngestionService(
            self.store,
            self.embedder,
            self.parser,
            self.chunker,
            self.registry,
            self.metrics,
            self.tracer,
            pii_redaction_mode=self.settings.pii_redaction_mode,
        )
        # ADR-018 B5: opt-in Docling-first structured ingestion. Legacy self.ingestion is left intact
        # (visual executor / reindex reach into it); only the ingest ENTRYPOINT is switched.
        self.structured_ingestion = None
        if self.settings.structured_ingest_enabled:
            from raku_rag.services.structured_ingestion import build_structured_ingestion_service

            self.structured_ingestion = build_structured_ingestion_service(
                store=self.store,
                embedder=self.embedder,
                registry=self.registry,
                metrics=self.metrics,
                tracer=self.tracer,
                pii_redaction_mode=self.settings.pii_redaction_mode,
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
            structured_tool=self.structured_tool,
            settings=self.settings,
        )
        self.deletion = DeletionService(
            self.store, self.registry, self.cache, crop_store=self.crops.store
        )
        self.assets = AssetService(self.registry, self.store, self.acl, self.crops.store)
        self.reindex_plans = InMemoryReindexPlanStore()
        self.reindex = ReindexService(
            self.store, self.embedder, self.parser, self.chunker, self.registry, self.reindex_plans
        )

    # --- convenience admin helpers (admin API analog) ---
    def grant(
        self,
        tenant_id: str,
        scope_type: ScopeType,
        scope_id: str,
        subject_type: SubjectType,
        subject_id: str,
    ) -> None:
        self.acl.add(ACLGrant(tenant_id, scope_type, scope_id, subject_type, subject_id))

    @property
    def _ingest(self):
        """Active ingest service: the opt-in structured one when enabled, else the legacy one.

        Resolved dynamically (not cached) so callers/tests that swap ``self.ingestion`` still take
        effect when structured ingestion is off (the default).
        """
        return self.structured_ingestion or self.ingestion

    def ingest_text(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        document_id: str,
        text: str,
        source_id: str = "src",
        chunking_metadata: dict | None = None,
    ):
        return self._ingest.ingest(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            raw=text.encode("utf-8"),
            content_type="text/plain",
            chunking_metadata=chunking_metadata,
        )

    def list_extraction_reviews(self, tenant_id: str) -> list[dict]:
        """ADR-018 §12.1 — the extraction review queue for a tenant (quarantined chunks) as dicts."""

        from raku_rag.services.ingestion_quality import extraction_review_queue

        return [
            {
                "tenant_id": item.tenant_id,
                "document_id": item.document_id,
                "chunk_id": item.chunk_id,
                "status": item.status,
                "reasons": list(item.reasons),
                "page_no": item.page_no,
                "anchor_type": item.anchor_type,
                "bbox": list(item.bbox) if item.bbox is not None else None,
                "text_snippet": item.text_snippet,
                "suggested_action": item.suggested_action,
            }
            for item in extraction_review_queue(self.store, tenant_id=tenant_id)
        ]

    def extraction_quality_metrics(self, tenant_id: str) -> dict:
        """ADR-018 §18 — the extraction quality-gate ops metrics for a tenant."""

        from raku_rag.services.ingestion_quality import extraction_quality_stats

        return extraction_quality_stats(self.store, tenant_id=tenant_id)

    def apply_extraction_review_action(
        self,
        *,
        tenant_id: str,
        chunk_id: str,
        action: str,
        actor: str,
        corrected_text: str | None = None,
        reason: str = "",
    ) -> dict:
        """ADR-018 §12.2 — apply a reviewer decision to a quarantined chunk; returns the outcome."""

        from raku_rag.services.review_actions import ReviewActionService

        service = ReviewActionService(self.store, self.embedder, audit=self.audit)
        decision = service.apply(
            tenant_id=tenant_id,
            chunk_id=chunk_id,
            action=action,
            actor=actor,
            corrected_text=corrected_text,
            reason=reason,
        )
        return {
            "chunk_id": decision.chunk_id,
            "action": decision.action,
            "status": decision.status,
            "reviewed_by": decision.reviewed_by,
            "reviewed_at": decision.reviewed_at,
            "high_risk_citation_eligible": decision.high_risk_citation_eligible,
            "retrieval_eligible": decision.retrieval_eligible,
        }

    def ingest_visual_fixture(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        document_id: str,
        image: bytes,
        source_id: str = "visual",
        exif_metadata: dict | None = None,
        captioning_enabled: bool = True,
    ):
        executor = VisualIngestionExecutor(
            visual_embedder=HashingVisualEmbeddingProvider(dim=self.settings.embedding_dim),
            cost=self.cost,
        )
        result = executor.execute_image(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            image=image,
            exif_metadata=exif_metadata,
            options=VisualIngestionOptions(captioning_enabled=captioning_enabled),
            job_id=f"visual:{document_id}",
        )
        chunks = visual_chunks_from_ingestion(result)
        self.store.upsert(list(zip(chunks, result.visual_vectors)))
        existing = self.registry.get(tenant_id, document_id)
        self.registry.put(
            Document(
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                source_id=source_id,
                version=(existing.version + 1) if existing else 1,
                checksum=result.asset.checksum,
                metadata={
                    "visual_asset_ids": [result.asset.asset_id],
                    "caption_status": result.caption_status,
                    "exif_removed_keys": list(result.exif_removed_keys),
                },
                created_at=existing.created_at if existing else _now(),
                updated_at=_now(),
                indexed_at=_now(),
                tombstone=False,
            )
        )
        return result

    def answer(
        self, principal: IdentityClaims, query: str, collection_id: str | None = None
    ) -> Answer:
        return self.answer_service.answer(
            principal, query, self.profiles.resolve(collection_id), collection_id=collection_id
        )

    def search(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None = None,
        *,
        correlation_id: str = "",
    ):
        return self.retrieval.retrieve(
            principal,
            query,
            self.profiles.resolve(collection_id),
            correlation_id=correlation_id,
        )
