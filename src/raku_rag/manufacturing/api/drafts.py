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

import itertools
from dataclasses import replace
from datetime import date, datetime, timezone

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import AuditLogEntry, InMemoryAuditLogWriter
from raku_rag.manufacturing.domain.draft import DraftArtifact, DraftType
from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata
from raku_rag.manufacturing.drafts.generator import DraftGenerator, coerce_kind
from raku_rag.manufacturing.drafts.review import ReviewWorkflow

from typing import Callable

GetMfgMeta = Callable[[str, str], ManufacturingDocumentMetadata | None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DraftService:
    """In-memory draft store + generator/review orchestration with audit (US4)."""

    def __init__(
        self,
        *,
        audit: InMemoryAuditLogWriter,
        get_mfg_meta: GetMfgMeta | None = None,
        today: date | None = None,
    ) -> None:
        self._audit = audit
        self._generator = DraftGenerator(get_mfg_meta=get_mfg_meta, today=today)
        self._review = ReviewWorkflow()
        # (tenant_id, artifact_id) -> canonical DraftArtifact (the system of record).
        self._store: dict[tuple[str, str], DraftArtifact] = {}
        self._ids = itertools.count(1)

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
        artifact_id = f"art_{next(self._ids)}"
        created_at = _now()

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
        self._store[(tenant_id, artifact_id)] = artifact
        return self._copy(artifact)

    # --- GET /v1/manufacturing/drafts/{artifact_id} ------------------------------------------------
    def get(self, tenant_id: str, artifact_id: str) -> DraftArtifact | None:
        """Return a DETACHED COPY of the stored draft (external mutation cannot flip the record)."""
        artifact = self._store.get((tenant_id, artifact_id))
        return self._copy(artifact) if artifact is not None else None

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
        self._audit_transition(
            artifact,
            action="draft.assign",
            actor_id=reviewer_id,
            decision=artifact.status.value,
        )
        return self._copy(artifact)

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
        self._audit_transition(
            artifact,
            action="draft.review",
            actor_id=artifact.reviewer_id,
            decision=artifact.approval_decision or artifact.status.value,
        )
        return self._copy(artifact)

    # --- internals ---------------------------------------------------------------------------------
    def _require(self, tenant_id: str, artifact_id: str) -> DraftArtifact:
        artifact = self._store.get((tenant_id, artifact_id))
        if artifact is None:
            raise ValueError(f"draft not found: {artifact_id}")
        return artifact

    @staticmethod
    def _copy(artifact: DraftArtifact) -> DraftArtifact:
        """Detached shallow copy; ``content`` is copied so callers can't mutate the stored body."""
        clone = replace(artifact)
        clone.content = dict(artifact.content)
        return clone

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
