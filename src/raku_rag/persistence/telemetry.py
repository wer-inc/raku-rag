"""★G1 — Postgres sinks for per-query telemetry (goal.md §2-5 observability).

The ``cost_records`` and ``rerank_traces`` tables have existed since 0002 with RLS but had no
writer; ``query_traces`` (0022) persists the previously in-memory RagHotPathMetric. All three
follow the datasource/lexicon persistence precedent: every query runs after ``_use_tenant`` so
RLS enforces isolation even if a WHERE clause is wrong.

Telemetry persistence is fail-OPEN by contract: callers guard every ``record`` call so a sink
outage degrades to in-memory-only metrics and never breaks answering (unlike the audit sink,
which is part of the safety posture). Reference-only stance: identities stay hashed and no raw
query/answer/context text is ever written here. ★G3b adds ONE carefully-scoped exception: the
question text lands in ``query_traces.query_redacted`` (0024) because 未回答分析 needs to show
WHICH questions failed — but only after the observability Redactor masked PII (services/answer.py
redacts before the metric is even recorded, same stance as chatbot session transcripts).

★G3b/★G5 also add the read side: ``PostgresQueryTraceReader`` (SQL aggregation over
``query_traces`` after ``_use_tenant``) and ``InMemoryQueryTraceReader`` (same summary shape from
``MetricsRecorder.rag_hot_path_metrics()`` for the deterministic profile) power
``GET /internal/quality/operational`` — the 品質・KPI screen's 実測 p50/p95 / 未回答 drill-down.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

# 未回答 = any terminal status that did not produce a grounded answer. Kept in one place so the
# Postgres SQL and the in-memory reader classify identically.
_ANSWERED_STATUS = "ok"


def _percentile_cont(values, fraction: float) -> float:
    """Linear-interpolation percentile, matching Postgres ``percentile_cont`` semantics."""
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * fraction
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


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
                "profile_id, status, model, prompt_version, query_redacted, llm_call_count, "
                "retrieval_ms, rerank_ms, generation_ms, total_ms, retrieved_chunks, "
                "rerank_input_count, context_tokens, prompt_tokens, completion_tokens, cache_hit) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    f"qtr_{uuid.uuid4().hex}",
                    tenant_id,
                    metric.request_id,
                    metric.user_id_hash,
                    metric.profile_id,
                    metric.status,
                    getattr(metric, "model", ""),
                    getattr(metric, "prompt_version", ""),
                    # Already PII-redacted upstream (services/answer.py) — see module docstring.
                    getattr(metric, "query_redacted", ""),
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


class PostgresQueryTraceReader:
    """★G3b/★G5 read seam over ``query_traces`` for the 実測運用メトリクス card.

    Every query runs after ``_use_tenant`` (RLS pattern) so a wrong WHERE cannot leak another
    tenant's traces. Aggregation happens in SQL — the table is unbounded, only the refusal
    drill-down is row-limited.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    def operational_summary(self, tenant_id: str, *, limit: int = 20) -> dict:
        from raku_rag.persistence.postgres import _use_tenant

        limit = max(1, min(int(limit), 100))
        _use_tenant(self._conn, tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), "
                "COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY total_ms), 0), "
                "COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms), 0), "
                "COALESCE(avg(prompt_tokens + completion_tokens), 0) "
                "FROM query_traces WHERE tenant_id = %s",
                (tenant_id,),
            )
            query_count, p50_ms, p95_ms, avg_total_tokens = cur.fetchone()
            cur.execute(
                "SELECT status, count(*) FROM query_traces WHERE tenant_id = %s GROUP BY status",
                (tenant_id,),
            )
            status_counts = {str(status): int(n) for status, n in cur.fetchall()}
            cur.execute(
                "SELECT request_id, query_redacted, status, created_at "
                "FROM query_traces WHERE tenant_id = %s AND status <> %s "
                "ORDER BY created_at DESC, query_trace_id DESC LIMIT %s",
                (tenant_id, _ANSWERED_STATUS, limit),
            )
            refusals = [
                {
                    "request_id": request_id,
                    "query_redacted": query_redacted,
                    "status": status,
                    "created_at": (
                        created_at.isoformat()
                        if isinstance(created_at, datetime)
                        else str(created_at or "")
                    ),
                }
                for request_id, query_redacted, status, created_at in cur.fetchall()
            ]
        return _operational_summary_dict(
            query_count=int(query_count),
            p50_ms=float(p50_ms),
            p95_ms=float(p95_ms),
            avg_total_tokens=float(avg_total_tokens),
            status_counts=status_counts,
            recent_refusals=refusals,
        )


class InMemoryQueryTraceReader:
    """Deterministic-profile equivalent of PostgresQueryTraceReader (same summary shape).

    Reads ``MetricsRecorder.rag_hot_path_metrics()``; the metric stores ``tenant_id_hash`` (never
    the raw tenant), so filtering re-derives the hash with the same ``_identity_hash`` helper.
    In-memory metrics carry no timestamp, so ``created_at`` is empty in this profile.
    """

    def __init__(self, metrics) -> None:
        self._metrics = metrics

    def operational_summary(self, tenant_id: str, *, limit: int = 20) -> dict:
        from raku_rag.observability.metrics import _identity_hash

        limit = max(1, min(int(limit), 100))
        tenant_hash = _identity_hash(tenant_id)
        rows = [
            metric
            for metric in self._metrics.rag_hot_path_metrics()
            if metric.tenant_id_hash == tenant_hash
        ]
        status_counts: dict[str, int] = {}
        for metric in rows:
            status_counts[metric.status] = status_counts.get(metric.status, 0) + 1
        refusals = [
            {
                "request_id": metric.request_id,
                "query_redacted": getattr(metric, "query_redacted", ""),
                "status": metric.status,
                "created_at": "",
            }
            # Newest-first, matching the Postgres ORDER BY created_at DESC.
            for metric in reversed(rows)
            if metric.status != _ANSWERED_STATUS
        ][:limit]
        totals = [metric.total_ms for metric in rows]
        token_totals = [metric.prompt_tokens + metric.completion_tokens for metric in rows]
        return _operational_summary_dict(
            query_count=len(rows),
            p50_ms=_percentile_cont(totals, 0.5),
            p95_ms=_percentile_cont(totals, 0.95),
            avg_total_tokens=(sum(token_totals) / len(token_totals)) if token_totals else 0.0,
            status_counts=status_counts,
            recent_refusals=refusals,
        )


def _operational_summary_dict(
    *,
    query_count: int,
    p50_ms: float,
    p95_ms: float,
    avg_total_tokens: float,
    status_counts: dict,
    recent_refusals: list,
) -> dict:
    """One shape for both readers so the deterministic and Postgres profiles cannot drift."""
    insufficient = int(status_counts.get("insufficient_evidence", 0))
    return {
        "query_count": query_count,
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "avg_total_tokens": avg_total_tokens,
        "status_counts": status_counts,
        "insufficient_rate": (insufficient / query_count) if query_count else 0.0,
        "recent_refusals": recent_refusals,
    }


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
