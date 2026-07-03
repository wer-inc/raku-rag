"""T021 — CacheService: retrieval/answer cache with invalidation (FR-008/045).

DeletionService delegates invalidation here so deleted documents can never reappear via a cached
answer (SC-003). Keyed by tenant_id; entries record the document_ids they depend on.

★G5: entries are LRU-bounded per tenant (``max_entries_per_tenant``) so long-lived populated caches
(e.g. the query-embedding cache) cannot grow without bound. ``get`` refreshes recency; ``put`` of a
new key evicts that tenant's least-recently-used entry once the cap is reached.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

DEFAULT_MAX_ENTRIES_PER_TENANT = 1000


@dataclass
class _Entry:
    value: object
    document_ids: frozenset[str]
    asset_ids: frozenset[str] = frozenset()
    crop_ids: frozenset[str] = frozenset()


@dataclass
class CacheService:
    # Insertion order doubles as recency order (LRU → MRU): ``get`` re-inserts on hit.
    _store: dict[tuple[str, str], _Entry] = field(default_factory=dict)
    # <= 0 disables the bound (not recommended outside tests).
    max_entries_per_tenant: int = DEFAULT_MAX_ENTRIES_PER_TENANT
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def get(self, tenant_id: str, key: str):
        with self._lock:
            entry = self._store.pop((tenant_id, key), None)
            if entry is None:
                return None
            # Re-insert to mark as most recently used.
            self._store[(tenant_id, key)] = entry
            return entry.value

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
        with self._lock:
            self._store.pop((tenant_id, key), None)
            if self.max_entries_per_tenant > 0:
                while self._tenant_entry_count(tenant_id) >= self.max_entries_per_tenant:
                    self._evict_lru(tenant_id)
            self._store[(tenant_id, key)] = _Entry(
                value,
                frozenset(document_ids),
                frozenset(asset_ids or set()),
                frozenset(crop_ids or set()),
            )

    def invalidate_document(self, tenant_id: str, document_id: str) -> int:
        with self._lock:
            to_del = [
                k
                for k, e in self._store.items()
                if k[0] == tenant_id and document_id in e.document_ids
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
        with self._lock:
            to_del = [
                k
                for k, e in self._store.items()
                if k[0] == tenant_id
                and ((assets and e.asset_ids & assets) or (crops and e.crop_ids & crops))
            ]
            for k in to_del:
                del self._store[k]
            return len(to_del)

    def _tenant_entry_count(self, tenant_id: str) -> int:
        return sum(1 for k in self._store if k[0] == tenant_id)

    def _evict_lru(self, tenant_id: str) -> None:
        for k in self._store:  # iteration order = LRU → MRU
            if k[0] == tenant_id:
                del self._store[k]
                return
