"""T033 — QueryProfile resolution (per collection, overridable per query) (FR-014a)."""

from __future__ import annotations

from raku_rag.domain.models import QueryProfile


class ProfileRegistry:
    def __init__(self, default: QueryProfile | None = None) -> None:
        self._default = default or QueryProfile()
        self._by_collection: dict[str, QueryProfile] = {}

    def set(self, collection_id: str, profile: QueryProfile) -> None:
        self._by_collection[collection_id] = profile

    def resolve(self, collection_id: str | None) -> QueryProfile:
        if collection_id and collection_id in self._by_collection:
            return self._by_collection[collection_id]
        return self._default
