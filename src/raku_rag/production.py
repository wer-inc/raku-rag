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
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings
from raku_rag.core.security.token import TokenVerifier
from raku_rag.domain.models import Document, JobStatus
from raku_rag.domain.models import QueryProfile
from raku_rag.manufacturing.safety.visual_verify import visual_verifiers_from_settings
from raku_rag.observability.exporters import exporter_from_settings
from raku_rag.observability.langfuse_client import build_langfuse_client
from raku_rag.observability.metrics import MetricsRecorder
from raku_rag.observability.tracing import InMemoryTracer
from raku_rag.persistence.postgres import (
    PostgresAclPolicy,
    PostgresAuditSink,
    PostgresDocumentRegistry,
    PostgresProviderPolicyRepository,
    PostgresIngestionRunStore,
    PostgresVectorStore,
    connect,
)
from raku_rag.persistence.telemetry import (
    PostgresCostRecordSink,
    PostgresQueryTraceSink,
    PostgresRerankTraceSink,
)
from raku_rag.providers.chunkers import SentenceChunker
from raku_rag.providers.embeddings import embedding_provider_from_settings
from raku_rag.providers.guardrails import guardrail_from_settings
from raku_rag.providers.llms import llm_provider_from_settings
from raku_rag.providers.parsers import (
    CompositeParser,
    DocxParser,
    SpreadsheetParser,
    TextParser,
)
from raku_rag.providers.rerankers import reranker_from_settings
from raku_rag.providers.visual import (
    async_document_analyzer_from_settings,
    captioning_from_settings,
    layout_from_settings,
    ocr_from_settings,
    structured_from_settings,
    vlm_from_settings,
    visual_embedding_from_settings,
)
from raku_rag.services.answer import AnswerService
from raku_rag.services.assets import AssetService
from raku_rag.services.cache import CacheService
from raku_rag.services.cost import CostService
from raku_rag.services.crop import crop_service_from_settings
from raku_rag.services.deletion import DeletionService
from raku_rag.services.groundedness import GroundednessGate
from raku_rag.services.ingestion import IngestionService
from raku_rag.services.profile import ProfileRegistry
from raku_rag.services.reindex import InMemoryReindexPlanStore, ReindexService
from raku_rag.services.retrieval import RetrievalService
from raku_rag.services.structured_tables import TableManifestStructuredTool
from raku_rag.workers.ingestion import (
    IngestionExecutor,
    IngestionJobMessage,
    IngestionRun,
    VisualIngestionExecutor,
)
from workers.ingest.providers.visual import (
    AsyncDocumentAnalyzerPolicyRouter,
    CaptionPolicyRouter,
    LayoutPolicyRouter,
    OcrPolicyRouter,
    VisualEmbeddingPolicyRouter,
    VlmPolicyRouter,
)

