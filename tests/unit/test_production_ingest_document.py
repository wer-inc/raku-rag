from __future__ import annotations

import hashlib
from unittest import TestCase

from raku_rag.domain.models import Document, JobStatus
from raku_rag.production import ProductionSystem
from raku_rag.services.ingestion import IngestionJob
from raku_rag.workers.ingestion import IngestionRun


def _doc(*, tombstone: bool) -> Document:
    return Document(
        tenant_id="demo",
        collection_id="manuals",
        document_id="doc-1",
        source_id="standard",
        version=1,
        checksum="checksum",
        metadata={},
        tombstone=tombstone,
    )


def _run() -> IngestionRun:
    return IngestionRun(
        ingestion_run_id="ing-existing",
        idempotency_key="existing-key",
        tenant_id="demo",
        collection_id="manuals",
        source_id="standard",
        document_id="doc-1",
        document_ref="data:text/plain;base64,old",
        content_type="text/plain",
        trigger="api",
        status=JobStatus.SUCCEEDED.value,
        chunk_count=1,
    )


class _FakeRegistry:
    def __init__(self, doc: Document | None) -> None:
        self.doc = doc

    def get(self, tenant_id: str, document_id: str) -> Document | None:
        if self.doc and self.doc.tenant_id == tenant_id and self.doc.document_id == document_id:
            return self.doc
        return None

    def put(self, doc: Document) -> None:
        self.doc = doc


class _FakeRuns:
    def __init__(self) -> None:
        self.run = _run()
        self.events: list[str] = []

    def create_queued(self, _message, *, trigger: str):
        self.events.append(f"create:{trigger}")
        return self.run, False

    def mark_queued(self, run: IngestionRun) -> None:
        self.events.append("queued")
        run.status = JobStatus.QUEUED.value
        run.finished_at = ""

    def mark_running(self, run: IngestionRun) -> None:
        self.events.append("running")
        run.status = JobStatus.RUNNING.value

    def mark_succeeded(self, run: IngestionRun, *, chunk_count: int) -> None:
        self.events.append("succeeded")
        run.status = JobStatus.SUCCEEDED.value
        run.chunk_count = chunk_count

    def mark_failed(self, run: IngestionRun, *, reason: str, retry_count: int) -> None:
        self.events.append(f"failed:{reason}:{retry_count}")
        run.status = JobStatus.FAILED.value

    def get_for_tenant(self, tenant_id: str, ingestion_run_id: str) -> IngestionRun | None:
        if self.run.tenant_id == tenant_id and self.run.ingestion_run_id == ingestion_run_id:
            return self.run
        return None


class _FakeIngestion:
    def __init__(self, registry: _FakeRegistry) -> None:
        self.registry = registry
        self.calls = 0

    def ingest(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_id: str,
        document_id: str,
        raw: bytes,
        content_type: str,
        chunking_metadata,
    ) -> IngestionJob:
        self.calls += 1
        self.registry.put(
            Document(
                tenant_id=tenant_id,
                collection_id=collection_id,
                source_id=source_id,
                document_id=document_id,
                version=2,
                checksum=hashlib.sha256(raw).hexdigest(),
                metadata={},
                tombstone=False,
            )
        )
        return IngestionJob(
            job_id="job-1",
            document_id=document_id,
            status=JobStatus.SUCCEEDED.value,
            chunk_count=1,
        )


def _fake_production(doc: Document | None):
    system = ProductionSystem.__new__(ProductionSystem)
    registry = _FakeRegistry(doc)
    runs = _FakeRuns()
    ingestion = _FakeIngestion(registry)
    system.registry = registry
    system.ingestion_runs = runs
    system.ingestion = ingestion
    return system, registry, runs, ingestion


class TestProductionIngestDocument(TestCase):
    def test_duplicate_live_document_keeps_idempotent_skip(self) -> None:
        system, _registry, runs, ingestion = _fake_production(_doc(tombstone=False))

        result = system.ingest_document(
            tenant_id="demo",
            collection_id="manuals",
            source_id="standard",
            document_id="doc-1",
            document_ref="data:text/plain;base64,new",
            raw=b"same content",
            content_type="text/plain",
        )

        self.assertIs(result, runs.run)
        self.assertEqual(ingestion.calls, 0)
        self.assertEqual(runs.events, ["create:api"])

    def test_duplicate_deleted_document_reindexes_and_restores_document(self) -> None:
        system, registry, runs, ingestion = _fake_production(_doc(tombstone=True))

        result = system.ingest_document(
            tenant_id="demo",
            collection_id="manuals",
            source_id="standard",
            document_id="doc-1",
            document_ref="data:text/plain;base64,new",
            raw=b"same content",
            content_type="text/plain",
        )

        self.assertIs(result, runs.run)
        self.assertEqual(ingestion.calls, 1)
        self.assertEqual(runs.events, ["create:api", "queued", "running", "succeeded"])
        self.assertIsNotNone(registry.doc)
        self.assertFalse(registry.doc.tombstone)
        self.assertEqual(registry.doc.metadata["document_ref"], "data:text/plain;base64,new")
