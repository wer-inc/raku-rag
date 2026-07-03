"""★G1 — Postgres sinks for per-query telemetry (goal.md §2-5 observability).

The ``cost_records`` and ``rerank_traces`` tables have existed since 0002 with RLS but had no
writer; ``query_traces`` (0022) persists the previously in-memory RagHotPathMetric. All three
follow the datasource/lexicon persistence precedent: every query runs after ``_use_tenant`` so
RLS enforces isolation even if a WHERE clause is wrong.

Telemetry persistence is fail-OPEN by contract: callers guard every ``record`` call so a sink
outage degrades to in-memory-only metrics and never breaks answering (unlike the audit sink,
which is part of the safety posture). Reference-only stance: no raw query/answer/context text
is ever written here.
"""

from __future__ import annotations

import json
import uuid


def cost_record_scope(record) -> tuple[str, str]:
    """Map a CostRecord to the cost_records (scope_type, scope_id) columns.

    Most-specific wins; falls back to the tenant scope so every record lands somewhere queryable.
    """
    if getattr(record, "query_id", ""):
        return ("query", record.query_id)
    if getattr(record, "job_id", ""):
        return ("job", record.job_id)
    if getattr(record, "collection_id", ""):
        return ("collection", record.collection_id)
    return ("tenant", record.tenant_id)


class PostgresCostRecordSink:
    """Write-through sink for CostService: one row per CostRecord in ``cost_records``."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def record(self, record) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        scope_type, scope_id = cost_record_scope(record)
        metadata = dict(record.metadata or {})
        # billable / narrower scopes have no dedicated columns; keep them queryable in metadata.
        metadata.setdefault("billable", bool(record.billable))
        if record.collection_id:
            metadata.setdefault("collection_id", record.collection_id)
        _use_tenant(self._conn, record.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (record.tenant_id,),
            )
            cur.execute(
                "INSERT INTO cost_records (cost_record_id, tenant_id, scope_type, scope_id, "
                "kind, amount, quantity, unit, trace_id, metadata, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
                (
                    f"cost_{uuid.uuid4().hex}",
                    record.tenant_id,
                    scope_type,
                    scope_id,
                    record.kind,
                    record.amount,
                    record.quantity,
                    record.unit,
                    record.trace_id,
                    json.dumps(metadata),
                    record.created_at,
                ),
            )


class PostgresQueryTraceSink:
    """Durable per-query hot-path trace: one row per RagHotPathMetric in ``query_traces``."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def record(self, tenant_id: str, metric) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (tenant_id,),
            )
            cur.execute(
                "INSERT INTO query_traces (query_trace_id, tenant_id, request_id, user_id_hash, "
                "profile_id, status, model, prompt_version, llm_call_count, retrieval_ms, "
                "rerank_ms, generation_ms, total_ms, retrieved_chunks, rerank_input_count, "
                "context_tokens, prompt_tokens, completion_tokens, cache_hit) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    f"qtr_{uuid.uuid4().hex}",
                    tenant_id,
                    metric.request_id,
                    metric.user_id_hash,
                    metric.profile_id,
                    metric.status,
                    getattr(metric, "model", ""),
                    getattr(metric, "prompt_version", ""),
                    metric.llm_call_count,
                    metric.retrieval_ms,
                    metric.rerank_ms,
                    metric.generation_ms,
                    metric.total_ms,
                    metric.retrieved_chunks,
                    metric.rerank_input_count,
                    metric.context_tokens,
                    metric.prompt_tokens,
                    metric.completion_tokens,
                    metric.cache_hit,
                ),
            )


class PostgresRerankTraceSink:
    """One row per executed rerank in ``rerank_traces`` (skipped reranks are not recorded)."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def record(
        self,
        *,
        tenant_id: str,
        query_id: str,
        retrieval_profile_id: str,
        provider: str,
        model: str,
        candidate_count: int,
        final_context_count: int,
        latency_ms: float,
        cost_amount: float = 0.0,
    ) -> None:
        from raku_rag.persistence.postgres import _use_tenant

        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (tenant_id,),
            )
            cur.execute(
                "INSERT INTO rerank_traces (rerank_trace_id, tenant_id, query_id, "
                "retrieval_profile_id, provider, model, candidate_count, final_context_count, "
                "latency_ms, cost_amount) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    f"rrt_{uuid.uuid4().hex}",
                    tenant_id,
                    query_id,
                    retrieval_profile_id,
                    provider,
                    model,
                    candidate_count,
                    final_context_count,
                    latency_ms,
                    cost_amount,
                ),
            )