if TYPE_CHECKING:
    from raku_rag.manufacturing.app import ManufacturingSystem
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
        self.store = PostgresVectorStore(self._conn, embedding_dim=self.settings.embedding_dim)
        self.acl = PostgresAclPolicy(self._conn)
        self.ingestion_runs = PostgresIngestionRunStore(self._conn)
        self.provider_policies = PostgresProviderPolicyRepository(self._conn)

        # Reused, unchanged from MvpSystem.
        self.embedder = embedding_provider_from_settings(self.settings)
        # Upload-driven ingestion (goal.md Priority #2) accepts text/markdown/html + DOCX (Word)
        # + XLSX/CSV (Excel) — PDF needs an optional pypdf parser (not installed here).
        self.parser = CompositeParser([TextParser(), DocxParser(), SpreadsheetParser()])
        self.chunker = SentenceChunker()
        # P1-1/P1-3/P1-4: select generator + reranker + output guardrail by runtime profile. The
        # deterministic default keeps Tier-A fast and the deployed default behaviour unchanged;
        # production selects the real Bedrock adapters (fail-closed for generation/guardrail,
        # fail-safe-to-score-order for rerank per FR-030). guardrail is None under deterministic (the
        # stdlib PromptInjectionGuard still runs in the answer flow).
        self.reranker = reranker_from_settings(self.settings)
        self.llm = llm_provider_from_settings(self.settings)
        self.guardrail = guardrail_from_settings(self.settings)
        self.ocr = _wrap_provider_policy(
            ocr_from_settings(self.settings), OcrPolicyRouter, self.provider_policies
        )
        self.layout = _wrap_provider_policy(
            layout_from_settings(self.settings), LayoutPolicyRouter, self.provider_policies
        )
        self.structured = _wrap_provider_policy(
            structured_from_settings(self.settings), None, self.provider_policies
        )
        self.captioning = _wrap_provider_policy(
            captioning_from_settings(self.settings),
            CaptionPolicyRouter,
            self.provider_policies,
        )
        self.vlm = _wrap_provider_policy(
            vlm_from_settings(self.settings), VlmPolicyRouter, self.provider_policies
        )
        self.visual_embedder = _wrap_provider_policy(
            visual_embedding_from_settings(self.settings),
            VisualEmbeddingPolicyRouter,
            self.provider_policies,
        )
        self.async_document_analyzer = _wrap_provider_policy(
            async_document_analyzer_from_settings(self.settings),
            AsyncDocumentAnalyzerPolicyRouter,
            self.provider_policies,
        )
        # ★G1: durable per-query telemetry (goal.md §2-5). Reference-only rows — no raw
        # query/answer text — and every sink is fail-open so answering never depends on them.
        self.cost = CostService(sink=PostgresCostRecordSink(self._conn))
        self.telemetry_exporter = exporter_from_settings(
            self.settings, langfuse_client=build_langfuse_client(self.settings)
        )
        self.metrics = MetricsRecorder(
            exporter=self.telemetry_exporter,
            hot_path_sink=PostgresQueryTraceSink(self._conn),
        )
        self.tracer = InMemoryTracer(exporter=self.telemetry_exporter)
        self.audit = PostgresAuditSink(self._conn)
        self.cache = CacheService()
        self.crops = crop_service_from_settings(self.settings)
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
            rerank_trace_sink=PostgresRerankTraceSink(self._conn),
            # ★G5: query-embedding cache — repeats of the same query skip the (paid) embedding
            # call. Tenant/model-version-scoped keys; LRU-capped per tenant inside CacheService.
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
        # ADR-018 B5: opt-in Docling-first structured ingestion (mirrors MvpSystem; ProductionSystem
        # does not call super().__init__ so the flag wiring is repeated here). Default OFF. The worker
        # IngestionExecutor still uses the legacy self.ingestion (visual/OCR internals) — only the
        # ingest_text entrypoint is switched.
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
        self.visual_ingestion_executor = VisualIngestionExecutor(
            ocr=self.ocr,
            layout=self.layout,
            captioning=self.captioning,
            visual_embedder=self.visual_embedder,
            cost=self.cost,
            crops=self.crops,
        )
        self.ingestion_executor = IngestionExecutor(
            self.ingestion,
            visual_executor=self.visual_ingestion_executor,
            async_document_analyzer=self.async_document_analyzer,
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
            output_guardrail=self.guardrail,
            structured_tool=self.structured_tool,
            visual_verifiers=visual_verifiers_from_settings(self.settings),
            settings=self.settings,
            # ★G5 model-routing seam: register the default provider under its model name so
            # QueryProfile.llm_model routing is exercisable via the tenant-tunable query-profiles
            # API today, and additional (e.g. small/cheap) providers can be registered here later
            # without touching AnswerService.
            llm_by_model=(
                {getattr(self.llm, "model", ""): self.llm}
                if getattr(self.llm, "model", "")
                else None
            ),
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
        filename: str = "",
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
            existing_doc = self.registry.get(tenant_id, document_id)
            if existing_doc is not None and not existing_doc.tombstone:
                if manufacturing_metadata is not None:
                    self.attach_manufacturing_metadata(
                        tenant_id, document_id, manufacturing_metadata
                    )
                return run
            # A previously deleted document may be re-seeded with identical bytes. The ingestion-run
            # idempotency key is still present, but retrieval must not leave the registry/chunks
            # tombstoned. Reuse the existing run row and project a fresh processing lifecycle.
            self.ingestion_runs.mark_queued(run)
        if _is_pdf_content_type(content_type):
            # Multi-page PDFs are async: the API creates the run and the worker owns submit/poll/persist.
            if run.status not in {JobStatus.QUEUED.value, JobStatus.RUNNING.value}:
                self.ingestion_runs.mark_queued(run)
            self._upsert_pending_document_stub(
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_id=source_id,
                document_id=document_id,
                checksum=checksum,
                document_ref=document_ref,
                content_type=content_type,
                manufacturing_metadata=manufacturing_metadata,
                filename=filename,
            )
            return run

        self.ingestion_runs.mark_running(run)
        if _is_image_content_type(content_type):
            try:
                result = self.ingestion_executor.execute_document(
                    tenant_id=tenant_id,
                    collection_id=collection_id,
                    source_id=source_id,
                    document_id=document_id,
                    document_ref=document_ref,
                    raw=raw,
                    content_type=content_type,
                )
            except Exception as exc:
                self.ingestion_runs.mark_failed(run, reason=str(exc), retry_count=0)
                refreshed = self.ingestion_runs.get_for_tenant(tenant_id, run.ingestion_run_id)
                return refreshed or run
            if result.status == JobStatus.SUCCEEDED.value:
                self.ingestion_runs.mark_succeeded(
                    run,
                    chunk_count=result.chunk_count,
                    content_checksum=result.content_checksum,
                    parser_version=result.parser_version,
                    chunking_config_version=result.chunking_config_version,
                    embedding_model_version=result.embedding_model_version,
                )
                doc = self.registry.get(tenant_id, document_id)
                if doc is not None:
                    doc.metadata["document_ref"] = document_ref
                    doc.metadata["content_type"] = content_type
                    if filename:
                        doc.metadata["filename"] = filename
                    self.registry.put(doc)
                if manufacturing_metadata is not None:
                    self.attach_manufacturing_metadata(
                        tenant_id, document_id, manufacturing_metadata
                    )
            else:
                self.ingestion_runs.mark_failed(
                    run, reason=result.failure_reason or "visual ingestion failed", retry_count=0
                )
            refreshed = self.ingestion_runs.get_for_tenant(tenant_id, run.ingestion_run_id)
            return refreshed or run

        job = self.ingestion.ingest(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            raw=raw,
            content_type=content_type,
            chunking_metadata=(
                manufacturing_metadata.to_mapping() if manufacturing_metadata is not None else None
            ),
        )
        if job.status == JobStatus.SUCCEEDED.value:
            self.ingestion_runs.mark_succeeded(run, chunk_count=job.chunk_count)
            doc = self.registry.get(tenant_id, document_id)
            if doc is not None:
                doc.metadata["document_ref"] = document_ref
                doc.metadata["content_type"] = content_type
                if filename:
                    doc.metadata["filename"] = filename
                self.registry.put(doc)
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

    def _upsert_pending_document_stub(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        checksum: str,
        document_ref: str,
        content_type: str,
        manufacturing_metadata: "ManufacturingDocumentMetadata | None",
        filename: str = "",
    ) -> None:
        existing = self.registry.get(tenant_id, document_id)
        metadata = dict(existing.metadata) if existing else {}
        metadata["document_ref"] = document_ref
        metadata["content_type"] = content_type
        if filename:
            metadata["filename"] = filename
        if manufacturing_metadata is not None:
            from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY

            metadata[MFG_META_KEY] = manufacturing_metadata.to_mapping()
        now = datetime.now(timezone.utc).isoformat()
        self.registry.put(
            Document(
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                source_id=source_id,
                version=existing.version if existing else 1,
                checksum=checksum,
                metadata=metadata,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                indexed_at=existing.indexed_at if existing else "",
                tombstone=False,
            )
        )

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
            chunking_metadata=metadata.to_mapping(),
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


def _is_image_content_type(content_type: str) -> bool:
    return content_type.lower().split(";", 1)[0].strip().startswith("image/")


def _is_pdf_content_type(content_type: str) -> bool:
    return content_type.lower().split(";", 1)[0].strip() == "application/pdf"


def _wrap_provider_policy(provider: object | None, router_cls: object | None, resolver: object):
    if provider is None or router_cls is None:
        return provider
    provider_id = str(getattr(provider, "provider_id", "") or "")
    if not provider_id:
        return provider
    return router_cls(provider, provider_id=provider_id, policy_resolver=resolver)


def build_manufacturing_system_for_base(base: ProductionSystem) -> "ManufacturingSystem":
    """Compose the manufacturing product surface over an existing production base system.

    The base 001 RAG store, manufacturing audit hash-chain writer, and DataUsePolicy store all share
    the same tenant-scoped Postgres connection. This is the production counterpart to the default
    in-memory ``ManufacturingSystem()`` composition.
    """
    from raku_rag.manufacturing.app import ManufacturingSystem
    from raku_rag.persistence.manufacturing_audit import PostgresManufacturingAuditLogWriter
    from raku_rag.persistence.manufacturing_governance import PostgresDataUsePolicyStore

    # NOTE (issue 0012): PostgresDraftStore is implemented and unit/Tier-B tested, but is NOT wired
    # here yet. Activating it requires first correcting the manufacturing_draft_artifacts CHECK
    # constraint `NOT (created_by='ai' AND status='approved')`, which currently rejects the legitimate
    # human-approved AI draft (created_by stays 'ai' as provenance; approval is attributed by
    # reviewer_id). That constraint governs the draft-approval safety boundary (always human per
    # CLAUDE.md), so the corrective migration is a separate, human-approved change. Until then the draft
    # queue uses the in-memory store (draft_store defaults to None -> InMemoryDraftStore).
    return ManufacturingSystem(
        settings=base.settings,
        base_system=base,
        audit=PostgresManufacturingAuditLogWriter(base._conn),
        policy_store=PostgresDataUsePolicyStore(base._conn),
    )


def build_production_manufacturing_system(
    dsn: str = DEFAULT_DSN, settings: Settings | None = None, *, reset: bool = False
) -> "ManufacturingSystem":
    """Create a Postgres ``ProductionSystem`` and wire the manufacturing product surface over it."""
    return build_manufacturing_system_for_base(
        ProductionSystem(dsn, settings=settings, reset=reset)
    )
