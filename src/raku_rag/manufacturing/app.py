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

from datetime import date

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings
from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.api import record_answer_decision
from raku_rag.manufacturing.api.answer_ext import ManufacturingAnswer, ManufacturingAnswerService
from raku_rag.manufacturing.api.search_ext import ManufacturingSearchService
from raku_rag.manufacturing.domain.audit import InMemoryAuditLogWriter
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.manufacturing.safety.classifier import RuleHighRiskClassifier
from raku_rag.manufacturing.safety.gate import ManufacturingSafetyGate

# Key for the ManufacturingDocumentMetadata stashed in the 001 Document.metadata JSON.
_MFG_META_KEY = "_mfg_meta"


class ManufacturingSystem:
    def __init__(self, settings: Settings | None = None, *, today: date | None = None) -> None:
        self._mvp = MvpSystem(settings)
        # tenant-scoped manufacturing metadata store (mirrors DocumentRegistry; in-memory).
        self._mfg_meta: dict[tuple[str, str], ManufacturingDocumentMetadata] = {}
        self.audit = InMemoryAuditLogWriter()

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
        self._mfg_meta[(tenant_id, document_id)] = metadata
        return job

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
