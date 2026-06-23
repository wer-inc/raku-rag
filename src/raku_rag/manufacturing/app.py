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
from datetime import date, datetime, timedelta, timezone

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings
from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.api import record_answer_decision, record_answer_feedback
from raku_rag.manufacturing.api.answer_ext import ManufacturingAnswer, ManufacturingAnswerService
from raku_rag.manufacturing.api.dashboard import DashboardService
from raku_rag.manufacturing.api.drafts import DraftService
from raku_rag.manufacturing.api.ingest_metadata import ManufacturingSyncStatusService
from raku_rag.manufacturing.api.policy import GovernanceService
from raku_rag.manufacturing.api.search_ext import ManufacturingSearchService
from raku_rag.manufacturing.api.trouble import TroubleCaseSearchService
from raku_rag.manufacturing.domain.acl_mapping import ManufacturingScope, apply_scope, record_denial
from raku_rag.manufacturing.domain.audit import AuditLogEntry, InMemoryAuditLogWriter
from raku_rag.manufacturing.domain.draft import DraftArtifact, DraftType
from raku_rag.manufacturing.domain.entities import (
    Countermeasure,
    FailureMode,
    TroubleCase,
)
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.manufacturing.governance.no_train import (
    InMemoryDataUsePolicyStore,
    InMemoryNoTrainGuard,
)
from raku_rag.manufacturing.governance.retention import InMemoryRetentionManager
from raku_rag.manufacturing.ingestion.approval import ApprovalWorkflow
from raku_rag.manufacturing.ingestion.metadata_enrichment import MFG_META_KEY, MetadataEnricher
from raku_rag.manufacturing.interfaces import ApprovalState, AuditLogWriter, DataUsePolicyStore
from raku_rag.manufacturing.knowledge.trouble_cases import (
    InMemoryTroubleCaseStore,
    TroubleCaseRetriever,
    TroubleCaseSearchResponse,
)
from raku_rag.dagster.assets.manufacturing import InMemoryManufacturingKpiMaterializationStore
from raku_rag.manufacturing.safety.classifier import RuleHighRiskClassifier
from raku_rag.manufacturing.safety.gate import ManufacturingSafetyGate
from raku_rag.persistence.control_plane import InMemoryControlPlaneStateRepository
from raku_rag.providers.parsers import (
    CompositeParser,
    DocxParser,
    SpreadsheetParser,
    TextParser,
    DOCX_CONTENT_TYPE,
    XLSX_CONTENT_TYPE,
)
from raku_rag.services.ingestion import IngestionService


def datetime_now_iso() -> str:
    """Module-level UTC ISO timestamp helper (reference-only audit timestamps)."""
    return datetime.now(timezone.utc).isoformat()


# Key for the ManufacturingDocumentMetadata stashed in the 001 Document.metadata JSON.
_MFG_META_KEY = MFG_META_KEY

