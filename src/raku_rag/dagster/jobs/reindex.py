"""T046 — Dagster-compatible reindex backfill job boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from raku_rag.services.reindex import ReindexPlan, ReindexService


@dataclass(frozen=True)
class ReindexBackfillRequest:
    reindex_plan_id: str
    tenant_id: str
    collection_id: str
    document_ids: tuple[str, ...]
    reason: str
    target_embedding_model_version: str = ""
    dagster_tags: dict[str, str] = field(default_factory=dict)


def build_reindex_backfill_request(plan: ReindexPlan) -> ReindexBackfillRequest:
    document_ids = tuple(str(v) for v in plan.scope.get("document_ids", []))
    return ReindexBackfillRequest(
        reindex_plan_id=plan.reindex_plan_id,
        tenant_id=plan.tenant_id,
        collection_id=plan.collection_id,
        document_ids=document_ids,
        reason=plan.reason,
        target_embedding_model_version=plan.target_embedding_model_version,
        dagster_tags={
            "tenant_id": plan.tenant_id,
            "collection_id": plan.collection_id,
            "reindex_plan_id": plan.reindex_plan_id,
        },
    )


def execute_reindex_backfill(
    service: ReindexService,
    plan: ReindexPlan,
    *,
    documents: Mapping[str, bytes],
    content_type: str = "text/plain",
) -> ReindexPlan:
    """Execute a plan through the same service used by SQS/admin paths.

    A real Dagster op/asset can call this function from its executor without creating another reindex
    implementation.
    """

    return service.execute_plan(plan, documents=documents, content_type=content_type)
