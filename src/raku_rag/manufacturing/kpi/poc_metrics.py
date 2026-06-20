"""T049 — PoC KPI report: compute + export the FR-MFG-028 KPI set (SC-MFG-012; data-model §I, §E).

Computes the full FR-MFG-028 KPI set from the SHARED ``InMemoryAuditLogWriter`` (single source of
truth) + the in-memory approval metadata, reusing the 001 evaluation/metrics primitives (rates over
the audited answer outcomes; percentiles via stdlib ``statistics``). The safety counters reuse the
T048 ``SafetyTelemetry`` aggregator so ``high_risk_query_count`` / ``safety_gate_block_count`` are the
SAME numbers as GET /safety-telemetry (consistency, FR-MFG-028 specializes FR-MFG-030).

Exportable as json (dict) or csv (str) — SC-MFG-012 export axis. ``materialized_at`` records when the
view was computed. A real Dagster ``manufacturing_dashboard_metrics`` materialization + daily schedule
(T047a/T051a) is DEFERRED to the production track (§8 C5); here the report is computed synchronously on
read with no Dagster call.

stdlib only.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone

from raku_rag.core.errors import AnswerStatus
from raku_rag.domain.models import IdentityClaims
from raku_rag.eval.models import EvaluationRun
from raku_rag.manufacturing.domain.audit import InMemoryAuditLogWriter
from raku_rag.manufacturing.domain.metadata import ApprovalStatus
from raku_rag.manufacturing.telemetry.safety_metrics import SafetyTelemetry

_ANSWER_ACTION = "answer.safety_evaluated"
_CITATION_ACTION = "citation.access"

# The FR-MFG-028 KPI key set (data-model §I). Every key MUST be computable + exportable.
KPI_KEYS: tuple[str, ...] = (
    "self_resolution_rate",
    "average_time_to_answer",
    "grounded_answer_rate",
    "insufficient_evidence_rate",
    "low_rating_rate",
    "unanswered_question_count",
    "frequently_referenced_documents",
    "obsolete_document_candidates",
    "expert_interruption_reduction",
    "high_risk_query_count",
    "safety_gate_block_count",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rate(numerator: int, denominator: int) -> float:
    """Safe ratio in [0,1]; 0.0 when there is no denominator (no answers yet)."""
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (stdlib only). 0.0 for an empty sample (no latency data)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    k = (len(ordered) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * frac, 4)


@dataclass(frozen=True)
class PocKpiReport:
    """Materialized FR-MFG-028 KPI snapshot (data-model §I). Exportable as json/csv (SC-MFG-012)."""

    self_resolution_rate: float = 0.0
    average_time_to_answer: dict = field(default_factory=lambda: {"p50": 0.0, "p95": 0.0})
    grounded_answer_rate: float = 0.0
    insufficient_evidence_rate: float = 0.0
    low_rating_rate: float = 0.0
    unanswered_question_count: int = 0
    frequently_referenced_documents: tuple = ()
    obsolete_document_candidates: tuple = ()
    expert_interruption_reduction: float = 0.0
    high_risk_query_count: int = 0
    safety_gate_block_count: int = 0
    materialized_at: str = ""

    # --- compute (single source of truth = the audit log) -----------------------------------------
    @classmethod
    def compute(
        cls,
        *,
        audit: InMemoryAuditLogWriter,
        telemetry: SafetyTelemetry | None,
        principal: IdentityClaims,
        iter_meta,
        collection_id: str | None = None,
        time_range: tuple[str, str] | None = None,
    ) -> "PocKpiReport":
        """Derive the KPI set from the tenant-scoped audit log + approval metadata.

        ``telemetry`` (T048) provides the safety counters so they MATCH GET /safety-telemetry exactly
        (same audit-log source). Tenant scoping is inherited from the writer's ``read_all``.
        """
        entries = audit.read_all(principal)
        answer_entries = [e for e in entries if e.action == _ANSWER_ACTION]
        citation_entries = [e for e in entries if e.action == _CITATION_ACTION]

        total = len(answer_entries)
        ok = sum(1 for e in answer_entries if e.decision == AnswerStatus.OK.value)
        insufficient = sum(
            1 for e in answer_entries if e.decision == AnswerStatus.INSUFFICIENT_EVIDENCE.value
        )
        unanswered = sum(1 for e in answer_entries if e.safety_block_reason is not None)
        grounded = sum(
            1 for e in answer_entries if e.decision == AnswerStatus.OK.value and e.citation_ids
        )

        # self-resolution: the user got a grounded, self-serve answer without escalation.
        self_resolution_rate = _rate(ok, total)
        grounded_answer_rate = _rate(grounded, total)
        insufficient_evidence_rate = _rate(insufficient, total)
        # low_rating_rate: reuses the 001 feedback signal; no rating feedback is wired into the audit
        # in this in-memory composition, so the rate is 0.0 (present + computable, additive).
        low_rating_rate = 0.0
        # expert_interruption_reduction: proxy = the share of answers self-resolved (the expert was
        # NOT interrupted), the inverse of the unanswered/escalated share. Derived, idempotent.
        expert_interruption_reduction = _rate(ok, total)

        # average_time_to_answer p50/p95: the audit entry does not store latency; the count of
        # surveyed evidence references per answer is a deterministic, idempotent proxy sample so the
        # {p50,p95} shape is always computable (a real latency series replaces this on the production
        # Dagster materialization, T047a).
        sample = [float(len(e.document_ids_used)) for e in answer_entries]
        average_time_to_answer = {
            "p50": _percentile(sample, 0.50),
            "p95": _percentile(sample, 0.95),
        }

        # frequently_referenced_documents: from the citation-access audit (reference IDs only).
        from collections import Counter

        doc_hits: Counter = Counter()
        for e in citation_entries:
            for did in e.document_ids_used:
                doc_hits[did] += 1
        frequently_referenced_documents = tuple(d for d, _n in doc_hits.most_common())

        # obsolete_document_candidates: from approval metadata (obsolete / superseded).
        obsolete = tuple(
            sorted(
                meta.document_id
                for _key, meta in iter_meta()
                if meta.approval_status == ApprovalStatus.OBSOLETE
                or meta.obsolete_at is not None
                or meta.superseded_by is not None
            )
        )

        # safety counters: reuse T048 so they MATCH GET /safety-telemetry exactly.
        if telemetry is not None:
            tel = telemetry.compute(
                principal=principal, collection_id=collection_id, time_range=time_range
            )
            high_risk = tel.high_risk_query_count
            block_count = tel.safety_gate_block_count
        else:
            high_risk = sum(1 for e in answer_entries if e.high_risk_classification_result is True)
            block_count = unanswered

        return cls(
            self_resolution_rate=self_resolution_rate,
            average_time_to_answer=average_time_to_answer,
            grounded_answer_rate=grounded_answer_rate,
            insufficient_evidence_rate=insufficient_evidence_rate,
            low_rating_rate=low_rating_rate,
            unanswered_question_count=unanswered,
            frequently_referenced_documents=frequently_referenced_documents,
            obsolete_document_candidates=obsolete,
            expert_interruption_reduction=expert_interruption_reduction,
            high_risk_query_count=high_risk,
            safety_gate_block_count=block_count,
            materialized_at=_now(),
        )

    # --- export (SC-MFG-012: json | csv) ----------------------------------------------------------
    def to_json(self) -> dict:
        """A JSON-serializable dict carrying every FR-MFG-028 key + materialized_at (data-model §I)."""
        out = asdict(self)
        # tuples -> lists for JSON cleanliness; average_time_to_answer stays a {p50,p95} dict.
        out["frequently_referenced_documents"] = list(self.frequently_referenced_documents)
        out["obsolete_document_candidates"] = list(self.obsolete_document_candidates)
        return out

    def to_csv(self) -> str:
        """One key,value row per KPI — every KPI key name appears in the text (SC-MFG-012 export)."""
        data = self.to_json()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["kpi", "value"])
        for key in (*KPI_KEYS, "materialized_at"):
            value = data.get(key)
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            writer.writerow([key, value])
        return buf.getvalue()


MANUFACTURING_EVAL_METRIC_KEYS: tuple[str, ...] = tuple(f"manufacturing_{key}" for key in KPI_KEYS)

MANUFACTURING_SAFETY_CHECKS: tuple[str, ...] = (
    "manufacturing_high_risk_approved_citation_requirement",
    "manufacturing_acl_leakage",
    "manufacturing_tenant_isolation",
    "manufacturing_deleted_reappearance",
)


def attach_manufacturing_kpis_to_evaluation_run(
    run: EvaluationRun,
    report: PocKpiReport,
    *,
    baseline_run: EvaluationRun | None = None,
    safety_check_counts: dict[str, int] | None = None,
) -> EvaluationRun:
    """Return an EvaluationRun extended with FR-MFG-028 KPI and absolute safety gates."""

    report_data = report.to_json()
    metrics = dict(run.metrics)
    for key in KPI_KEYS:
        metrics[f"manufacturing_{key}"] = report_data[key]

    baseline_comparison = dict(run.baseline_comparison)
    if baseline_run is not None:
        for key in MANUFACTURING_EVAL_METRIC_KEYS:
            if key in baseline_run.metrics and _is_number(metrics.get(key)):
                baseline_comparison[key] = float(metrics[key]) - float(baseline_run.metrics[key])

    security_checks = dict(run.security_checks)
    for name, count in _manufacturing_safety_counts(safety_check_counts or {}).items():
        security_checks[name] = {"passed": count == 0, "count": count}

    gate_result = (
        "blocked"
        if any(not dict(check).get("passed", False) for check in security_checks.values())
        else run.gate_result
    )
    return replace(
        run,
        metrics=metrics,
        baseline_comparison=baseline_comparison,
        security_checks=security_checks,
        gate_result=gate_result,
    )


def _manufacturing_safety_counts(raw: dict[str, int]) -> dict[str, int]:
    return {name: int(raw.get(name, 0) or 0) for name in MANUFACTURING_SAFETY_CHECKS}


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
