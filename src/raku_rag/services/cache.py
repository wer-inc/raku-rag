"""T021 — CacheService: retrieval/answer cache with invalidation (FR-008/045).

DeletionService delegates invalidation here so deleted documents can never reappear via a cached
answer (SC-003). Keyed by tenant_id; entries record the document_ids they depend on.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _Entry:
    value: object
    document_ids: frozenset[str]
    asset_ids: frozenset[str] = frozenset()
    crop_ids: frozenset[str] = frozenset()


@dataclass
class CacheService:
    _store: dict[tuple[str, str], _Entry] = field(default_factory=dict)

    def get(self, tenant_id: str, key: str):
        entry = self._store.get((tenant_id, key))
        return entry.value if entry else None

    def put(
        self,
        tenant_id: str,
        key: str,
        value: object,
        document_ids: set[str],
        *,
        asset_ids: set[str] | None = None,
        crop_ids: set[str] | None = None,
    ) -> None:
        self._store[(tenant_id, key)] = _Entry(
            value,
            frozenset(document_ids),
            frozenset(asset_ids or set()),
            frozenset(crop_ids or set()),
        )

    def invalidate_document(self, tenant_id: str, document_id: str) -> int:
        to_del = [
            k for k, e in self._store.items() if k[0] == tenant_id and document_id in e.document_ids
        ]
        for k in to_del:
            del self._store[k]
        return len(to_del)

    def invalidate_visual_artifacts(
        self,
        tenant_id: str,
        *,
        asset_ids: set[str] | None = None,
        crop_ids: set[str] | None = None,
    ) -> int:
        assets = frozenset(asset_ids or set())
        crops = frozenset(crop_ids or set())
        to_del = [
            k
            for k, e in self._store.items()
            if k[0] == tenant_id
            and ((assets and e.asset_ids & assets) or (crops and e.crop_ids & crops))
        ]
        for k in to_del:
            del self._store[k]
        return len(to_del)
