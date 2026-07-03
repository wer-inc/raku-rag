"""T043/T044 — Draft service: create / assign / review / get on ManufacturingSystem (US4).

Orchestrates the reused ``DraftGenerator`` (drafts/generator.py) + ``ReviewWorkflow`` (drafts/review.py)
behind the in-memory ``ManufacturingSystem`` entrypoints, mirroring contracts §D (POST /drafts,
.../assign, .../review, GET .../{id}) as Python methods (not HTTP).

System-of-record discipline (load-bearing for SC-MFG-007):
  - the store holds the CANONICAL DraftArtifact; ``create`` / ``get`` / ``assign`` / ``review`` all
    return a DETACHED COPY. Mutating a returned copy (e.g. ``art.status = APPROVED``) can never flip
    the stored record — only the reviewer workflow performed here mutates the canonical object.
  - ``approved`` is reachable ONLY through ``review`` with an attributable reviewer; ``create`` always
    yields ``status=draft`` + ``created_by=ai``; AI cannot self-approve (Hard Rule 1).

Every transition (generation, assignment, decision) is recorded into the reused ``AuditLogWriter``
with reference IDs only — generation time, creator, template, source documents (FR-MFG-010b/021).

stdlib only.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.api.draft_store import (
    DraftStore,
    InMemoryDraftStore,
    copy_artifact,
)
from raku_rag.manufacturing.domain.audit import AuditLogEntry
from raku_rag.manufacturing.domain.draft import DraftArtifact, DraftStatus, DraftType
from raku_rag.manufacturing.domain.metadata import (
    ApprovalSource,
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.drafts.generator import DraftGenerator, coerce_kind
from raku_rag.manufacturing.drafts.render import render_draft_markdown
from raku_rag.manufacturing.drafts.review import InvalidTransitionError, ReviewWorkflow
from raku_rag.manufacturing.interfaces import AuditLogWriter

from typing import Callable

GetMfgMeta = Callable[[str, str], ManufacturingDocumentMetadata | None]
# (principal, document_id) -> may this principal use this doc as a draft source? True iff the doc is
# NOT tombstoned AND is ACL-readable, OR resolves to no 001 Document at all (a never-ingested id
# references nothing and therefore cannot leak -> keep it). SC-MFG-008 / data-model.md:86,146-147.
CanUseSource = Callable[[IdentityClaims, str], bool]
# Publish-time ingestion seam (issue 0019): called as
#   ingest(collection_id=..., document_id=..., text=..., metadata=...)
# ManufacturingSystem supplies its REUSED manufacturing ingestion path (001 parse->chunk->embed->index
# + metadata attach) here, so DraftService never grows a parallel ingest mechanism.
IngestPublishedDraft = Callable[..., object]

# Draft kind -> published DocumentKind (data-model §B). FAQ has no DocumentKind (the 0006 CHECK
# enumerates 8 kinds without faq) — its kind rides in metadata.extra["draft_kind"] instead.
_PUBLISH_DOCUMENT_KIND: dict[DraftType, DocumentKind | None] = {
    DraftType.CHECKLIST: DocumentKind.INSPECTION,
    DraftType.TROUBLE_REPORT: DocumentKind.TROUBLE_REPORT,
    DraftType.QUALITY_REPORT: DocumentKind.QUALITY_REPORT,
    DraftType.TRAINING: DocumentKind.TRAINING,
    DraftType.FAQ: None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DraftService:
    """In-memory draft store + generator/review orchestration with audit (US4)."""

    def __init__(
        self,
        *,
        audit: AuditLogWriter,
        get_mfg_meta: GetMfgMeta | None = None,
        can_use_source: CanUseSource | None = None,
        today: date | None = None,
        store: DraftStore | None = None,
    ) -> None:
        self._audit = audit
        self._can_use_source = can_use_source
        self._today = today  # injected clock for deterministic effective_date in tests
        self._generator = DraftGenerator(get_mfg_meta=get_mfg_meta, today=today)
        self._review = ReviewWorkflow()
        # The canonical DraftArtifact lives behind the DraftStore seam (in-memory for unit tests /
        # single-process MVP; Postgres in production so the queue survives restart — issue 0012).
        self._store: DraftStore = store or InMemoryDraftStore()

    # --- POST /v1/manufacturing/drafts -------------------------------------------------------------
    def create(
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
        """Generate a draft (ALWAYS status=draft, created_by=ai), persist it, audit, return a copy."""
        tenant_id = principal.tenant_id
        draft_type = coerce_kind(kind)
        artifact_id = self._store.next_id()
        created_at = _now()

        # SC-MFG-008 / data-model.md:86,146-147 — a draft must NOT surface a tombstoned or
        # ACL-unreadable document via its provenance/grounding. EXCLUDE such sources (and their
        # citations) up-front so source_document_ids / source_citations / content are all clean.
        # Reuses the SAME 001 deny-by-default ACL + tombstone decision (no parallel authz path); a
        # never-ingested id resolves to no Document and is kept (it references nothing -> cannot leak).
        if self._can_use_source is not None:
            context_citations = tuple(
                c
                for c in (context_citations or ())
                if self._can_use_source(principal, c.document_id)
            )
            source_document_ids = tuple(
                d for d in (source_document_ids or ()) if self._can_use_source(principal, d)
            )

        artifact = self._generator.generate(
            artifact_id=artifact_id,
            tenant_id=tenant_id,
            kind=draft_type,
            actor=principal,
            created_at=created_at,
            context_citations=context_citations,
            source_document_ids=source_document_ids,
            template_id=template_id,
            collection_id=collection_id,
            manufacturing_filters=manufacturing_filters,
        )

        log_id = self._audit_generation(artifact, actor_id=principal.user_id)
        artifact.audit_log_ref = log_id

        # Persist the canonical record; hand the caller a detached copy.
        self._store.add(artifact)
        return copy_artifact(artifact)

    # --- GET /v1/manufacturing/drafts (list) -------------------------------------------------------
    def list(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        reviewer_id: str | None = None,
    ) -> list[DraftArtifact]:
        """Return detached copies of tenant drafts, newest first. Optional status/reviewer filters."""
        return self._store.list(tenant_id, status=status, reviewer_id=reviewer_id)

    # --- GET /v1/manufacturing/drafts/{artifact_id} ------------------------------------------------
    def get(self, tenant_id: str, artifact_id: str) -> DraftArtifact | None:
        """Return a DETACHED COPY of the stored draft (external mutation cannot flip the record)."""
        artifact = self._store.get(tenant_id, artifact_id)
        return copy_artifact(artifact) if artifact is not None else None

    # --- POST .../assign ---------------------------------------------------------------------------
    def assign(
        self,
        *,
        tenant_id: str,
        artifact_id: str,
        reviewer_id: str | None = None,
        reviewer_group: str | None = None,
        reviewer_role: str | None = None,
    ) -> DraftArtifact:
        """draft -> in_review with reviewer attribution + assigned_at. Audited."""
        artifact = self._require(tenant_id, artifact_id)
        self._review.assign(
            artifact,
            reviewer_id=reviewer_id,
            reviewer_group=reviewer_group,
            reviewer_role=reviewer_role,
        )
        self._store.save(artifact)
        self._audit_transition(
            artifact,
            action="draft.assign",
            actor_id=reviewer_id,
            decision=artifact.status.value,
        )
        return copy_artifact(artifact)

    # --- POST .../review ---------------------------------------------------------------------------
    def review(
        self,
        *,
        tenant_id: str,
        artifact_id: str,
        reviewer: IdentityClaims | None,
        decision: str,
        comment: str | None = None,
    ) -> DraftArtifact:
        """Record a reviewer decision. approve REQUIRES a reviewer (else raises; record unchanged)."""
        artifact = self._require(tenant_id, artifact_id)
        # decide() raises PermissionError on a no-reviewer approve WITHOUT mutating the artifact, so
        # the canonical record stays draft (Hard Rule 1, SC-MFG-007).
        self._review.decide(artifact, reviewer=reviewer, decision=decision, comment=comment)
        # decide() raised above on a no-reviewer approve WITHOUT mutating, so we only reach save() on a
        # legal transition — the canonical record is persisted (Postgres) or re-put (in-memory).
        self._store.save(artifact)
        self._audit_transition(
            artifact,
            action="draft.review",
            actor_id=artifact.reviewer_id,
            decision=artifact.approval_decision or artifact.status.value,
        )
        return copy_artifact(artifact)

    # --- POST .../publish (issue 0019) --------------------------------------------------------------
    def publish(
        self,
        *,
        tenant_id: str,
        artifact_id: str,
        actor: IdentityClaims | None,
        ingest: IngestPublishedDraft,
    ) -> DraftArtifact:
        """Publish an APPROVED draft into the knowledge base as an approved 001 Document.

        Publish is a SEPARATE, attributable HUMAN action after approval (Hard Rule 1 stays intact:
        the reviewer approval alone never publishes, and AI can neither approve nor publish):
          - ``actor`` must be an attributable human principal (no user_id -> PermissionError; the
            actor always comes from the signed principal, never the request body);
          - only ``status=approved`` drafts publish; draft/in_review/rejected/archived raise
            ``InvalidTransitionError`` (the server maps it to 409);
          - idempotency: an already-published draft raises ``InvalidTransitionError`` (409/no-op —
            a second publish can never mint a second document);
          - the draft content is rendered deterministically (drafts/render.py) and ingested via the
            INJECTED manufacturing ingestion seam with approved+effective metadata and full
            provenance (source draft, source citations/documents) in ``metadata.extra``;
          - the transition is recorded in the hash-chain audit (``draft.published``: actor,
            draft_id, new document_id) and on the artifact (published_document_id/by/at).
        """
        if actor is None or not getattr(actor, "user_id", None):
            # Unattributable/AI publish attempt — reject; the stored artifact is untouched.
            raise PermissionError(
                "publish requires an explicit human actor (AI cannot publish, Hard Rule 1)"
            )
        artifact = self._require(tenant_id, artifact_id)
        if artifact.published_document_id:
            raise InvalidTransitionError(
                f"draft {artifact_id} is already published as "
                f"document {artifact.published_document_id}"
            )
        if artifact.status != DraftStatus.APPROVED:
            raise InvalidTransitionError(
                f"cannot publish from status={artifact.status.value!r} "
                f"(publish requires a reviewer-approved draft, issue 0019)"
            )

        document_id = f"pub_{artifact.artifact_id}"
        today = (self._today or datetime.now(timezone.utc).date()).isoformat()
        metadata = ManufacturingDocumentMetadata(
            tenant_id=tenant_id,
            document_id=document_id,
            document_kind=_PUBLISH_DOCUMENT_KIND.get(artifact.type),
            # Approved + effective TODAY: the published knowledge is immediately citable, including
            # by the high-risk approved+effective evidence gate (FR-MFG-005).
            approval_status=ApprovalStatus.APPROVED,
            approval_source=ApprovalSource.WORKFLOW,
            effective_date=today,
            approved_by=artifact.reviewer_id or actor.user_id,
            approved_at=artifact.reviewed_at,
            extra={
                # Provenance: which draft this document came from and what grounded it. The 0006
                # CHECK pins approval_source to imported|workflow, so the finer-grained publish
                # origin is carried here instead of as a new ApprovalSource value.
                "approval_source_detail": "draft_publish",
                "published_from_draft_id": artifact.artifact_id,
                "draft_kind": artifact.type.value,
                "source_document_ids": list(artifact.source_document_ids),
                "source_citations": list(artifact.source_citations),
            },
        )
        # Ingest FIRST; only a successful ingest marks the artifact published (a failed ingest
        # leaves the draft publishable again — no phantom published_document_id).
        ingest(
            collection_id=artifact.collection_id,
            document_id=document_id,
            text=render_draft_markdown(artifact),
            metadata=metadata,
        )

        artifact.published_document_id = document_id
        artifact.published_by = actor.user_id
        artifact.published_at = _now()
        self._store.save(artifact)
        self._audit_publish(artifact, actor_id=actor.user_id)
        return copy_artifact(artifact)

    # --- internals ---------------------------------------------------------------------------------
    def _require(self, tenant_id: str, artifact_id: str) -> DraftArtifact:
        artifact = self._store.get(tenant_id, artifact_id)
        if artifact is None:
            raise ValueError(f"draft not found: {artifact_id}")
        return artifact

    def _audit_generation(self, artifact: DraftArtifact, *, actor_id: str | None) -> str:
        """Audit DraftArtifact generation: time / creator / template / source docs (FR-MFG-010b)."""
        ts = artifact.created_at or _now()
        log_id = f"draft.generate:{artifact.artifact_id}:{ts}"
        self._audit.record(
            AuditLogEntry(
                tenant_id=artifact.tenant_id,
                log_id=log_id,
                timestamp=ts,
                actor_id=actor_id,
                action="draft.generate",
                resource_type="draft_artifact",
                resource_id=artifact.artifact_id,
                decision=artifact.status.value,
                reason=artifact.type.value,
                document_ids_used=tuple(artifact.source_document_ids),
                client_metadata={
                    "created_by": (
                        artifact.created_by.value if artifact.created_by is not None else None
                    ),
                    "template_id": artifact.template_id,
                },
            )
        )
        return log_id

    def _audit_publish(self, artifact: DraftArtifact, *, actor_id: str) -> None:
        """Audit the publish action into the hash chain (FR-MFG-021): actor / draft / new doc."""
        ts = artifact.published_at or _now()
        self._audit.record(
            AuditLogEntry(
                tenant_id=artifact.tenant_id,
                log_id=f"draft.published:{artifact.artifact_id}:{ts}",
                timestamp=ts,
                actor_id=actor_id,
                action="draft.published",
                resource_type="draft_artifact",
                resource_id=artifact.artifact_id,
                decision="published",
                reason=artifact.type.value,
                # Reference IDs only: the new document + the grounding sources it inherited.
                document_ids_used=(
                    artifact.published_document_id,
                    *artifact.source_document_ids,
                ),
                client_metadata={
                    "published_document_id": artifact.published_document_id,
                    "reviewer_id": artifact.reviewer_id,
                },
            )
        )

    def _audit_transition(
        self, artifact: DraftArtifact, *, action: str, actor_id: str | None, decision: str | None
    ) -> None:
        """Audit an assign / review state transition (FR-MFG-021)."""
        ts = _now()
        self._audit.record(
            AuditLogEntry(
                tenant_id=artifact.tenant_id,
                log_id=f"{action}:{artifact.artifact_id}:{ts}",
                timestamp=ts,
                actor_id=actor_id,
                action=action,
                resource_type="draft_artifact",
                resource_id=artifact.artifact_id,
                decision=decision,
                reason=artifact.type.value,
                client_metadata={
                    "status": artifact.status.value,
                    "reviewer_role": artifact.reviewer_role,
                    "reviewer_group": artifact.reviewer_group,
                },
            )
        )
