"""DraftStore — the persistence seam for DraftArtifact (data-model §F, issue 0012).

``DraftService`` orchestrates generation / review / audit; WHERE the canonical DraftArtifact lives is
behind this Protocol so the implementations are interchangeable:
  - ``InMemoryDraftStore`` — process-local dict (unit tests / single-process MVP). NOT durable.
  - ``PostgresDraftStore`` (persistence/manufacturing_drafts.py) — durable across answer-service
    restarts and shared across instances, wired in the production composition.

System-of-record discipline (SC-MFG-007): the store holds the CANONICAL artifact. ``get`` returns a
mutable instance the service may drive through the review workflow and then ``save``; external reads
(``DraftService.get`` / ``.list``) hand out detached copies so a caller can never flip a stored record.

stdlib only.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Protocol

from raku_rag.manufacturing.domain.draft import DraftArtifact


def copy_artifact(artifact: DraftArtifact) -> DraftArtifact:
    """Detached shallow copy; ``content`` is copied so callers can't mutate the stored body."""
    clone = replace(artifact)
    clone.content = dict(artifact.content)
    return clone


class DraftStore(Protocol):
    """Storage seam for the canonical DraftArtifact, keyed by (tenant_id, artifact_id)."""

    def next_id(self) -> str:
        """Allocate a new artifact_id."""
        ...

    def add(self, artifact: DraftArtifact) -> None:
        """Insert a freshly generated artifact."""
        ...

    def get(self, tenant_id: str, artifact_id: str) -> DraftArtifact | None:
        """Return the stored artifact (mutable; service mutates then ``save``) or None."""
        ...

    def save(self, artifact: DraftArtifact) -> None:
        """Persist a mutated artifact (upsert by (tenant_id, artifact_id))."""
        ...

    def list(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        reviewer_id: str | None = None,
    ) -> list[DraftArtifact]:
        """Detached copies of the tenant's drafts, newest first, optional status/reviewer filters."""
        ...


class InMemoryDraftStore:
    """Process-local dict store (unit tests / single-process MVP). NOT durable across restarts."""

    def __init__(self) -> None:
        # (tenant_id, artifact_id) -> canonical DraftArtifact (the system of record).
        self._store: dict[tuple[str, str], DraftArtifact] = {}
        self._ids = itertools.count(1)

    def next_id(self) -> str:
        return f"art_{next(self._ids)}"

    def add(self, artifact: DraftArtifact) -> None:
        self._store[(artifact.tenant_id, artifact.artifact_id)] = artifact

    def get(self, tenant_id: str, artifact_id: str) -> DraftArtifact | None:
        return self._store.get((tenant_id, artifact_id))

    def save(self, artifact: DraftArtifact) -> None:
        self._store[(artifact.tenant_id, artifact.artifact_id)] = artifact

    def list(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        reviewer_id: str | None = None,
    ) -> list[DraftArtifact]:
        items: list[DraftArtifact] = []
        for (tid, _aid), artifact in self._store.items():
            if tid != tenant_id:
                continue
            if status and artifact.status.value != status:
                continue
            if reviewer_id and artifact.reviewer_id != reviewer_id:
                continue
            items.append(copy_artifact(artifact))
        items.sort(key=lambda a: a.created_at or "", reverse=True)
        return items
