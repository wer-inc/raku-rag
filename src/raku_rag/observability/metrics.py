"""T016/T034/T060 - minimal in-memory metrics boundary."""

from __future__ import annotations

import hashlib
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


def _identity_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


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


@dataclass(frozen=True)
class RagHotPathMetric:
    request_id: str
    tenant_id_hash: str
    user_id_hash: str
    profile_id: str
    status: str
    llm_call_count: int
    retrieval_ms: float
    rerank_ms: float
    generation_ms: float
    total_ms: float
    retrieved_chunks: int
    rerank_input_count: int
    context_tokens: int
    prompt_tokens: int
    completion_tokens: int
    cache_hit: bool

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "tenant_id_hash": self.tenant_id_hash,
            "user_id_hash": self.user_id_hash,
            "profile_id": self.profile_id,
            "status": self.status,
            "llm_call_count": self.llm_call_count,
            "retrieval_ms": self.retrieval_ms,
            "rerank_ms": self.rerank_ms,
            "generation_ms": self.generation_ms,
            "total_ms": self.total_ms,
            "retrieved_chunks": self.retrieved_chunks,
            "rerank_input_count": self.rerank_input_count,
            "context_tokens": self.context_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cache_hit": self.cache_hit,
        }


@dataclass
class MetricsRecorder:
    _counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = field(default_factory=dict)
    _observations: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = field(
        default_factory=dict
    )
    _rag_hot_paths: list[RagHotPathMetric] = field(default_factory=list)

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

    def record_rag_hot_path(
        self,
        *,
        request_id: str,
        tenant_id: str,
        user_id: str,
        profile_id: str,
        status: str,
        llm_call_count: int = 0,
        retrieval_ms: float = 0.0,
        rerank_ms: float = 0.0,
        generation_ms: float = 0.0,
        total_ms: float = 0.0,
        retrieved_chunks: int = 0,
        rerank_input_count: int = 0,
        context_tokens: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_hit: bool = False,
    ) -> RagHotPathMetric:
        """Record request-level RAG latency/count/token metrics without raw identities."""
        metric = RagHotPathMetric(
            request_id=request_id,
            tenant_id_hash=_identity_hash(tenant_id),
            user_id_hash=_identity_hash(user_id),
            profile_id=profile_id,
            status=status,
            llm_call_count=max(0, int(llm_call_count)),
            retrieval_ms=max(0.0, float(retrieval_ms)),
            rerank_ms=max(0.0, float(rerank_ms)),
            generation_ms=max(0.0, float(generation_ms)),
            total_ms=max(0.0, float(total_ms)),
            retrieved_chunks=max(0, int(retrieved_chunks)),
            rerank_input_count=max(0, int(rerank_input_count)),
            context_tokens=max(0, int(context_tokens)),
            prompt_tokens=max(0, int(prompt_tokens)),
            completion_tokens=max(0, int(completion_tokens)),
            cache_hit=bool(cache_hit),
        )
        self._rag_hot_paths.append(metric)
        labels = {
            "tenant_id_hash": metric.tenant_id_hash,
            "profile_id": profile_id,
            "status": status,
            "cache_hit": "true" if metric.cache_hit else "false",
        }
        self.increment("rag_requests_total", labels=labels)
        self.observe("rag_request_total_ms", metric.total_ms, labels=labels)
        self.observe("rag_retrieval_ms", metric.retrieval_ms, labels=labels)
        self.observe("rag_rerank_ms", metric.rerank_ms, labels=labels)
        self.observe("rag_generation_ms", metric.generation_ms, labels=labels)
        self.observe("rag_llm_call_count", metric.llm_call_count, labels=labels)
        self.observe("rag_retrieved_chunks", metric.retrieved_chunks, labels=labels)
        self.observe("rag_rerank_input_count", metric.rerank_input_count, labels=labels)
        self.observe("rag_context_tokens", metric.context_tokens, labels=labels)
        self.observe("rag_prompt_tokens", metric.prompt_tokens, labels=labels)
        self.observe("rag_completion_tokens", metric.completion_tokens, labels=labels)
        return metric

    def rag_hot_path_metrics(self, request_id: str = "") -> tuple[RagHotPathMetric, ...]:
        if request_id:
            return tuple(metric for metric in self._rag_hot_paths if metric.request_id == request_id)
        return tuple(self._rag_hot_paths)

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
