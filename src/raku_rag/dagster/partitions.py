"""Dagster partition policy helpers.

Partition granularity is tenant / collection / source / sync_run. The helpers are plain strings so
online request paths never need Dagster imports to display or reason about run metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote


@dataclass(frozen=True)
class DagsterPartitionKey:
    tenant_id: str
    collection_id: str
    source_id: str
    sync_run_id: str

    def to_key(self) -> str:
        return build_partition_key(
            tenant_id=self.tenant_id,
            collection_id=self.collection_id,
            source_id=self.source_id,
            sync_run_id=self.sync_run_id,
        )

    def tags(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "collection_id": self.collection_id,
            "source_id": self.source_id,
            "sync_run_id": self.sync_run_id,
        }


def build_partition_key(
    *, tenant_id: str, collection_id: str, source_id: str, sync_run_id: str
) -> str:
    parts = (tenant_id, collection_id, source_id, sync_run_id)
    if any(not p for p in parts):
        raise ValueError("tenant_id, collection_id, source_id and sync_run_id are required")
    return "/".join(quote(p, safe="") for p in parts)


def parse_partition_key(key: str) -> DagsterPartitionKey:
    parts = key.split("/")
    if len(parts) != 4 or any(not p for p in parts):
        raise ValueError("partition key must be tenant/collection/source/sync_run")
    tenant_id, collection_id, source_id, sync_run_id = (unquote(p) for p in parts)
    return DagsterPartitionKey(
        tenant_id=tenant_id,
        collection_id=collection_id,
        source_id=source_id,
        sync_run_id=sync_run_id,
    )