# Safe default provider-capability wiring used when the caller injects none. The single default
# provider 'mvp_local' is treated as no-train-guaranteed (the in-memory MVP processes data locally
# and never sends it to an external trainer), so the BUILT capabilities stay available out of the box
# while still routing every decision through the NoTrainGuard (no silent bypass). Base CR-001-B owns
# the real verified set in production; this is the minimal local default.
_DEFAULT_PROVIDER = "mvp_local"
_DEFAULT_PROVIDER_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "answer_llm": (_DEFAULT_PROVIDER,),
    "embedding": (_DEFAULT_PROVIDER,),
    "ocr": (_DEFAULT_PROVIDER,),
    "draft_llm": (_DEFAULT_PROVIDER,),
}
_DEFAULT_NO_TRAIN_PROVIDERS: tuple[str, ...] = (_DEFAULT_PROVIDER,)

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
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        today: date | None = None,
        provider_capabilities: dict | None = None,
        no_train_providers=None,
        base_system: MvpSystem | None = None,
        audit: AuditLogWriter | None = None,
        policy_store: DataUsePolicyStore | None = None,
    ) -> None:
        self._mvp = base_system or MvpSystem(settings)
        self.control_plane = InMemoryControlPlaneStateRepository()
        # tenant-scoped manufacturing metadata store (mirrors DocumentRegistry; in-memory).
        self._mfg_meta: dict[tuple[str, str], ManufacturingDocumentMetadata] = {}
        self.audit = audit or InMemoryAuditLogWriter()

        # --- Phase 9 governance overlay (no-train / retention / policy / export) ------------------
        # Reuse the Phase-2 DataUsePolicyStore (per-tenant GQ1/GQ2 defaults + opt-in invariant +
        # version bump). The NoTrainGuard enforces the policy against the INJECTED provider-capability
        # map (Base CR-001-B verified set is injected here; 002 enforces opt-in/GQ1 locally). When the
        # caller injects no map a safe local default applies (every BUILT capability stays available).
        self._policy_store = policy_store or InMemoryDataUsePolicyStore()
        caps = (
            _DEFAULT_PROVIDER_CAPABILITIES
            if provider_capabilities is None
            else provider_capabilities
        )
        nt_providers = (
            _DEFAULT_NO_TRAIN_PROVIDERS if no_train_providers is None else no_train_providers
        )
        self.no_train = InMemoryNoTrainGuard(
            self._policy_store,
            provider_capabilities=caps,
            no_train_providers=nt_providers,
        )
        self.retention = InMemoryRetentionManager(self._policy_store, deletion=self._mvp.deletion)
        self._governance = GovernanceService(policy_store=self._policy_store, audit=self.audit)

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
            audit=self.audit,
            get_mfg_meta=self.get_mfg_meta,
            can_use_source=self._can_use_draft_source,
            today=today,
        )
        # US3 — similar past TroubleCase retrieval (FR-MFG-008/009, Hard Rule 4). The knowledge graph
        # is registered in an in-memory store; the retriever runs the symptom query through the SAME
        # reused 001 RetrievalService (deny-by-default ACL PRE-filter) — no parallel authz path — and
        # resolves only ACL-visible source documents back to their TroubleCase graph. Past-case
        # countermeasures are normalized to candidate/past-example even when permanent.
        self._trouble_cases = InMemoryTroubleCaseStore()
        self._trouble_retriever = TroubleCaseRetriever(
            retrieval=self._mvp.retrieval,
            store=self._trouble_cases,
            get_mfg_meta=self.get_mfg_meta,
            get_document=self._mvp.registry.get,
        )
        self._trouble_search = TroubleCaseSearchService(
            retriever=self._trouble_retriever, audit=self.audit
        )
        # US5 — knowledge-ops dashboard / safety-telemetry / KPI (FR-MFG-012/028/030). Request-path
        # reads use the materialized KPI store when populated and otherwise compute from the shared
        # audit log; either path is local state only and never calls Dagster synchronously.
        self.kpi_materializations = InMemoryManufacturingKpiMaterializationStore()
        self._dashboard = DashboardService(
            audit=self.audit,
            get_mfg_meta=self.get_mfg_meta,
            all_mfg_meta=lambda: list(self._mfg_meta.items()),
            retention=self.retention,
            materialized_kpi_store=self.kpi_materializations,
        )
        self._sync_status = ManufacturingSyncStatusService(self.control_plane)

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

    def grant_scope(self, scope: ManufacturingScope) -> None:
        """US6 (T053, FR-MFG-013): provision a department/factory/role/equipment-area scope.

        Translates the manufacturing scope to 001 ``ACLGrant`` records via the T011 ``acl_mapping``
        helper and adds them to the SAME 001 :class:`AclPolicy` the reused 001 ``RetrievalService``
        consults (``self._mvp.acl``). This builds NO new authorization mechanism: the 001
        deny-by-default PRE-filter inside ``InMemoryVectorStore.search`` then enforces manufacturing
        scoping on every BUILT endpoint (answer / search / drafts = US1/US2/US4). US3 trouble-cases
        and US5 dashboard, when built, MUST grant through this SAME method (they are not stubbed).
        """
        apply_scope(self._mvp.acl, scope)

    # --- metadata resolver ------------------------------------------------------------------------
    def _can_use_draft_source(self, principal: IdentityClaims, document_id: str) -> bool:
        """SC-MFG-008 draft-source guard: a draft may use a document as a source ONLY if it is not
        tombstoned AND is ACL-readable by ``principal`` under the SAME 001 AclPolicy the retrieval
        pre-filter consults (data-model.md:86,146-147). A document_id that resolves to no 001
        Document references nothing real and therefore cannot leak — it is allowed. Reuses
        self._mvp.registry (tombstone state) + self._mvp.acl (deny-by-default) — no new mechanism.
        """
        doc = self._mvp.registry.get(principal.tenant_id, document_id)
        if doc is None:
            return True  # never-ingested id: nothing to leak
        if doc.tombstone:
            return False  # deleted-content reappearance guard (data-model.md:86)
        return self._mvp.acl.can_read_document(principal, doc)

    def get_mfg_meta(
        self, tenant_id: str, document_id: str
    ) -> ManufacturingDocumentMetadata | None:
        # A source-deleted (tombstoned) document must NOT resurface via the metadata resolver
        # (GAP-S2 / top risk: deleted-content reappearance). The draft path resolves a citation's
        # approval state from here WITHOUT going through the tombstone-excluding 001 retrieval, so a
        # stale APPROVED+effective entry could otherwise confirm a draft safety item for a document
        # that has been withdrawn/recalled. A later restore (re-ingest) un-tombstones the registry doc
        # and re-populates the resolver, so this also honors the restore path.
        doc = self._mvp.registry.get(tenant_id, document_id)
        if doc is not None and doc.tombstone:
            return None
        cached = self._mfg_meta.get((tenant_id, document_id))
        if cached is not None:
            return cached
        if doc is None:
            return None
        raw = doc.metadata.get(_MFG_META_KEY)
        if raw is None:
            return None
        meta = ManufacturingDocumentMetadata.from_mapping(raw)
        self._mfg_meta[(tenant_id, document_id)] = meta
        return meta

    def _set_mfg_meta(
        self, tenant_id: str, document_id: str, metadata: ManufacturingDocumentMetadata
    ) -> None:
        """Update the fast resolver map (read by search/answer/classifier/gate)."""
        self._mfg_meta[(tenant_id, document_id)] = metadata
        doc = self._mvp.registry.get(tenant_id, document_id)
        if doc is not None:
            doc.metadata[_MFG_META_KEY] = metadata.to_mapping()
            self._mvp.registry.put(doc)

    def list_documents(
        self, principal: IdentityClaims, *, collection_id: str | None = None
    ) -> list[dict]:
        """ACL-filtered manufacturing document inventory for the ドキュメント一覧 screen.

        Enumerates live (non-tombstoned, so a source-deleted doc never resurfaces — GAP-S2)
        documents from the 001 registry — the deployed source of truth, since ``/internal/ingest``
        persists the manufacturing metadata into ``Document.metadata`` over Postgres rather than the
        in-process ``_mfg_meta`` map. Every document is re-checked against the 001 deny-by-default
        ACL (``can_read_document``) so the inventory never leaks a document the caller cannot read —
        the same isolation the search/answer paths enforce (top risk: ACL leakage). Approval state is
        resolved per document via ``get_mfg_meta`` (honors the tombstone/restore path). Read-only.
        """
        tenant_id = principal.tenant_id
        registry = self._mvp.registry
        acl = self._mvp.acl
        lister = getattr(registry, "list_documents", None)
        pairs: list[tuple] = []
        if callable(lister):
            for doc in lister(tenant_id, collection_id=collection_id):
                if getattr(doc, "tombstone", False):
                    continue
                if not acl.can_read_document(principal, doc):
                    continue
                pairs.append((doc, self.get_mfg_meta(tenant_id, doc.document_id)))
        else:
            # In-memory MvpSystem path: the manufacturing ingest populates ``_mfg_meta`` directly.
            for (meta_tenant, document_id), meta in self._mfg_meta.items():
                if meta_tenant != tenant_id:
                    continue
                doc = registry.get(tenant_id, document_id)
                if doc is None or doc.tombstone:
                    continue
                if collection_id and doc.collection_id != collection_id:
                    continue
                if not acl.can_read_document(principal, doc):
                    continue
                pairs.append((doc, meta))

        out: list[dict] = []
        for doc, meta in pairs:
            kind = getattr(getattr(meta, "document_kind", None), "value", None)
            status = getattr(getattr(meta, "approval_status", None), "value", None)
            out.append(
                {
                    "document_id": doc.document_id,
                    "collection_id": doc.collection_id,
                    "source_id": doc.source_id,
                    "document_kind": (
                        kind if kind is not None else getattr(meta, "document_kind", None)
                    ),
                    "approval_status": status if status is not None else "unknown",
                    "effective_date": getattr(meta, "effective_date", None),
                    "approved_by": getattr(meta, "approved_by", None),
                    "approved_at": getattr(meta, "approved_at", None),
                    "superseded_by": getattr(meta, "superseded_by", None),
                    "equipment": getattr(meta, "equipment", None),
                    "safety_category": getattr(meta, "safety_category", None),
                }
            )
        out.sort(key=lambda d: (d["collection_id"] or "", d["document_id"]))
        return out

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
            chunking_metadata=metadata.to_mapping(),
        )
        # Stash on the 001 Document.metadata (JSON-carryable) AND in the fast resolver map.
        self._set_mfg_meta(tenant_id, document_id, metadata)
        # Propagate to indexed chunks (FR-MFG-003) so the metadata travels with the evidence.
        self._enricher.propagate_to_chunks(tenant_id, document_id, metadata)
        # Audit the ingest / metadata enrichment (reference IDs only; no body text) — FR-MFG-021.
        self._audit_ingest(
            tenant_id=tenant_id, document_id=document_id, content_type="text/plain", job=job
        )
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
            chunking_metadata=metadata.to_mapping(),
        )
        # Attach manufacturing metadata to Document.metadata + propagate to chunks (FR-MFG-003).
        self._enricher.attach(tenant_id, document_id, metadata)
        self._set_mfg_meta(tenant_id, document_id, metadata)
        # Audit the ingest/parse (reference IDs only; no body text) — FR-MFG-021.
        self._audit_ingest(tenant_id=tenant_id, document_id=document_id, content_type=ct, job=job)
        return job

    @staticmethod
    def _content_type_for(path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        if ext not in _EXT_CONTENT_TYPE:
            raise ValueError(f"unsupported file extension: {ext!r}")
        return _EXT_CONTENT_TYPE[ext]

    def _audit_ingest(self, *, tenant_id: str, document_id: str, content_type: str, job) -> None:
        from datetime import datetime, timezone

        from raku_rag.manufacturing.domain.audit import AuditLogEntry

        ts = datetime.now(timezone.utc).isoformat()
        self.audit.record(
            AuditLogEntry(
                tenant_id=tenant_id,
                log_id=f"ingest.metadata:{document_id}:{ts}",
                timestamp=ts,
                action="ingest.parse_metadata",
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
        """Re-attach manufacturing metadata to an already-ingested document (FR-MFG-003).

        The metadata UPDATE is itself an audited governance event (FR-MFG-021: ManufacturingDocument
        Metadata の作成・更新・削除) — reference IDs only, never the customer name / body.
        """
        result = self._enricher.attach(tenant_id, document_id, metadata)
        self._set_mfg_meta(tenant_id, document_id, metadata)
        ts = datetime_now_iso()
        self.audit.record(
            AuditLogEntry(
                tenant_id=tenant_id,
                log_id=f"metadata.update:{document_id}:{ts}",
                timestamp=ts,
                action="metadata.update",
                resource_type="document",
                resource_id=document_id,  # reference ID only
                decision="updated",
                approval_status_at_use=(
                    metadata.approval_status.value if metadata.approval_status else None
                ),
                document_ids_used=(document_id,),
            )
        )
        return result

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

    def supersede_document(
        self,
        *,
        tenant_id: str,
        document_id: str,
        superseded_by: str,
        actor: IdentityClaims,
    ) -> ApprovalState:
        """Obsolete ``document_id`` by supersession, recording superseded_by (FR-MFG-004/021).

        Drives the lightweight workflow approved->obsolete (forward, legal under the GAP-F6 guard)
        and stamps superseded_by + obsolete_at; approval_source = workflow. Audited. The superseding
        document is NOT auto-approved — it must go through its own review (Hard Rule 1).
        """
        return self._approval.supersede(tenant_id, document_id, superseded_by, actor)

    # --- manufacturing sync/status (T031b; wraps 001 control-plane state) -------------------------
    def request_source_sync(
        self,
        principal: IdentityClaims,
        source_id: str,
        *,
        collection_id: str = "manufacturing",
        document_id: str = "",
        document_ref: str = "",
        content_type: str = "text/plain",
        idempotency_key: str = "",
    ) -> dict:
        """POST /v1/manufacturing/sources/{source_id}/sync."""
        return self._sync_status.request_sync(
            principal,
            source_id,
            collection_id=collection_id,
            document_id=document_id,
            document_ref=document_ref,
            content_type=content_type,
            idempotency_key=idempotency_key,
        )

    def source_sync_status(self, principal: IdentityClaims, source_id: str) -> dict:
        """GET /v1/manufacturing/sources/{source_id}/sync-status."""
        return self._sync_status.sync_status(principal, source_id)

    def ingestion_run_status(self, principal: IdentityClaims, ingestion_run_id: str) -> dict:
        """GET /v1/manufacturing/ingestion-runs/{ingestion_run_id}."""
        return self._sync_status.ingestion_run(principal, ingestion_run_id)

    # --- answer (001 path under the safety overlay) -----------------------------------------------
    def answer(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None = None,
        intent_hint: str | None = None,
        manufacturing_filters: dict | None = None,
        factory_id: str | None = None,
    ) -> ManufacturingAnswer:
        profile = self._mvp.profiles.resolve(collection_id)
        # T061 — ACL-denial auditing: a query that matches within-tenant documents the principal has
        # NO grant to is silently dropped by the 001 deny-by-default PRE-filter; surface that denial
        # to the audit log (reference IDs only) so FR-MFG-021 coverage includes acl_denied.
        self._audit_acl_denials(principal, collection_id)

        ans, classification, decision, candidate_doc_ids = self._answer.answer(
            principal,
            query,
            profile,
            intent_hint=intent_hint,
            manufacturing_filters=manufacturing_filters,
        )
        # T020/T061 — audit the high-risk + safety decision + citation access (reference IDs only).
        citation_ids = tuple(
            c.chunk_id or c.document_id for c in ans.citations if (c.chunk_id or c.document_id)
        )
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
            citation_ids=citation_ids,
            # T056 — snapshot the actor org-context so US5 telemetry can group by factory/department
            # (department == the actor's 001 ACL group; factory == the supplied territory). Optional;
            # answer behaviour is unchanged when factory_id is omitted.
            principal=principal,
            factory_id=factory_id,
            collection_id=collection_id,  # FR-MFG-030 collection axis (None = cross-collection answer)
        )
        # T061 — citation-access auditing (FR-MFG-021): when the answer path retrieves and SURVEYS
        # candidate citations as evidence (asserted citations, else the surveyed candidate documents),
        # record which citations/documents were accessed by reference ID only. Non-vacuous: it fires
        # only when real, ACL-visible evidence was actually read to form the decision.
        accessed = citation_ids or tuple(candidate_doc_ids)
        if accessed:
            self._audit_citation_access(
                principal=principal,
                correlation_id=ans.correlation_id,
                citation_ids=accessed,
                document_ids=tuple(candidate_doc_ids),
            )
        return ans

    def _audit_citation_access(
        self,
        *,
        principal: IdentityClaims,
        correlation_id: str,
        citation_ids: tuple[str, ...],
        document_ids: tuple[str, ...],
    ) -> None:
        """Record a citation-access event (reference IDs only) — FR-MFG-021 / SC-MFG-010."""
        ts = datetime_now_iso()
        self.audit.record(
            AuditLogEntry(
                tenant_id=principal.tenant_id,
                log_id=f"citation.access:{correlation_id or ts}:{ts}",
                timestamp=ts,
                request_id=correlation_id or None,
                actor_id=principal.user_id,
                action="citation.access",
                resource_type="citation",
                resource_id=correlation_id or None,
                decision="accessed",
                citation_ids=tuple(citation_ids),
                document_ids_used=tuple(document_ids),
            )
        )

    def _audit_acl_denials(self, principal: IdentityClaims, collection_id: str | None) -> None:
        """Journal an ACL denial when the principal is barred from in-tenant documents (FR-MFG-021).

        Walks the reused 001 vector store for chunks in the principal's tenant (optionally scoped to
        ``collection_id``) that are NOT visible under the 001 ACL pre-filter. Each denied document is
        recorded ONCE via the existing ``record_denial`` helper (action ``acl.denied``, reference IDs
        only). This builds NO new authz — it observes the SAME deny-by-default decision the retrieval
        pre-filter already makes.
        """
        visible = self._mvp.acl.visibility(principal)
        seen: set[str] = set()
        for chunk, _vec in self._mvp.store.iter_items():
            if chunk.tenant_id != principal.tenant_id or chunk.tombstone:
                continue
            if collection_id is not None and chunk.collection_id != collection_id:
                continue
            if chunk.document_id in seen:
                continue
            if not visible(chunk):
                seen.add(chunk.document_id)
                record_denial(self.audit, principal=principal, chunk=chunk, reason="acl_denied")

    # --- search (001 retrieval + approval tags) ---------------------------------------------------
    def search(
        self,
        principal: IdentityClaims,
        query: str,
        collection_id: str | None = None,
        manufacturing_filters: dict | None = None,
    ):
        profile = self._mvp.profiles.resolve(collection_id)
        results = self._search.search(
            principal, query, profile, manufacturing_filters=manufacturing_filters
        )
        # GAP-F3 — audit the search-query ACCESS (FR-MFG-021: search query). Reference IDs only: the
        # ACL-visible result document_ids surveyed, never the query text / body / customer name.
        self._audit_search_query(
            principal=principal,
            collection_id=collection_id,
            document_ids=tuple(
                dict.fromkeys(r.document_id for r in results if getattr(r, "document_id", None))
            ),
        )
        return results

    def _audit_search_query(
        self,
        *,
        principal: IdentityClaims,
        collection_id: str | None,
        document_ids: tuple[str, ...],
    ) -> None:
        """Record a search-query access event (reference IDs only) — FR-MFG-021 / SC-MFG-010."""
        ts = datetime_now_iso()
        self.audit.record(
            AuditLogEntry(
                tenant_id=principal.tenant_id,
                log_id=f"search.query:{collection_id or ''}:{ts}",
                timestamp=ts,
                actor_id=principal.user_id,
                action="search.query",
                resource_type="collection",
                resource_id=collection_id,  # reference ID only; None for tenant-wide search
                decision="executed",
                document_ids_used=tuple(document_ids),
            )
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

    # --- trouble cases (US3: register + search; contracts §C; FR-MFG-008/009) ---------------------
    def register_trouble_case(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        source_document_id: str,
        text: str,
        metadata: ManufacturingDocumentMetadata,
        trouble_case: TroubleCase,
        failure_mode: FailureMode | None = None,
        countermeasures: tuple[Countermeasure, ...] = (),
        recurrence_prevention: str | None = None,
        source_id: str = "src",
    ) -> None:
        """Seed a past TroubleCase: ingest the report body via the REUSED 001 ingestion path (so its
        chunks are retrievable AND subject to the 001 ACL PRE-filter) and register the
        TroubleCase/FailureMode/Countermeasure graph + recurrence note (T034).

        Visibility is decided by the 001 ACL over the ingested source document — NOT by this store.
        """
        # Reuse the 001 ingestion + manufacturing metadata-attach path (same as every other endpoint),
        # so the body is retrievable through the 001 RetrievalService deny-by-default PRE-filter.
        self.ingest_manufacturing(
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=source_document_id,
            text=text,
            metadata=metadata,
            source_id=source_id,
        )
        # Register the knowledge-graph relations, keyed by the source 001 Document (the ACL anchor).
        self._trouble_cases.register(
            tenant_id=tenant_id,
            source_document_id=source_document_id,
            trouble_case=trouble_case,
            failure_mode=failure_mode,
            countermeasures=tuple(countermeasures),
            recurrence_prevention=recurrence_prevention,
        )

    def search_trouble_cases(
        self,
        principal: IdentityClaims,
        symptom_query: str,
        *,
        collection_id: str | None = None,
        manufacturing_filters: dict | None = None,
        top_k: int | None = None,
    ) -> TroubleCaseSearchResponse:
        """POST /v1/manufacturing/trouble-cases/search (contracts §C, FR-MFG-008/009).

        Finds similar past TroubleCases via the reused 001 RetrievalService (ACL PRE-filter), resolves
        each ACL-visible case to its FailureMode (cause) + provisional/permanent-split Countermeasures
        (normalized to candidate/past-example, Hard Rule 4) + recurrence note + citations. Audited
        (FR-MFG-021). An unauthorized confidential case never surfaces — its source chunk is excluded
        by the 001 deny-by-default pre-filter BEFORE scoring (SC-MFG-008, extended).
        """
        profile = self._mvp.profiles.resolve(collection_id)
        if top_k is not None:
            from dataclasses import replace as _replace

            profile = _replace(profile, top_k=top_k)
        return self._trouble_search.search(
            principal,
            symptom_query,
            profile,
            manufacturing_filters=manufacturing_filters,
        )

    # --- governance: no-train (T057, FR-MFG-016~018/029, SC-MFG-009, GQ1) -------------------------
    def use_for_training(self, *, tenant_id: str, data_kind: str, actor: IdentityClaims) -> None:
        """Single funnel for "use customer data for training/improvement".

        Delegates to ``no_train.assert_no_train`` BEFORE any use (so opt-in-less training is
        impossible) and audits the attempt/decision. Raises on refusal (default policy refuses;
        SC-MFG-009 = 0 accepted uses without a valid admin opt-in).
        """
        ts = datetime_now_iso()
        try:
            self.no_train.assert_no_train(tenant_id, data_kind)
        except Exception:
            self._audit_training_use(
                tenant_id=tenant_id, data_kind=data_kind, actor=actor, decision="refused", ts=ts
            )
            raise
        self._audit_training_use(
            tenant_id=tenant_id, data_kind=data_kind, actor=actor, decision="permitted", ts=ts
        )

    def _audit_training_use(
        self, *, tenant_id: str, data_kind: str, actor: IdentityClaims, decision: str, ts: str
    ) -> None:
        self.audit.record(
            AuditLogEntry(
                tenant_id=tenant_id,
                log_id=f"no_train.use:{tenant_id}:{ts}",
                timestamp=ts,
                actor_id=actor.user_id if actor else None,
                action="no_train.training_use",
                resource_type="data_use_policy",
                resource_id=tenant_id,  # reference ID only
                decision=decision,
                reason=data_kind,  # a reference label (answer/draft/feedback/eval) — not body text
            )
        )

    def capability_status(self, tenant_id: str, capability: str) -> str:
        """'temporarily_unavailable' when the capability is blocked (GQ1), else 'ok'."""
        return self.no_train.capability_status(tenant_id, capability)

    def resolve_capability_provider(self, tenant_id: str, capability: str) -> str | None:
        """A no-train-guaranteed provider for the capability, or None when blocked (no silent degrade)."""
        return self.no_train.resolve_capability_provider(tenant_id, capability)

    # --- governance: data-use policy / status / export (T062/T063/T064) ---------------------------
    def get_data_use_policy(self, tenant_id: str):
        """GET /v1/manufacturing/policy/data-use — GQ1/GQ2 safe default (auto-seeded)."""
        return self._governance.get_data_use_policy(tenant_id)

    def update_data_use_policy(self, *, tenant_id: str, patch: dict, actor: IdentityClaims):
        """PUT /v1/manufacturing/policy/data-use — patch + version bump + opt-in invariant + audit."""
        return self._governance.update_data_use_policy(
            tenant_id=tenant_id, patch=patch, actor=actor
        )

    def governance_status(self, tenant_id: str) -> dict:
        """GET /v1/manufacturing/governance/status — core features + ISMAP readiness memo."""
        return self._governance.governance_status(tenant_id)

    def export_audit(self, *, principal: IdentityClaims, fmt: str = "jsonl"):
        """GET /v1/manufacturing/audit/export — tenant-scoped, reference-only, hash-chain exposed."""
        return self._governance.export_audit(principal=principal, fmt=fmt)

    # --- governance: deletion / tombstone (T061; reuses 001 tombstone) ----------------------------
    def delete_document(self, *, tenant_id: str, document_id: str, actor: IdentityClaims):
        """Delete a document via the REUSED 001 tombstone/cascade path; audited as a deletion.

        A deleted document never reappears in search/answer/citation (SC-003). The audit entry holds
        reference IDs only (the document_id), never the body / customer name.
        """
        result = self._mvp.deletion.delete(tenant_id, document_id)
        ts = datetime_now_iso()
        self.audit.record(
            AuditLogEntry(
                tenant_id=tenant_id,
                log_id=f"deletion.tombstone:{document_id}:{ts}",
                timestamp=ts,
                actor_id=actor.user_id if actor else None,
                action="deletion.tombstone",
                resource_type="document",
                resource_id=document_id,  # reference ID only — never the confidential body
                decision="tombstoned",
                reason=f"chunks={result.tombstoned_chunks}",
                document_ids_used=(document_id,),
            )
        )
        return result

    # --- governance: retention enforcement (GAP-F1; FR-MFG-020, GQ2; reuses 001 tombstone) ---------
    def expire_document(self, *, tenant_id: str, document_id: str, actor: IdentityClaims):
        """Expire a single document past its retention window via the REUSED 001 tombstone path.

        Delegates to the same 001 DeletionService as delete_document (tombstone + cascade); an expired
        document never reappears in search/answer/citation (SC-003). Audited as a deletion (reference
        IDs only) — reuses the delete_document funnel so the audit-coverage closed list is unchanged.
        """
        return self.delete_document(tenant_id=tenant_id, document_id=document_id, actor=actor)

    def run_retention_sweep(
        self, *, tenant_id: str, actor: IdentityClaims, now_iso: str | None = None
    ) -> tuple[str, ...]:
        """Expire every live document whose age exceeds the tenant's effective customer-data retention.

        Age is computed from the 001 ``Document.created_at`` (ISO UTC, set at ingest). The window is
        ``effective_retention(tenant_id).retention_customer_days`` (GQ2 default 365, clamped to
        30..3650). Each past-window document is expired via :meth:`expire_document` (001 tombstone +
        cascade, SC-003). Returns the expired document_ids; emits ONE summary audit entry (reference
        IDs only — the count + the expired ids, never body/customer). NOT auto-scheduled: an admin
        endpoint / future Dagster job must invoke it; this is the honest minimal wiring.
        """
        now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
        retention_days = self.retention.effective_retention(tenant_id).retention_customer_days
        cutoff = now - timedelta(days=retention_days)
        # documents_for_tenant returns a snapshot tuple, so expiring (which tombstones registry docs)
        # under iteration is safe.
        candidates = [
            doc.document_id
            for doc in self._mvp.registry.documents_for_tenant(tenant_id)
            if not doc.tombstone
            and doc.created_at
            and datetime.fromisoformat(doc.created_at) < cutoff
        ]
        expired: list[str] = []
        for document_id in candidates:
            self.expire_document(tenant_id=tenant_id, document_id=document_id, actor=actor)
            expired.append(document_id)
        ts = datetime_now_iso()
        self.audit.record(
            AuditLogEntry(
                tenant_id=tenant_id,
                log_id=f"retention.sweep:{tenant_id}:{ts}",
                timestamp=ts,
                actor_id=actor.user_id if actor else None,
                action="retention.sweep",
                resource_type="data_use_policy",
                resource_id=tenant_id,  # reference ID only
                decision="swept",
                reason=f"retention_days={retention_days};expired={len(expired)}",
                document_ids_used=tuple(expired),
            )
        )
        return tuple(expired)

    # --- US5: knowledge-ops dashboard / safety-telemetry / KPI (contracts §E; FR-MFG-012/028/030) --
    def record_answer_feedback(
        self,
        *,
        principal: IdentityClaims,
        rating: int,
        answer_correlation_id: str = "",
        document_ids: tuple[str, ...] = (),
        comment: str | None = None,
        collection_id: str | None = None,
    ) -> bool:
        """POST /v1/manufacturing/answers/{id}/feedback (FR-MFG-021/012/028).

        Records a user/reviewer rating of an answer as an audited, reference-IDs-only event (the
        SINGLE source of truth). The low-rating dashboard surface + KPI low_rating_rate are DERIVED
        from this audit action (api/dashboard.py / kpi/poc_metrics.py), never a parallel store.

        ``comment`` is accepted for API parity with the 001 FeedbackRequest but is INTENTIONALLY
        DROPPED here: no free-text body reaches the audit log (SC-MFG-010 = PII/secret/body 0).
        Returns True iff the rating is low (<= LOW_RATING_THRESHOLD).
        """
        return record_answer_feedback(
            self.audit,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            rating=rating,
            answer_correlation_id=answer_correlation_id,
            document_ids=tuple(document_ids),
            collection_id=collection_id,
        )

    def _audit_admin_access(
        self,
        *,
        principal: IdentityClaims,
        action: str,
        resource_type: str,
        decision: str = "accessed",
    ) -> None:
        """Record an admin read-view access (dashboard / safety-telemetry / KPI) — reference IDs only.

        No body / query / customer name is stored; the entry carries NO high_risk / safety_block flag,
        so it is inert for the audit-derived safety telemetry (single-source-of-truth scan), FR-MFG-021.
        """
        ts = datetime_now_iso()
        self.audit.record(
            AuditLogEntry(
                tenant_id=principal.tenant_id,
                log_id=f"{action}:{principal.tenant_id}:{ts}",
                timestamp=ts,
                actor_id=principal.user_id,
                action=action,
                resource_type=resource_type,
                resource_id=principal.tenant_id,  # reference ID only
                decision=decision,
            )
        )

    def knowledge_ops_dashboard(
        self,
        principal: IdentityClaims,
        *,
        collection_id: str | None = None,
        factory_id: str | None = None,
        department_id: str | None = None,
        time_range: tuple[str, str] | None = None,
    ):
        """GET /v1/manufacturing/dashboard (FR-MFG-012, US5-1).

        Surfaces unanswered / low-rating / frequent-questions / frequently-referenced-documents /
        obsolete(stale) candidates / knowledge-gap areas, all DERIVED from the shared audit log
        (single source of truth) + in-memory approval metadata. Tenant-scoped; computed
        synchronously (no Dagster — T047a/T051a deferred, §8 C5).
        """
        self._audit_admin_access(
            principal=principal, action="dashboard.access", resource_type="dashboard"
        )
        return self._dashboard.knowledge_ops_dashboard(
            principal,
            collection_id=collection_id,
            factory_id=factory_id,
            department_id=department_id,
            time_range=time_range,
        )

    def safety_telemetry(
        self,
        principal: IdentityClaims,
        *,
        collection_id: str | None = None,
        factory_id: str | None = None,
        department_id: str | None = None,
        time_range: tuple[str, str] | None = None,
        axis=None,
        granularity: str = "daily",
    ):
        """GET /v1/manufacturing/safety-telemetry (FR-MFG-030, SC-MFG-013).

        Audit-derived high_risk_query_count / safety_gate_block_count + mutually-exclusive breakdown
        (single source of truth, idempotent GROUP/SUM). Restricts to a factory/department axis when
        supplied; ``source == 'audit_log'``. Tenant-scoped.
        """
        self._audit_admin_access(
            principal=principal, action="dashboard.access", resource_type="safety_telemetry"
        )
        return self._dashboard.safety_telemetry(
            principal,
            collection_id=collection_id,
            factory_id=factory_id,
            department_id=department_id,
            time_range=time_range,
            axis=axis,
            granularity=granularity,
        )

    def kpi(
        self,
        principal: IdentityClaims,
        *,
        collection_id: str | None = None,
        time_range: tuple[str, str] | None = None,
        format: str = "json",
    ):
        """GET /v1/manufacturing/kpi (FR-MFG-028, SC-MFG-012).

        Computes the full FR-MFG-028 KPI set and EXPORTS it as json (dict) or csv (str). The safety
        counters reuse the SAME audit-derived telemetry as GET /safety-telemetry (consistency).
        Computed synchronously (no Dagster — T047a/T051a deferred, §8 C5).
        """
        self._audit_admin_access(
            principal=principal, action="kpi.export", resource_type="kpi", decision=format
        )
        return self._dashboard.kpi(
            principal,
            collection_id=collection_id,
            time_range=time_range,
            format=format,
        )
