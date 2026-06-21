"""T057/T079 - text and visual evaluation runner with absolute security hard gates."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from raku_rag.core.text import content_terms
from raku_rag.domain.models import BoundingBox, Chunk, Citation, IdentityClaims, Modality
from raku_rag.eval.models import (
    EvaluationExampleResult,
    ExpectedEvidence,
    EvaluationRun,
    EvaluationSet,
    _stable_id,
)
from raku_rag.eval.probes import SecurityProbeSuite

SECURITY_CHECKS = (
    "acl_leakage",
    "deleted_reappearance",
    "tenant_isolation",
    "unauthorized_context",
    "prompt_injection",
    "source_poisoning",  # release-blocking since GAP-S3/PR-016 fix (manufacturing/api/answer_ext.py)
    "visual_acl_leakage",
    "visual_deleted_reappearance",
    "visual_unauthorized_context",
    "visual_thumbnail_crop_leakage",
)


@dataclass(frozen=True)
class SecurityCheck:
    passed: bool
    count: int = 0

    def to_dict(self) -> dict:
        return {"passed": self.passed, "count": self.count}


class EvaluationRunner:
    def __init__(
        self, system, *, probe_suite: SecurityProbeSuite | None = None, run_repository=None
    ) -> None:
        self.system = system
        # The gate's security signal is COMPUTED by probes every run (P0-1); the suite runs by
        # default so production callers (answer-service, dagster) get real counts without changes.
        self.probe_suite = probe_suite if probe_suite is not None else SecurityProbeSuite()
        # Optional persistence (P2-9). Default None → existing behavior unchanged; when a repository
        # is supplied the completed run is persisted (metrics/security/baseline/gate/provenance) so
        # results are trendable across releases. Any object with .save(run) works (in-memory/Postgres).
        self.run_repository = run_repository

    def run(
        self,
        eval_set: EvaluationSet,
        *,
        principal: IdentityClaims,
        collection_id: str | None = None,
        baseline: bool = False,
        baseline_run: EvaluationRun | None = None,
        security_check_counts: dict[str, int] | None = None,
    ) -> EvaluationRun:
        examples: list[EvaluationExampleResult] = []
        recall_hits = 0
        citation_hits = 0
        grounded_hits = 0
        precision_sum = 0.0
        rr_sum = 0.0
        gradeable = 0
        faithful_sum = 0.0
        faithful_gradeable = 0
        visual_recall_hits = 0
        visual_citation_hits = 0
        visual_grounded_hits = 0
        bbox_scores: list[float] = []
        visual_latencies: list[float] = []
        visual_cost = 0.0
        total_cost = 0.0

        for item in eval_set.items:
            expected_docs = {e.document_id for e in item.expected_evidence if e.document_id}
            expected_visual = tuple(e for e in item.expected_evidence if _is_visual_expected(e))
            started = perf_counter()
            retrieved = self.system.search(principal, item.question, collection_id)
            answer = self.system.answer(principal, item.question, collection_id)
            latency_ms = (perf_counter() - started) * 1000
            retrieved_docs = tuple(dict.fromkeys(result.chunk.document_id for result in retrieved))
            cited_docs = tuple(dict.fromkeys(c.document_id for c in answer.citations))
            retrieved_assets = tuple(
                dict.fromkeys(
                    str(result.chunk.metadata.get("asset_id", ""))
                    for result in retrieved
                    if _is_visual_chunk(result.chunk) and result.chunk.metadata.get("asset_id")
                )
            )
            cited_assets = tuple(
                dict.fromkeys(
                    c.asset_id for c in answer.citations if c.kind == "visual" and c.asset_id
                )
            )
            retrieved_regions = tuple(
                dict.fromkeys(
                    str(result.chunk.metadata.get("region_id", ""))
                    for result in retrieved
                    if _is_visual_chunk(result.chunk) and result.chunk.metadata.get("region_id")
                )
            )
            cited_regions = tuple(
                dict.fromkeys(
                    c.region_id for c in answer.citations if c.kind == "visual" and c.region_id
                )
            )
            if expected_docs and expected_docs.intersection(retrieved_docs):
                recall_hits += 1
            if expected_docs and expected_docs.intersection(cited_docs):
                citation_hits += 1
            if answer.status == "ok" and answer.citations and answer.used_chunks:
                grounded_hits += 1
            if answer.status == "ok" and answer.text and answer.used_chunks:
                # Deterministic faithfulness: fraction of the asserted answer's content-terms that are
                # actually supported by the cited/used evidence text (stronger than the structural
                # groundedness proxy; catches a plausibly-worded unsupported answer from a real LLM).
                used_ids = set(answer.used_chunks)
                evidence_text = " ".join(
                    result.chunk.text for result in retrieved if result.chunk.chunk_id in used_ids
                )
                faithful_gradeable += 1
                faithful_sum += _term_support(answer.text, evidence_text)
            if expected_docs:
                # precision@k and MRR over the (ranked, deduped) retrieved docs — graded over items
                # that carry expected evidence (recall_at_k stays a per-item hit-rate for continuity).
                gradeable += 1
                relevant_retrieved = expected_docs.intersection(retrieved_docs)
                precision_sum += (
                    len(relevant_retrieved) / len(retrieved_docs) if retrieved_docs else 0.0
                )
                rank = next((i + 1 for i, d in enumerate(retrieved_docs) if d in expected_docs), 0)
                rr_sum += (1.0 / rank) if rank else 0.0
            query_cost = float(answer.cost.get("amount", 0.0)) if answer.cost else 0.0
            total_cost += query_cost
            if expected_visual:
                visual_latencies.append(latency_ms)
                visual_cost += query_cost + _visual_trace_cost(
                    self.system, principal.tenant_id, answer.correlation_id
                )
                if any(
                    _matches_chunk(expected, result.chunk)
                    for expected in expected_visual
                    for result in retrieved
                ):
                    visual_recall_hits += 1
                if any(
                    _matches_citation(expected, citation)
                    for expected in expected_visual
                    for citation in answer.citations
                ):
                    visual_citation_hits += 1
                if (
                    answer.status == "ok"
                    and answer.used_chunks
                    and any(citation.kind == "visual" for citation in answer.citations)
                ):
                    visual_grounded_hits += 1
                bbox_scores.extend(_bbox_scores(expected_visual, answer.citations))
            examples.append(
                EvaluationExampleResult(
                    item_id=item.item_id,
                    answer_status=answer.status,
                    cited_document_ids=cited_docs,
                    retrieved_document_ids=retrieved_docs,
                    latency_ms=latency_ms,
                    query_cost=query_cost,
                    cited_asset_ids=cited_assets,
                    retrieved_asset_ids=retrieved_assets,
                    cited_region_ids=cited_regions,
                    retrieved_region_ids=retrieved_regions,
                )
            )

        count = max(1, len(eval_set.items))
        visual_count = max(
            1,
            sum(
                1
                for item in eval_set.items
                if any(_is_visual_expected(e) for e in item.expected_evidence)
            ),
        )
        latencies = [example.latency_ms for example in examples]
        metrics = {
            "recall_at_k": recall_hits / count,
            "precision_at_k": precision_sum / gradeable if gradeable else 0.0,
            "mrr": rr_sum / gradeable if gradeable else 0.0,
            "citation_accuracy": citation_hits / count,
            "groundedness": grounded_hits / count,
            "faithfulness": faithful_sum / faithful_gradeable if faithful_gradeable else 0.0,
            "p95_latency_ms": _p95(latencies),
            "query_cost": total_cost,
            "visual_recall_at_k": visual_recall_hits / visual_count,
            "visual_citation_accuracy": visual_citation_hits / visual_count,
            "bbox_iou": (sum(bbox_scores) / len(bbox_scores)) if bbox_scores else 0.0,
            "visual_groundedness": visual_grounded_hits / visual_count,
            "p95_visual_answer_latency_ms": _p95(visual_latencies),
            "visual_query_cost": visual_cost,
        }
        # Compute the security signal from real probes; the caller-supplied counts can only RAISE a
        # count (force-block override), never downgrade a probe-found leak — this keeps the protected
        # test_eval_hard_gate green unmodified while making the probes authoritative (research D2).
        probe_outcome = self.probe_suite.run()
        caller_counts = security_check_counts or {}
        effective_counts = {
            name: max(
                int(probe_outcome.counts.get(name, 0) or 0),
                int(caller_counts.get(name, 0) or 0),
            )
            for name in SECURITY_CHECKS
        }
        security_checks = _security_checks(effective_counts)
        gate_result = (
            "blocked"
            if (not probe_outcome.probes_executed)
            or any(not check["passed"] for check in security_checks.values())
            else "passed"
        )
        baseline_comparison = _compare_to_baseline(
            metrics, baseline_run.metrics if baseline_run else {}
        )
        run_id = _stable_id(
            "eval_run", [eval_set.eval_set_id, principal.tenant_id, metrics, security_checks]
        )
        run_record = EvaluationRun(
            run_id=run_id,
            eval_set_id=eval_set.eval_set_id,
            tenant_id=eval_set.tenant_id,
            status="succeeded",
            baseline=baseline,
            metrics=metrics,
            baseline_comparison=baseline_comparison,
            security_checks=security_checks,
            gate_result=gate_result,
            examples=tuple(examples),
            probe_results=tuple(result.to_dict() for result in probe_outcome.results),
            probes_executed=probe_outcome.probes_executed,
        )
        if self.run_repository is not None:
            self.run_repository.save(run_record)
        return run_record


def _term_support(answer_text: str | None, evidence_text: str) -> float:
    """Deterministic faithfulness proxy (012/P1-5): the fraction of the answer's content-terms that
    are supported by the evidence's content-terms. 1.0 = fully supported, 0.0 = no support / no text.
    """
    answer_terms = content_terms(answer_text or "")
    if not answer_terms:
        return 0.0
    return len(answer_terms & content_terms(evidence_text)) / len(answer_terms)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return ordered[index]


def _is_visual_expected(evidence: ExpectedEvidence) -> bool:
    return (
        evidence.kind == "visual"
        or bool(evidence.asset_id)
        or bool(evidence.region_id)
        or evidence.bbox is not None
    )


def _is_visual_chunk(chunk: Chunk) -> bool:
    if isinstance(chunk.modality, Modality):
        return chunk.modality == Modality.VISUAL
    return str(chunk.modality) == Modality.VISUAL.value


def _matches_chunk(expected: ExpectedEvidence, chunk: Chunk) -> bool:
    if not _is_visual_chunk(chunk):
        return False
    if expected.document_id and expected.document_id != chunk.document_id:
        return False
    if expected.chunk_id and expected.chunk_id != chunk.chunk_id:
        return False
    if expected.asset_id and expected.asset_id != str(chunk.metadata.get("asset_id", "")):
        return False
    if expected.region_id and expected.region_id != str(chunk.metadata.get("region_id", "")):
        return False
    return True


def _matches_citation(expected: ExpectedEvidence, citation: Citation) -> bool:
    if citation.kind != "visual":
        return False
    if expected.document_id and expected.document_id != citation.document_id:
        return False
    if expected.chunk_id and expected.chunk_id != (citation.chunk_id or ""):
        return False
    if expected.asset_id and expected.asset_id != citation.asset_id:
        return False
    if expected.region_id and expected.region_id != citation.region_id:
        return False
    return True


def _bbox_scores(
    expected: tuple[ExpectedEvidence, ...], citations: tuple[Citation, ...]
) -> list[float]:
    scores: list[float] = []
    for item in expected:
        if item.bbox is None:
            continue
        matches = [
            _bbox_iou(item.bbox, citation.bbox)
            for citation in citations
            if citation.bbox is not None and _matches_citation(item, citation)
        ]
        if matches:
            scores.append(max(matches))
        else:
            scores.append(0.0)
    return scores


def _bbox_iou(left: BoundingBox, right: BoundingBox | None) -> float:
    if right is None:
        return 0.0
    left_x2 = left.x + left.width
    left_y2 = left.y + left.height
    right_x2 = right.x + right.width
    right_y2 = right.y + right.height
    intersection_width = max(0.0, min(left_x2, right_x2) - max(left.x, right.x))
    intersection_height = max(0.0, min(left_y2, right_y2) - max(left.y, right.y))
    intersection = intersection_width * intersection_height
    union = (left.width * left.height) + (right.width * right.height) - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _visual_trace_cost(system, tenant_id: str, trace_id: str) -> float:
    if not trace_id or not hasattr(system, "cost"):
        return 0.0
    records = getattr(system.cost, "records", lambda *args, **kwargs: ())(tenant_id)
    return sum(
        float(record.amount)
        for record in records
        if record.trace_id == trace_id
        and record.kind in {"vlm_image_tokens", "thumbnail_crop_generation_cost"}
    )


def _security_checks(counts: dict[str, int]) -> dict:
    checks: dict[str, dict] = {}
    for name in SECURITY_CHECKS:
        count = int(counts.get(name, 0) or 0)
        checks[name] = SecurityCheck(passed=count == 0, count=count).to_dict()
    return checks


def _compare_to_baseline(metrics: dict, baseline_metrics: dict) -> dict:
    if not baseline_metrics:
        return {}
    comparison = {}
    for key, value in metrics.items():
        if key in baseline_metrics:
            comparison[key] = value - float(baseline_metrics[key])
    return comparison
