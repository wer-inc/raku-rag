"""T016/T034/T060 - minimal in-memory metrics boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

OBSERVABILITY_STAGES: tuple[str, ...] = ("ingestion", "retrieval", "generation", "evaluation")
_OK_STATUSES = {"ok", "succeeded", "skipped"}


def _label_key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((labels or {}).items()))


def _p95(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95))))
    return float(ordered[index])


@dataclass(frozen=True)
class StageMetrics:
    stage: str
    throughput: float
    error_count: float
    error_rate: float
    p95_latency_ms: float
    cost_total: float

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "throughput": self.throughput,
            "error_count": self.error_count,
            "error_rate": self.error_rate,
            "p95_latency_ms": self.p95_latency_ms,
            "cost_total": self.cost_total,
        }


@dataclass
class MetricsRecorder:
    _counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = field(default_factory=dict)
    _observations: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = field(
        default_factory=dict
    )

    def increment(
        self, name: str, value: float = 1.0, *, labels: dict[str, str] | None = None
    ) -> None:
        key = (name, _label_key(labels))
        self._counters[key] = self._counters.get(key, 0.0) + value

    def observe(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        self._observations.setdefault((name, _label_key(labels)), []).append(value)

    def counter(self, name: str, *, labels: dict[str, str] | None = None) -> float:
        return self._counters.get((name, _label_key(labels)), 0.0)

    def observations(self, name: str, *, labels: dict[str, str] | None = None) -> tuple[float, ...]:
        return tuple(self._observations.get((name, _label_key(labels)), ()))

    def record_stage(
        self,
        stage: str,
        *,
        tenant_id: str,
        status: str = "ok",
        latency_ms: float = 0.0,
        cost: float = 0.0,
    ) -> None:
        """Record the canonical dashboard dimensions for a pipeline stage."""
        if stage not in OBSERVABILITY_STAGES:
            raise ValueError(f"unknown observability stage: {stage}")
        stage_labels = {"tenant_id": tenant_id, "stage": stage}
        status_labels = {**stage_labels, "status": status}
        self.increment("rag_stage_throughput_total", labels=status_labels)
        self.observe("rag_stage_latency_ms", max(0.0, latency_ms), labels=stage_labels)
        if status not in _OK_STATUSES:
            self.increment("rag_stage_errors_total", labels=status_labels)
        if cost:
            self.increment("rag_stage_cost_total", max(0.0, cost), labels=stage_labels)

    def stage_summary(self, tenant_id: str, stage: str) -> StageMetrics:
        if stage not in OBSERVABILITY_STAGES:
            raise ValueError(f"unknown observability stage: {stage}")
        labels = {"tenant_id": tenant_id, "stage": stage}
        throughput = self._counter_sum("rag_stage_throughput_total", labels)
        errors = self._counter_sum("rag_stage_errors_total", labels)
        return StageMetrics(
            stage=stage,
            throughput=throughput,
            error_count=errors,
            error_rate=(errors / throughput) if throughput else 0.0,
            p95_latency_ms=_p95(self.observations("rag_stage_latency_ms", labels=labels)),
            cost_total=self._counter_sum("rag_stage_cost_total", labels),
        )

    def dashboard_snapshot(self, tenant_id: str) -> tuple[StageMetrics, ...]:
        return tuple(self.stage_summary(tenant_id, stage) for stage in OBSERVABILITY_STAGES)

    def _counter_sum(self, name: str, required_labels: dict[str, str]) -> float:
        total = 0.0
        for (metric_name, label_items), value in self._counters.items():
            if metric_name != name:
                continue
            labels = dict(label_items)
            if all(labels.get(k) == v for k, v in required_labels.items()):
                total += value
        return total
