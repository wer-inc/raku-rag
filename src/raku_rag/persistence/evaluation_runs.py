"""P2-9 — persist evaluation runs to the ``evaluation_runs`` table so eval results are trendable.

``InMemoryEvaluationRunRepository`` (default, Tier A) and ``PostgresEvaluationRunRepository`` (Tier B)
share the same row codec. The repository stores the SERIALIZED row and reconstructs the run on read,
so a no-op/echo implementation cannot pass the round-trip tests. Per-item ``examples`` are
intentionally NOT persisted (the table is for metric/gate/provenance trending, not per-item replay).

psycopg is imported lazily inside the Postgres adapter only, so this module imports cleanly under the
stdlib-only Tier A gate.
"""

from __future__ import annotations

import json

from raku_rag.eval.models import EvaluationRun

# Columns persisted to evaluation_runs (0002 base + 0007 additions). `examples` is deliberately omitted.
PERSISTED_FIELDS = (
    "evaluation_run_id",
    "tenant_id",
    "collection_id",
    "eval_set_id",
    "status",
    "baseline",
    "metrics",
    "security_checks",
    "baseline_comparison",
    "gate_result",
    "probe_results",
    "probes_executed",
    "created_at",
)


def evaluation_run_to_row(run: EvaluationRun) -> dict:
    """Serialize an EvaluationRun to a table-row dict (jsonb columns as plain dict/list)."""
    return {
        "evaluation_run_id": run.run_id,
        "tenant_id": run.tenant_id,
        "collection_id": None,  # EvaluationRun has no collection scope; column stays nullable
        "eval_set_id": run.eval_set_id,
        "status": run.status,
        "baseline": bool(run.baseline),
        "metrics": dict(run.metrics),
        "security_checks": dict(run.security_checks),
        "baseline_comparison": dict(run.baseline_comparison),
        "gate_result": run.gate_result,
        "probe_results": [dict(result) for result in run.probe_results],
        "probes_executed": bool(run.probes_executed),
        "created_at": run.created_at,
    }


def row_to_evaluation_run(row: dict) -> EvaluationRun:
    """Reconstruct an EvaluationRun from a stored row (examples are not persisted → empty)."""
    return EvaluationRun(
        run_id=row["evaluation_run_id"],
        eval_set_id=row.get("eval_set_id") or "",
        tenant_id=row["tenant_id"],
        status=row.get("status") or "succeeded",
        baseline=bool(row.get("baseline", False)),
        metrics=dict(row.get("metrics") or {}),
        baseline_comparison=dict(row.get("baseline_comparison") or {}),
        security_checks=dict(row.get("security_checks") or {}),
        gate_result=row.get("gate_result") or "passed",
        examples=(),
        probe_results=tuple(dict(result) for result in (row.get("probe_results") or ())),
        probes_executed=bool(row.get("probes_executed", False)),
        created_at=row.get("created_at") or "",
    )


class InMemoryEvaluationRunRepository:
    """Default Tier-A repository. Stores the serialized row (not the live object) so read-back is a
    genuine round-trip through the row codec — a no-op/echo cannot satisfy the tests."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], dict] = {}

    def save(self, run: EvaluationRun) -> str:
        # json round-trip => a deep, reference-free copy of the serialized row.
        row = json.loads(json.dumps(evaluation_run_to_row(run)))
        self._rows[(run.tenant_id, run.run_id)] = row
        return run.run_id

    def get(self, tenant_id: str, run_id: str) -> EvaluationRun | None:
        row = self._rows.get((tenant_id, run_id))
        return row_to_evaluation_run(row) if row is not None else None

    def list_runs(self, tenant_id: str, eval_set_id: str | None = None) -> list[EvaluationRun]:
        rows = [
            row
            for (t, _), row in self._rows.items()
            if t == tenant_id and (eval_set_id is None or row.get("eval_set_id") == eval_set_id)
        ]
        # Chronological (created_at ISO string sorts lexically) for trend reading; run_id tiebreak.
        rows.sort(key=lambda r: (r.get("created_at") or "", r.get("evaluation_run_id") or ""))
        return [row_to_evaluation_run(row) for row in rows]


class PostgresEvaluationRunRepository:
    """Postgres-backed repository targeting the RLS-scoped ``evaluation_runs`` table (Tier B).

    Same surface + codec as the in-memory repo; RLS applies via the session tenant on every op.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    def _use_tenant(self, tenant_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (tenant_id,))

    def save(self, run: EvaluationRun) -> str:
        from psycopg.types.json import Json

        row = evaluation_run_to_row(run)
        self._use_tenant(run.tenant_id)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO evaluation_runs (evaluation_run_id, tenant_id, collection_id, "
                "eval_set_id, status, baseline, metrics, security_checks, baseline_comparison, "
                "gate_result, probe_results, probes_executed) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (evaluation_run_id) DO UPDATE SET "
                "metrics=EXCLUDED.metrics, security_checks=EXCLUDED.security_checks, "
                "baseline_comparison=EXCLUDED.baseline_comparison, gate_result=EXCLUDED.gate_result, "
                "probe_results=EXCLUDED.probe_results, probes_executed=EXCLUDED.probes_executed, "
                "status=EXCLUDED.status, baseline=EXCLUDED.baseline, eval_set_id=EXCLUDED.eval_set_id, "
                "updated_at=now()",
                (
                    row["evaluation_run_id"],
                    row["tenant_id"],
                    row["collection_id"],
                    row["eval_set_id"],
                    row["status"],
                    row["baseline"],
                    Json(row["metrics"]),
                    Json(row["security_checks"]),
                    Json(row["baseline_comparison"]),
                    row["gate_result"],
                    Json(row["probe_results"]),
                    row["probes_executed"],
                ),
            )
        return run.run_id

    def _select(self, where_sql: str, params: tuple):
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT evaluation_run_id, tenant_id, collection_id, eval_set_id, status, baseline, "
                "metrics, security_checks, baseline_comparison, gate_result, probe_results, "
                "probes_executed, created_at FROM evaluation_runs " + where_sql,
                params,
            )
            return cur.fetchall()

    @staticmethod
    def _row(record) -> dict:
        created = record[12]
        return {
            "evaluation_run_id": record[0],
            "tenant_id": record[1],
            "collection_id": record[2],
            "eval_set_id": record[3],
            "status": record[4],
            "baseline": record[5],
            "metrics": record[6] or {},
            "security_checks": record[7] or {},
            "baseline_comparison": record[8] or {},
            "gate_result": record[9],
            "probe_results": record[10] or [],
            "probes_executed": record[11],
            "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
        }

    def get(self, tenant_id: str, run_id: str) -> EvaluationRun | None:
        self._use_tenant(tenant_id)
        rows = self._select("WHERE evaluation_run_id = %s", (run_id,))
        return row_to_evaluation_run(self._row(rows[0])) if rows else None

    def list_runs(self, tenant_id: str, eval_set_id: str | None = None) -> list[EvaluationRun]:
        self._use_tenant(tenant_id)
        if eval_set_id is None:
            rows = self._select("ORDER BY created_at, evaluation_run_id", ())
        else:
            rows = self._select(
                "WHERE eval_set_id = %s ORDER BY created_at, evaluation_run_id", (eval_set_id,)
            )
        return [row_to_evaluation_run(self._row(record)) for record in rows]


__all__ = [
    "PERSISTED_FIELDS",
    "InMemoryEvaluationRunRepository",
    "PostgresEvaluationRunRepository",
    "evaluation_run_to_row",
    "row_to_evaluation_run",
]
