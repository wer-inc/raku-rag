"""T046 — reindex plans and parallel-build/switch execution.

The service keeps old chunks searchable until the replacement version is fully parsed, chunked, and
embedded. Switch is explicit: tombstone every existing chunk for the document, then publish the new
versioned chunk ids as live. Old chunks remain present but tombstoned, so search/answer cannot see them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping

from raku_rag.domain.models import Chunk, Document, Modality
from raku_rag.interfaces.base import Chunker, EmbeddingProvider, Parser, Vector, VectorStore
from raku_rag.services.ingestion import DocumentRegistry
from raku_rag.services.ingestion_quality import classify_text_extraction_quality
from raku_rag.services.structured_tables import (
    STRUCTURED_TABLE_COUNT_KEY,
    STRUCTURED_TABLE_MANIFEST_VERSION,
    STRUCTURED_TABLE_MANIFEST_VERSION_KEY,
    STRUCTURED_TABLE_MANIFESTS_KEY,
    cell_metadata_for_text,
    extract_structured_table_manifests,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: object) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


@dataclass
class ReindexPlan:
    reindex_plan_id: str
    tenant_id: str
    collection_id: str
    source_id: str = ""
    reason: str = "manual"
    target_parser_version: str = ""
    target_chunking_config_version: str = ""
    target_embedding_model_version: str = ""
    scope: dict = field(default_factory=dict)
    affected_document_count: int = 0
    status: str = "planned"
    dagster_backfill_id: str = ""
    created_by: str = ""
    created_at: str = field(default_factory=_now)
    started_at: str = ""
    finished_at: str = ""
    last_error: str = ""


class InMemoryReindexPlanStore:
    def __init__(self) -> None:
        self._plans: dict[str, ReindexPlan] = {}

    def create(self, plan: ReindexPlan) -> ReindexPlan:
        self._plans[plan.reindex_plan_id] = plan
        return plan

    def get(self, tenant_id: str, reindex_plan_id: str) -> ReindexPlan | None:
        plan = self._plans.get(reindex_plan_id)
        if plan is None or plan.tenant_id != tenant_id:
            return None
        return plan

    def list(self, tenant_id: str, *, collection_id: str = "") -> list[ReindexPlan]:
        plans = [p for p in self._plans.values() if p.tenant_id == tenant_id]
        if collection_id:
            plans = [p for p in plans if p.collection_id == collection_id]
        return sorted(plans, key=lambda p: p.created_at, reverse=True)

    def mark_running(self, plan: ReindexPlan) -> None:
        plan.status = "running"
        plan.started_at = _now()
        plan.last_error = ""

    def mark_succeeded(self, plan: ReindexPlan) -> None:
        plan.status = "succeeded"
        plan.finished_at = _now()

    def mark_failed(self, plan: ReindexPlan, reason: str) -> None:
        plan.status = "failed"
        plan.last_error = reason
        plan.finished_at = _now()


class ReindexService:
    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingProvider,
        parser: Parser,
        chunker: Chunker,
        registry: DocumentRegistry,
        plans: InMemoryReindexPlanStore,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._parser = parser
        self._chunker = chunker
        self._registry = registry
        self._plans = plans

    def create_plan(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        document_ids: list[str],
        source_id: str = "",
        reason: str = "manual",
        created_by: str = "",
        target_parser_version: str = "",
        target_chunking_config_version: str = "",
        target_embedding_model_version: str = "",
    ) -> ReindexPlan:
        plan = ReindexPlan(
            reindex_plan_id=_stable_id(
                "reindex", tenant_id, collection_id, document_ids, reason, _now()
            ),
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            reason=reason,
            target_parser_version=target_parser_version,
            target_chunking_config_version=target_chunking_config_version,
            target_embedding_model_version=target_embedding_model_version
            or self._embedder.model_version,
            scope={"document_ids": list(document_ids)},
            affected_document_count=len(document_ids),
            created_by=created_by,
        )
        return self._plans.create(plan)

    def reindex_documents(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        documents: Mapping[str, bytes],
        source_id: str = "",
        content_type: str = "text/plain",
        reason: str = "manual",
        created_by: str = "",
    ) -> ReindexPlan:
        plan = self.create_plan(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_ids=list(documents.keys()),
            reason=reason,
            created_by=created_by,
        )
        self.execute_plan(plan, documents=documents, content_type=content_type)
        return plan

    def execute_plan(
        self,
        plan: ReindexPlan,
        *,
        documents: Mapping[str, bytes],
        content_type: str = "text/plain",
    ) -> ReindexPlan:
        self._plans.mark_running(plan)
        staged: list[tuple[Document, list[tuple[Chunk, Vector]]]] = []
        try:
            if not self._parser.supports(content_type):
                raise ValueError(f"unsupported content_type: {content_type}")
            for document_id in plan.scope.get("document_ids", []):
                raw = documents[document_id]
                doc = self._next_document(plan, document_id, raw)
                staged.append((doc, self._build_chunks(plan, doc, raw, content_type)))

            for _doc, chunks in staged:
                tombstoned_chunks = []
                for chunk, vector in chunks:
                    chunk.tombstone = True
                    tombstoned_chunks.append((chunk, vector))
                self._store.upsert(tombstoned_chunks)

            for doc, chunks in staged:
                self._store.set_tombstone(plan.tenant_id, doc.document_id, True)
                live_chunks = []
                for chunk, vector in chunks:
                    chunk.tombstone = False
                    live_chunks.append((chunk, vector))
                self._store.upsert(live_chunks)
                self._registry.put(doc)

            self._plans.mark_succeeded(plan)
        except Exception as exc:
            self._plans.mark_failed(plan, str(exc))
        return plan

    def _next_document(self, plan: ReindexPlan, document_id: str, raw: bytes) -> Document:
        existing = self._registry.get(plan.tenant_id, document_id)
        next_version = (existing.version + 1) if existing else 1
        return Document(
            tenant_id=plan.tenant_id,
            collection_id=plan.collection_id,
            document_id=document_id,
            source_id=plan.source_id or (existing.source_id if existing else ""),
            version=next_version,
            checksum=hashlib.sha256(raw).hexdigest(),
            metadata=dict(existing.metadata) if existing else {},
            created_at=existing.created_at if existing else _now(),
            updated_at=_now(),
            indexed_at=_now(),
            tombstone=False,
        )

    def _build_chunks(
        self,
        plan: ReindexPlan,
        doc: Document,
        raw: bytes,
        content_type: str,
    ) -> list[tuple[Chunk, Vector]]:
        text = self._parser.parse(raw, content_type)
        table_manifests = extract_structured_table_manifests(raw, content_type)
        # ADR-018 A12 §Phase E: reindex RE-EVALUATES extraction quality instead of stamping
        # accepted unconditionally, so low-quality legacy content (mojibake/CID/empty) is quarantined
        # out of retrieval on reprocessing rather than being re-blessed.
        quality_metadata = classify_text_extraction_quality(
            text, raw_size=len(raw), content_type=content_type
        )
        doc.metadata.update(
            {
                **quality_metadata,
                STRUCTURED_TABLE_MANIFEST_VERSION_KEY: STRUCTURED_TABLE_MANIFEST_VERSION,
                STRUCTURED_TABLE_MANIFESTS_KEY: table_manifests,
                STRUCTURED_TABLE_COUNT_KEY: len(table_manifests),
            }
        )
        pieces = self._chunker.chunk(text)
        chunks: list[Chunk] = []
        for text_piece, heading, position, span in pieces:
            chunks.append(
                Chunk(
                    tenant_id=plan.tenant_id,
                    chunk_id=f"{doc.document_id}:v{doc.version}:{position}",
                    document_id=doc.document_id,
                    collection_id=plan.collection_id,
                    text=text_piece,
                    position=position,
                    token_count=len(text_piece.split()),
                    heading_path=heading,
                    modality=Modality.TEXT,
                    embedding_model_version=plan.target_embedding_model_version
                    or self._embedder.model_version,
                    offset_mapping=(span, span[0]),
                    metadata={
                        **quality_metadata,
                        **cell_metadata_for_text(text_piece, table_manifests),
                    },
                )
            )
        vectors = self._embedder.embed([c.text for c in chunks]) if chunks else []
        return list(zip(chunks, vectors))
