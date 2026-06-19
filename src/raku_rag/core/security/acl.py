"""T011 — AclPolicy: deny-by-default, hierarchical (tenant→collection→document) grants (FR-022/025a).

Provides a ``visibility`` predicate used as a PRE-filter inside VectorStore.search, plus
``assert_visible`` for the double-defense post-check in RetrievalService.
"""
from __future__ import annotations

from collections.abc import Iterable

from raku_rag.core.errors import RagError
from raku_rag.domain.models import ACLGrant, Chunk, Document, IdentityClaims, ScopeType, SubjectType


class AclDenied(RagError):
    """Raised by the post-check when a chunk slipped through that the principal cannot read."""


class AclPolicy:
    def __init__(self, grants: Iterable[ACLGrant]) -> None:
        self._grants = list(grants)

    def add(self, grant: ACLGrant) -> None:
        self._grants.append(grant)

    def _subjects_of(self, p: IdentityClaims) -> set[tuple[SubjectType, str]]:
        subs: set[tuple[SubjectType, str]] = {(SubjectType.USER, p.user_id)}
        subs |= {(SubjectType.GROUP, g) for g in p.groups}
        subs |= {(SubjectType.ROLE, r) for r in p.roles}
        return subs

    def can_read(
        self, p: IdentityClaims, *, tenant_id: str, collection_id: str, document_id: str
    ) -> bool:
        """deny-by-default. A read requires a grant matching tenant + (covering scope) + subject."""
        if p.tenant_id != tenant_id:  # tenant boundary is structural (FR-021a)
            return False
        subjects = self._subjects_of(p)
        for g in self._grants:
            if g.tenant_id != tenant_id or g.permission != "read":
                continue
            if (g.subject_type, g.subject_id) not in subjects:
                continue
            if g.scope_type is ScopeType.TENANT and g.scope_id == tenant_id:
                return True
            if g.scope_type is ScopeType.COLLECTION and g.scope_id == collection_id:
                return True
            if g.scope_type is ScopeType.DOCUMENT and g.scope_id == document_id:
                return True
        return False

    def visibility(self, p: IdentityClaims):
        """Return a PRE-filter predicate over candidate chunks (chunk inherits document ACL)."""

        def _visible(c: Chunk) -> bool:
            return self.can_read(
                p,
                tenant_id=c.tenant_id,
                collection_id=c.collection_id,
                document_id=c.document_id,
            )

        return _visible

    def assert_visible(self, p: IdentityClaims, chunk: Chunk) -> None:
        """Double-defense post-check; fail-closed if anything unauthorized slipped through."""
        if not self.visibility(p)(chunk):
            raise AclDenied("post-check: unauthorized chunk in retrieval result")

    def can_read_document(self, p: IdentityClaims, doc: Document) -> bool:
        return self.can_read(
            p, tenant_id=doc.tenant_id, collection_id=doc.collection_id, document_id=doc.document_id
        )
