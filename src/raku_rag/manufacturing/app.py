"""Manufacturing composition root: the stage-2 analog of ``raku_rag.app.MvpSystem``.

``ManufacturingSystem`` WRAPS the 001 ``MvpSystem`` (RetrievalService / GroundednessGate /
AnswerService / AclPolicy / tenancy are reused, NOT reimplemented) and layers the manufacturing
``RuleHighRiskClassifier`` + ``ManufacturingSafetyGate`` + audit on top. It is the single in-memory
place that assembles the US1 manufacturing answer path; the production entrypoint would assemble the
same overlay behind the NestJS/pgvector adapters.

Contract (asserted by tests/manufacturing/helpers.py):
  - ``grant(...)`` delegates to the 001 AclPolicy.
  - ``ingest_manufacturing(*, tenant_id, collection_id, document_id, text, metadata, source_id="src")``
    ingests the body via the 001 ingestion path AND attaches ``ManufacturingDocumentMetadata`` so the
    classifier + gate can read it later.
  - ``answer(principal, query, collection_id=None, intent_hint=None) -> ManufacturingAnswer`` runs the
    001 answer path under the safety overlay.
  - ``search(...)`` returns 001 results decorated with approval tags.

stdlib only.
"""
from __future__ import annotations

import os
from datetime import date

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings
from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.api import record_answer_decision
from raku_rag.manufacturing.api.answer_ext import ManufacturingAnswer, ManufacturingAnswerService
from raku_rag.manufacturing.api.drafts import DraftService
from raku_rag.manufacturing.api.search_ext import ManufacturingSearchService
from raku_rag.manufacturing.domain.audit import InMemoryAuditLogWriter
from raku_rag.manufacturing.domain.draft import DraftArtifact, DraftType
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.manufacturing.ingestion.approval import ApprovalWorkflow
from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY, MetadataEnricher
from raku_rag.manufacturing.interfaces import ApprovalState
from raku_rag.manufacturing.safety.classifier import RuleHighRiskClassifier
from raku_rag.manufacturing.safety.gate import ManufacturingSafetyGate
from raku_rag.providers.parsers import (
    CompositeParser,
    DocxParser,
    SpreadsheetParser,
    TextParser,
    DOCX_CONTENT_TYPE,
    XLSX_CONTENT_TYPE,
)
from raku_rag.services.ingestion import IngestionService

# Key for the ManufacturingDocumentMetadata stashed in the 001 Document.metadata JSON.
_MFG_META_KEY = MFG_META_KEY

# Map file extension -> content type for the manufacturing file-ingestion entrypoint (FR-MFG-001).
_EXT_CONTENT_TYPE: dict[str, str] = {
    ".docx": DOCX_CONTENT_TYPE,
    ".xlsx": XLSX_CONTENT_TYPE,
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
}


class ManufacturingSystem:
    def __init__(self, settings: Settings | None = None, *, today: date | None = None) -> None:
        self._mvp = MvpSystem(settings)
        # tenant-scoped manufacturing metadata store (mirrors DocumentRegistry; in-memory).
        self._mfg_meta: dict[tuple[str, str], ManufacturingDocumentMetadata] = {}
        self.audit = InMemoryAuditLogWriter()

        # Manufacturing ingestion path: REUSE the 001 IngestionService (parse->chunk->embed->index)
        # but wire a CompositeParser so DOCX / XLSX / CSV (and the 001 text types) are all accepted
        # behind the single 001 Parser abstraction (FR-MFG-001/002). 001's TextParser alone rejects
        # these OOXML types, so the manufacturing path uses this composite instead.
        self._parser = CompositeParser([TextParser(), DocxParser(), SpreadsheetParser()])
        self._ingestion = IngestionService(
            self._mvp.store,
            self._mvp.embedder,
            self._parser,
            self._mvp.chunker,
            self._mvp.registry,
        )
        self._enricher = MetadataEnricher(
            store=self._mvp.store, get_document=self._mvp.registry.get
        )
        self._approval = ApprovalWorkflow(
            get_meta=self.get_mfg_meta,
            set_meta=self._set_mfg_meta,
            audit=self.audit,
            enricher=self._enricher,
        )

        classifier = RuleHighRiskClassifier(llm=self._mvp.llm)
        safety_gate = ManufacturingSafetyGate(today=today)
        self._answer = ManufacturingAnswerService(
            retrieval=self._mvp.retrieval,
            groundedness=self._mvp.gate,
            answer_service=self._mvp.answer_service,
            get_mfg_meta=self.get_mfg_meta,
            classifier=classifier,
            safety_gate=safety_gate,
            get_document=self._mvp.registry.get,
            today=today,
        )
        self._search = ManufacturingSearchService(
            retrieval=self._mvp.retrieval, get_mfg_meta=self.get_mfg_meta
        )
        # US4 — DraftArtifact generation + lightweight review workflow (FR-MFG-010/010a/010b).
        # Reuses the shared AuditLogWriter + US1 SafetyGate semantics; AI output is always draft.
        self._drafts = DraftService(
            audit=self.audit, get_mfg_meta=self.get_mfg_meta, today=today
        )

    # --- admin / ACL (delegates to 001) -----------------------------------------------------------
    def grant(
        self,
        tenant_id: str,
        scope_type: ScopeType,
        scope_id: str,
        subject_type: SubjectType,
        subject_id: str,
    ) -> None:
        self._mvp.grant(tenant_id, scope_type, scope_id, subject_type, subject_id)

    # --- metadata resolver ------------------------------------------------------------------------
    def get_mfg_meta(self, tenant_id: str, document_id: str) -> ManufacturingDocumentMetadata | None:
        return self._mfg_meta.get((tenant_id, document_id))

    def _set_mfg_meta(
        self, tenant_id: str, document_id: str, metadata: ManufacturingDocumentMetadata
    ) -> None:
        """Update the fast resolver map (read by search/answer/classifier/gate)."""
        self._mfg_meta[(tenant_id, document_id)] = metadata

    # --- ingestion (001 body path + manufacturing metadata attach) --------------------------------
    def ingest_manufacturing(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        document_id: str,
        text: str,
        metadata: ManufacturingDocumentMetadata,
        source_id: str = "src",
    ):
        job = self._mvp.ingest_text(
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            text=text,
            source_id=source_id,
        )
        # Stash on the 001 Document.metadata (JSON-carryable) AND in the fast resolver map.
        doc = self._mvp.registry.get(tenant_id, document_id)
        if doc is not None:
            doc.metadata[_MFG_META_KEY] = metadata
        self._set_mfg_meta(tenant_id, document_id, metadata)
        # Propagate to indexed chunks (FR-MFG-003) so the metadata travels with the evidence.
        self._enricher.propagate_to_chunks(tenant_id, document_id, metadata)
        return job

    # --- file ingestion (T029/T030; FR-MFG-001/002/003) -------------------------------------------
    def ingest_manufacturing_file(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        document_id: str,
        path: str,
        content_type: str | None = None,
        metadata: ManufacturingDocumentMetadata,
        source_id: str = "src",
    ):
        """Ingest a DOCX/XLSX/CSV (or 001 text) file via the REUSED 001 ingestion path.

        Reads the file bytes from ``path``, routes by extension / ``content_type`` to the right 001
        ``Parser`` (DocxParser / SpreadsheetParser / TextParser, dispatched by the CompositeParser),
        runs parse->chunk->embed->index, then enriches the Document/Chunk metadata. Returns the 001
        ``IngestionJob`` (``status == 'succeeded'``, ``chunk_count > 0``). Parse/ingest is audited
        (FR-MFG-021). Does NOT define a new search mechanism — the file is found via the 001 path.
        """
        with open(path, "rb") as fh:
            raw = fh.read()
        ct = content_type or self._content_type_for(path)

        job = self._ingestion.ingest(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            raw=raw,
            content_type=ct,
        )
        # Attach manufacturing metadata to Document.metadata + propagate to chunks (FR-MFG-003).
        self._set_mfg_meta(tenant_id, document_id, metadata)
        self._enricher.attach(tenant_id, document_id, metadata)
        # Audit the ingest/parse (reference IDs only; no body text) — FR-MFG-021.
        self._audit_ingest(
            tenant_id=tenant_id, document_id=document_id, content_type=ct, job=job
        )
        return job

    @staticmethod
    def _content_type_for(path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        if ext not in _EXT_CONTENT_TYPE:
            raise ValueError(f"unsupported file extension: {ext!r}")
        return _EXT_CONTENT_TYPE[ext]

    def _audit_ingest(
        self, *, tenant_id: str, document_id: str, content_type: str, job
    ) -> None:
        from datetime import datetime, timezone

        from raku_rag.manufacturing.domain.audit import AuditLogEntry

        ts = datetime.now(timezone.utc).isoformat()
        self.audit.record(
            AuditLogEntry(
                tenant_id=tenant_id,
                log_id=f"ingest.file:{document_id}:{ts}",
                timestamp=ts,
                action="ingest.file",
                resource_type="document",
                resource_id=document_id,  # reference ID only
                decision=job.status,
                reason=content_type,
                document_ids_used=(document_id,),
            )
        )

    # --- metadata update / approval lifecycle (T030; FR-MFG-003/004/004a) -------------------------
    def update_metadata(
        self,
        *,
        tenant_id: str,
        document_id: str,
        metadata: ManufacturingDocumentMetadata,
    ) -> ManufacturingDocumentMetadata:
        """Re-attach manufacturing metadata to an already-ingested document (FR-MFG-003)."""
        self._set_mfg_meta(tenant_id, document_id, metadata)
        return self._enricher.attach(tenant_id, document_id, metadata)

    def transition_approval(
        self,
        *,
        tenant_id: str,
        document_id: str,
        to_status: str,
        actor: IdentityClaims,
    ) -> ApprovalState:
        """Drive the lightweight workflow (approval_source = workflow). Audited (FR-MFG-004/021)."""
        return self._approval.transition(tenant_id, document_id, to_status, actor)

    def import_external_approval(
        self,
        *,
        tenant_id: str,
        document_id: str,
        external: dict,
        actor: IdentityClaims | None = None,
    ) -> ApprovalState:
        """Import an upstream approval as source of truth, overriding the workflow (FR-MFG-004a)."""
        return self._approval.import_external(tenant_id, document_id, external, actor)

    # --- answer (001 path under the safety overlay) -----------------------------------------------
    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None = None,
        intent_hint: str | None = None,
        manufacturing_filters: dict | None = None,
    ) -> ManufacturingAnswer:
        profile = self._mvp.profiles.resolve(collection_id)
        ans, classification, decision, candidate_doc_ids = self._answer.answer(
            principal,
            query,
            profile,
            intent_hint=intent_hint,
            manufacturing_filters=manufacturing_filters,
        )
        # T020 — audit the high-risk + safety decision (reference IDs only; redacted).
        record_answer_decision(
            self.audit,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            correlation_id=ans.correlation_id,
            status=ans.status,
            classification=classification,
            decision=decision,
            safety_block_reason=ans.safety_block_reason,
            candidate_document_ids=candidate_doc_ids,
        )
        return ans

    # --- search (001 retrieval + approval tags) ---------------------------------------------------
    def search(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None = None,
        manufacturing_filters: dict | None = None,
    ):
        profile = self._mvp.profiles.resolve(collection_id)
        return self._search.search(
            principal, query, profile, manufacturing_filters=manufacturing_filters
        )

    # --- drafts (US4: generate / assign / review / get; contracts §D) ------------------------------
    def generate_draft(
        self,
        *,
        principal: IdentityClaims,
        kind: DraftType | str,
        context_citations=(),
        source_document_ids=(),
        template_id: str | None = None,
        collection_id: str | None = None,
        manufacturing_filters: dict | None = None,
    ) -> DraftArtifact:
        """POST /v1/manufacturing/drafts — ALWAYS status=draft, created_by=ai (Hard Rule 1).

        AI never auto-approves; safety items follow FR-MFG-005 (no assertion without approved+effective
        evidence). Generation is audited (FR-MFG-010b/021).
        """
        return self._drafts.create(
            principal=principal,
            kind=kind,
            context_citations=context_citations,
            source_document_ids=source_document_ids,
            template_id=template_id,
            collection_id=collection_id,
            manufacturing_filters=manufacturing_filters,
        )

    def get_draft(self, tenant_id: str, artifact_id: str) -> DraftArtifact | None:
        """GET /v1/manufacturing/drafts/{artifact_id} — a detached copy of the stored record."""
        return self._drafts.get(tenant_id, artifact_id)

    def assign_reviewer(
        self,
        *,
        tenant_id: str,
        artifact_id: str,
        reviewer_id: str | None = None,
        reviewer_group: str | None = None,
        reviewer_role: str | None = None,
    ) -> DraftArtifact:
        """POST .../assign — draft -> in_review with reviewer attribution + assigned_at (audited)."""
        return self._drafts.assign(
            tenant_id=tenant_id,
            artifact_id=artifact_id,
            reviewer_id=reviewer_id,
            reviewer_group=reviewer_group,
            reviewer_role=reviewer_role,
        )

    def review_draft(
        self,
        *,
        tenant_id: str,
        artifact_id: str,
        reviewer: IdentityClaims | None,
        decision: str,
        comment: str | None = None,
    ) -> DraftArtifact:
        """POST .../review — reviewer decision. approve REQUIRES a reviewer (SC-MFG-007; audited)."""
        return self._drafts.review(
            tenant_id=tenant_id,
            artifact_id=artifact_id,
            reviewer=reviewer,
            decision=decision,
            comment=comment,
        )
