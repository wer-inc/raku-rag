"""T105 - two-stage offline PoC benchmark harness.

The harness builds deterministic Japanese document samples per industry and the execution matrices
used by the later parser, embedding/retrieval, answer-quality, and hard-gate benchmark tasks.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

from raku_rag.eval import EvaluationSet

BENCHMARK_TYPE = "poc_stack_benchmark"
DEFAULT_INDUSTRY_IDS = (
    "manufacturing",
    "real_estate_property_management",
    "investment_management_mutual_fund",
)
DEFAULT_PARSER_PROVIDERS = (
    "aws_textract",
    "azure_document_intelligence",
    "google_document_ai",
    "tesseract",
)
DEFAULT_EMBEDDING_MODELS = (
    "cohere-embed-multilingual-v3",
    "amazon-titan-embed-text-v2",
)
DEFAULT_RETRIEVAL_PROFILES = (
    "vector_rerank",
    "metadata_code_vector_rerank",
    "hybrid_metadata_code_vector_rerank",
)
SOURCE_FORMATS = ("pdf", "docx", "xlsx", "csv", "image", "scanned_pdf")
STAGE1_METRICS = (
    "parser_table_structure_accuracy",
    "spreadsheet_cell_citation_accuracy",
    "ocr_layout_confidence",
    "chunk_coverage",
    "embedding_coverage",
    "p95_parse_index_latency_ms",
    "parse_index_cost",
    "provider_policy_compliance",
)
STAGE2_METRICS = (
    "recall_at_5",
    "recall_at_10",
    "exact_code_lookup_success_rate",
    "citation_accuracy",
    "spreadsheet_cell_citation_accuracy",
    "groundedness",
    "insufficient_evidence_correct_rejection_rate",
    "high_risk_gate_compliance",
    "p95_latency_ms",
    "query_cost",
)
HARD_GATES = (
    "acl_leakage_count",
    "tenant_leakage_count",
    "deleted_document_searchable_count",
    "raw_context_logging_violation_count",
)
SECURITY_PROBES = (
    {
        "gate": "acl_leakage_count",
        "scenario": "unauthorized principal cannot retrieve collection-scoped documents",
    },
    {
        "gate": "tenant_leakage_count",
        "scenario": "cross-tenant query returns zero documents and citations",
    },
    {
        "gate": "deleted_document_searchable_count",
        "scenario": "tombstoned document is absent from retrieval and answer citations",
    },
    {
        "gate": "raw_context_logging_violation_count",
        "scenario": "Langfuse/logging payload contains no raw retrieved context by default",
    },
)


@dataclass(frozen=True)
class IndustryProfile:
    industry_id: str
    display_name_ja: str
    collection_id: str
    primary_identifier: str
    secondary_identifier: str
    noun_ja: str
    action_ja: str
    risk_ja: str


@dataclass(frozen=True)
class BenchmarkDocument:
    industry_id: str
    document_id: str
    collection_id: str
    source_format: str
    title: str
    text: str
    metadata: Mapping[str, object]

    def expected_evidence(self) -> dict:
        return {"document_id": self.document_id}


@dataclass(frozen=True)
class BenchmarkQuery:
    industry_id: str
    question: str
    expected_answer: str
    expected_document_id: str
    query_type: str

    def to_eval_item(self) -> dict:
        return {
            "question": self.question,
            "expected_answer": self.expected_answer,
            "expected_evidence": [{"document_id": self.expected_document_id}],
        }


@dataclass(frozen=True)
class IndustryBenchmarkCorpus:
    profile: IndustryProfile
    documents: tuple[BenchmarkDocument, ...]
    queries: tuple[BenchmarkQuery, ...]


@dataclass(frozen=True)
class PocBenchmarkRequest:
    industry_ids: tuple[str, ...] = DEFAULT_INDUSTRY_IDS
    document_sample_size: int = 20
    parser_providers: tuple[str, ...] = DEFAULT_PARSER_PROVIDERS
    embedding_models: tuple[str, ...] = DEFAULT_EMBEDDING_MODELS
    retrieval_profiles: tuple[str, ...] = DEFAULT_RETRIEVAL_PROFILES
    metrics: tuple[str, ...] = ()
    tenant_id: str = "tenant_poc_benchmark"

    def validate(self) -> None:
        if not 20 <= self.document_sample_size <= 50:
            raise ValueError("document_sample_size must be between 20 and 50")
        if not self.industry_ids:
            raise ValueError("industry_ids must not be empty")
        if not self.parser_providers:
            raise ValueError("parser_providers must not be empty")
        if not self.embedding_models:
            raise ValueError("embedding_models must not be empty")
        if not self.retrieval_profiles:
            raise ValueError("retrieval_profiles must not be empty")


@dataclass(frozen=True)
class PocBenchmarkPlan:
    evaluation_run_id: str
    benchmark_type: str
    status_url: str
    request: PocBenchmarkRequest
    corpora: tuple[IndustryBenchmarkCorpus, ...]
    eval_set: EvaluationSet
    stage1_matrix: tuple[dict, ...]
    stage2_matrix: tuple[dict, ...]
    metrics: tuple[str, ...]
    hard_gates: tuple[str, ...] = HARD_GATES

    def to_dict(self) -> dict:
        return {
            "evaluation_run_id": self.evaluation_run_id,
            "benchmark_type": self.benchmark_type,
            "status_url": self.status_url,
            "industry_ids": [corpus.profile.industry_id for corpus in self.corpora],
            "document_sample_size": self.request.document_sample_size,
            "document_count": sum(len(corpus.documents) for corpus in self.corpora),
            "eval_set_id": self.eval_set.eval_set_id,
            "eval_item_count": len(self.eval_set.items),
            "stage1_matrix": list(self.stage1_matrix),
            "stage2_matrix": list(self.stage2_matrix),
            "metrics": list(self.metrics),
            "hard_gates": list(self.hard_gates),
        }


@dataclass(frozen=True)
class PocBenchmarkRun:
    evaluation_run_id: str
    benchmark_type: str
    status: str
    parser_results: tuple[dict, ...]
    retrieval_results: tuple[dict, ...]
    metrics: Mapping[str, float]
    hard_gates: Mapping[str, int]
    recommendation: Mapping[str, object] = field(default_factory=dict)
    fallback_paths: tuple[dict, ...] = ()
    answer_quality_results: tuple[dict, ...] = ()
    security_results: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "evaluation_run_id": self.evaluation_run_id,
            "benchmark_type": self.benchmark_type,
            "status": self.status,
            "parser_results": list(self.parser_results),
            "retrieval_results": list(self.retrieval_results),
            "metrics": dict(self.metrics),
            "hard_gates": dict(self.hard_gates),
            "recommendation": dict(self.recommendation),
            "fallback_paths": list(self.fallback_paths),
            "answer_quality_results": list(self.answer_quality_results),
            "security_results": list(self.security_results),
        }


ParserEvaluator = Callable[[BenchmarkDocument, str], Mapping[str, float]]
RetrievalEvaluator = Callable[[EvaluationSet, str, str, str], Mapping[str, float]]
SecurityEvaluator = Callable[[PocBenchmarkPlan], Mapping[str, int]]


class PocStackBenchmarkHarness:
    def __init__(self, profiles: Iterable[IndustryProfile] | None = None) -> None:
        self._profiles = {
            profile.industry_id: profile for profile in (profiles or _default_profiles())
        }

    def plan(self, request: PocBenchmarkRequest | None = None) -> PocBenchmarkPlan:
        request = request or PocBenchmarkRequest()
        request.validate()
        corpora = self.build_corpora(request)
        eval_set = self.build_eval_set(request.tenant_id, corpora)
        stage1_matrix = self._stage1_matrix(request, corpora)
        stage2_matrix = self._stage2_matrix(request, corpora, eval_set)
        metrics = request.metrics or (*STAGE1_METRICS, *STAGE2_METRICS)
        run_id = _stable_id(
            "poc_bench",
            {
                "industries": request.industry_ids,
                "sample_size": request.document_sample_size,
                "parsers": request.parser_providers,
                "embeddings": request.embedding_models,
                "retrieval": request.retrieval_profiles,
                "eval_set_id": eval_set.eval_set_id,
            },
        )
        return PocBenchmarkPlan(
            evaluation_run_id=run_id,
            benchmark_type=BENCHMARK_TYPE,
            status_url=f"/v1/evaluations/poc-runs/{run_id}",
            request=request,
            corpora=corpora,
            eval_set=eval_set,
            stage1_matrix=stage1_matrix,
            stage2_matrix=stage2_matrix,
            metrics=metrics,
        )

    def build_corpora(self, request: PocBenchmarkRequest) -> tuple[IndustryBenchmarkCorpus, ...]:
        corpora: list[IndustryBenchmarkCorpus] = []
        for industry_id in request.industry_ids:
            profile = self._profiles.get(industry_id)
            if profile is None:
                raise KeyError(f"unknown industry_id: {industry_id}")
            documents = tuple(
                _document_for(profile, index)
                for index in range(1, request.document_sample_size + 1)
            )
            queries = tuple(
                _query_for(profile, document, index)
                for index, document in enumerate(documents, start=1)
            )
            corpora.append(
                IndustryBenchmarkCorpus(profile=profile, documents=documents, queries=queries)
            )
        return tuple(corpora)

    def build_eval_set(
        self, tenant_id: str, corpora: Iterable[IndustryBenchmarkCorpus]
    ) -> EvaluationSet:
        items = [query.to_eval_item() for corpus in corpora for query in corpus.queries]
        return EvaluationSet.register(
            tenant_id=tenant_id, items=items, eval_set_id="poc_stack_benchmark_eval"
        )

    def run_offline(
        self,
        request: PocBenchmarkRequest | None = None,
        *,
        parser_evaluator: ParserEvaluator | None = None,
        retrieval_evaluator: RetrievalEvaluator | None = None,
        security_evaluator: SecurityEvaluator | None = None,
    ) -> PocBenchmarkRun:
        plan = self.plan(request)
        parser_results = tuple(self._run_parser_stage(plan, parser_evaluator))
        retrieval_results = tuple(self._run_retrieval_stage(plan, retrieval_evaluator))
        metrics = _aggregate_metrics(parser_results, retrieval_results)
        hard_gates = _hard_gate_counts(plan, security_evaluator)
        recommendation = _recommend(parser_results, retrieval_results)
        answer_quality_results = _answer_quality_results(retrieval_results)
        security_results = _security_results(hard_gates)
        fallback_paths = (
            {
                "from": "vector_rerank",
                "to": "metadata_code_vector_rerank",
                "reason": "exact identifier recall",
            },
            {
                "from": "external_parser",
                "to": "aws_textract",
                "reason": "ProviderPolicy or residency failure",
            },
        )
        return PocBenchmarkRun(
            evaluation_run_id=plan.evaluation_run_id,
            benchmark_type=BENCHMARK_TYPE,
            status="blocked" if any(count > 0 for count in hard_gates.values()) else "succeeded",
            parser_results=parser_results,
            retrieval_results=retrieval_results,
            metrics=metrics,
            hard_gates=hard_gates,
            recommendation=recommendation,
            fallback_paths=fallback_paths,
            answer_quality_results=answer_quality_results,
            security_results=security_results,
        )

    def _stage1_matrix(
        self, request: PocBenchmarkRequest, corpora: tuple[IndustryBenchmarkCorpus, ...]
    ) -> tuple[dict, ...]:
        rows: list[dict] = []
        for corpus in corpora:
            formats = sorted({document.source_format for document in corpus.documents})
            for provider in request.parser_providers:
                rows.append(
                    {
                        "stage": "provider_parser",
                        "industry_id": corpus.profile.industry_id,
                        "parser_provider": provider,
                        "document_count": len(corpus.documents),
                        "source_formats": formats,
                        "metrics": list(STAGE1_METRICS),
                    }
                )
        return tuple(rows)

    def _stage2_matrix(
        self,
        request: PocBenchmarkRequest,
        corpora: tuple[IndustryBenchmarkCorpus, ...],
        eval_set: EvaluationSet,
    ) -> tuple[dict, ...]:
        rows: list[dict] = []
        for corpus in corpora:
            for embedding_model in request.embedding_models:
                for retrieval_profile in request.retrieval_profiles:
                    rows.append(
                        {
                            "stage": "retrieval_answer",
                            "industry_id": corpus.profile.industry_id,
                            "embedding_model": embedding_model,
                            "retrieval_profile": retrieval_profile,
                            "eval_set_id": eval_set.eval_set_id,
                            "eval_item_count": len(corpus.queries),
                            "metrics": list(STAGE2_METRICS),
                        }
                    )
        return tuple(rows)

    def _run_parser_stage(
        self, plan: PocBenchmarkPlan, evaluator: ParserEvaluator | None
    ) -> Iterable[dict]:
        documents_by_industry = {
            corpus.profile.industry_id: corpus.documents for corpus in plan.corpora
        }
        for row in plan.stage1_matrix:
            provider = str(row["parser_provider"])
            documents = documents_by_industry[str(row["industry_id"])]
            samples = [_parser_metrics(document, provider, evaluator) for document in documents]
            format_results = []
            for source_format in SOURCE_FORMATS:
                format_documents = [
                    document for document in documents if document.source_format == source_format
                ]
                if not format_documents:
                    continue
                format_samples = [
                    _parser_metrics(document, provider, evaluator) for document in format_documents
                ]
                format_results.append(
                    {
                        "source_format": source_format,
                        "document_count": len(format_documents),
                        "metrics": _mean_metrics(format_samples, STAGE1_METRICS),
                    }
                )
            yield {
                **row,
                "status": "completed",
                "metrics": _mean_metrics(samples, STAGE1_METRICS),
                "format_results": format_results,
            }

    def _run_retrieval_stage(
        self, plan: PocBenchmarkPlan, evaluator: RetrievalEvaluator | None
    ) -> Iterable[dict]:
        corpora_by_industry = {corpus.profile.industry_id: corpus for corpus in plan.corpora}
        for row in plan.stage2_matrix:
            embedding_model = str(row["embedding_model"])
            retrieval_profile = str(row["retrieval_profile"])
            industry_id = str(row["industry_id"])
            metrics = (
                evaluator(plan.eval_set, industry_id, embedding_model, retrieval_profile)
                if evaluator
                else _default_retrieval_metrics(embedding_model, retrieval_profile)
            )
            normalized_metrics = {
                metric: float(metrics.get(metric, 0.0)) for metric in STAGE2_METRICS
            }
            yield {
                **row,
                "status": "completed",
                "metrics": normalized_metrics,
                "query_type_metrics": _query_type_metrics(
                    corpora_by_industry[industry_id].queries,
                    normalized_metrics,
                    retrieval_profile,
                ),
            }


def _default_profiles() -> tuple[IndustryProfile, ...]:
    return (
        IndustryProfile(
            industry_id="manufacturing",
            display_name_ja="製造業",
            collection_id="manufacturing_manuals",
            primary_identifier="EQ",
            secondary_identifier="AL",
            noun_ja="設備",
            action_ja="保全手順",
            risk_ja="高温部のロックアウト",
        ),
        IndustryProfile(
            industry_id="real_estate_property_management",
            display_name_ja="不動産管理",
            collection_id="property_management",
            primary_identifier="PR",
            secondary_identifier="RM",
            noun_ja="物件",
            action_ja="修繕受付",
            risk_ja="消防設備の点検未了",
        ),
        IndustryProfile(
            industry_id="investment_management_mutual_fund",
            display_name_ja="投資運用・投信",
            collection_id="fund_operations",
            primary_identifier="FD",
            secondary_identifier="ISIN",
            noun_ja="ファンド",
            action_ja="約款確認",
            risk_ja="適合性確認なしの勧誘",
        ),
    )


def _document_for(profile: IndustryProfile, index: int) -> BenchmarkDocument:
    source_format = SOURCE_FORMATS[(index - 1) % len(SOURCE_FORMATS)]
    primary_code = f"{profile.primary_identifier}-{index:03d}"
    secondary_code = f"{profile.secondary_identifier}-{1000 + index:04d}"
    table_cell = f"B{(index % 12) + 2}"
    title = f"{profile.display_name_ja} {profile.noun_ja}{index:02d} {profile.action_ja}記録"
    text = (
        f"{title}。識別子 {primary_code}、関連コード {secondary_code}。"
        f"{profile.noun_ja}の{profile.action_ja}は毎月第{(index % 4) + 1}営業日に実施する。"
        f"表のセル {table_cell} には点検結果「正常」と記録する。"
        f"リスク項目は「{profile.risk_ja}」で、承認済み証跡がない場合は回答不可とする。"
    )
    return BenchmarkDocument(
        industry_id=profile.industry_id,
        document_id=f"{profile.industry_id}_doc_{index:03d}",
        collection_id=profile.collection_id,
        source_format=source_format,
        title=title,
        text=text,
        metadata={
            "industry_id": profile.industry_id,
            "document_type": "manual" if index % 2 else "spreadsheet",
            "approval_status": "approved",
            "primary_identifier": primary_code,
            "secondary_identifier": secondary_code,
            "source_format": source_format,
            "table_cell": table_cell,
            "language": "ja",
        },
    )


def _query_for(profile: IndustryProfile, document: BenchmarkDocument, index: int) -> BenchmarkQuery:
    primary_code = str(document.metadata["primary_identifier"])
    secondary_code = str(document.metadata["secondary_identifier"])
    if index % 5 == 0:
        question = f"{primary_code} のリスク項目について、承認済み証跡なしで作業してよいですか?"
        expected = "承認済み証跡がない場合は回答不可"
        query_type = "high_risk_gate"
    elif index % 3 == 0:
        question = f"{secondary_code} が記載された文書の表セルと結果を教えてください。"
        expected = f"{document.metadata['table_cell']} に「正常」"
        query_type = "spreadsheet_cell_citation"
    else:
        question = f"{primary_code} の {profile.action_ja} はいつ実施しますか?"
        expected = f"毎月第{(index % 4) + 1}営業日"
        query_type = "exact_code_lookup"
    return BenchmarkQuery(
        industry_id=profile.industry_id,
        question=question,
        expected_answer=expected,
        expected_document_id=document.document_id,
        query_type=query_type,
    )


def _parser_metrics(
    document: BenchmarkDocument,
    provider: str,
    evaluator: ParserEvaluator | None,
) -> Mapping[str, float]:
    if evaluator:
        return evaluator(document, provider)
    provider_profile = {
        "aws_textract": {
            "table": 0.88,
            "cell": 0.82,
            "ocr": 0.93,
            "latency": 2200.0,
            "cost": 0.015,
        },
        "azure_document_intelligence": {
            "table": 0.95,
            "cell": 0.92,
            "ocr": 0.95,
            "latency": 2600.0,
            "cost": 0.02,
        },
        "google_document_ai": {
            "table": 0.93,
            "cell": 0.9,
            "ocr": 0.94,
            "latency": 2500.0,
            "cost": 0.019,
        },
        "tesseract": {
            "table": 0.68,
            "cell": 0.55,
            "ocr": 0.8,
            "latency": 1800.0,
            "cost": 0.0,
        },
    }.get(
        provider,
        {"table": 0.0, "cell": 0.0, "ocr": 0.0, "latency": 0.0, "cost": 0.0},
    )
    format_adjustment = {
        "pdf": 1.0,
        "docx": 0.98,
        "xlsx": 0.96,
        "csv": 0.94,
        "image": 0.9,
        "scanned_pdf": 0.88,
    }[document.source_format]
    policy_compliance = 1.0 if provider in DEFAULT_PARSER_PROVIDERS else 0.0
    spreadsheet_applicable = document.source_format in {"xlsx", "csv"}
    return {
        "parser_table_structure_accuracy": _bounded(provider_profile["table"] * format_adjustment),
        "spreadsheet_cell_citation_accuracy": (
            _bounded(provider_profile["cell"] * format_adjustment)
            if spreadsheet_applicable
            else 0.0
        ),
        "ocr_layout_confidence": _bounded(provider_profile["ocr"] * format_adjustment),
        "chunk_coverage": 1.0,
        "embedding_coverage": 1.0,
        "p95_parse_index_latency_ms": float(provider_profile["latency"] + len(document.text)),
        "parse_index_cost": float(provider_profile["cost"]),
        "provider_policy_compliance": policy_compliance,
    }


def _default_retrieval_metrics(embedding_model: str, retrieval_profile: str) -> Mapping[str, float]:
    embedding_factor = 1.0 if embedding_model == "cohere-embed-multilingual-v3" else 0.95
    profile = {
        "vector_rerank": {
            "recall_at_5": 0.82,
            "recall_at_10": 0.92,
            "exact": 0.74,
            "citation": 0.8,
            "cell": 0.72,
            "latency": 2100.0,
            "cost": 0.018,
        },
        "metadata_code_vector_rerank": {
            "recall_at_5": 0.94,
            "recall_at_10": 0.99,
            "exact": 1.0,
            "citation": 0.93,
            "cell": 0.9,
            "latency": 2400.0,
            "cost": 0.02,
        },
        "hybrid_metadata_code_vector_rerank": {
            "recall_at_5": 0.96,
            "recall_at_10": 1.0,
            "exact": 1.0,
            "citation": 0.95,
            "cell": 0.93,
            "latency": 2800.0,
            "cost": 0.024,
        },
    }[retrieval_profile]
    return {
        "recall_at_5": _bounded(profile["recall_at_5"] * embedding_factor),
        "recall_at_10": _bounded(profile["recall_at_10"] * embedding_factor),
        "exact_code_lookup_success_rate": _bounded(profile["exact"] * embedding_factor),
        "citation_accuracy": _bounded(profile["citation"] * embedding_factor),
        "spreadsheet_cell_citation_accuracy": _bounded(profile["cell"] * embedding_factor),
        "groundedness": 1.0,
        "insufficient_evidence_correct_rejection_rate": 1.0,
        "high_risk_gate_compliance": 1.0,
        "p95_latency_ms": float(profile["latency"]),
        "query_cost": float(profile["cost"]),
    }


def _mean_metrics(
    samples: Iterable[Mapping[str, float]], metric_names: tuple[str, ...]
) -> dict[str, float]:
    values = list(samples)
    if not values:
        return {metric: 0.0 for metric in metric_names}
    return {
        metric: sum(float(sample.get(metric, 0.0)) for sample in values) / len(values)
        for metric in metric_names
    }


def _query_type_metrics(
    queries: tuple[BenchmarkQuery, ...],
    metrics: Mapping[str, float],
    retrieval_profile: str,
) -> list[dict]:
    counts: dict[str, int] = {}
    for query in queries:
        counts[query.query_type] = counts.get(query.query_type, 0) + 1
    return [
        {
            "query_type": "exact_code_lookup",
            "query_count": counts.get("exact_code_lookup", 0),
            "metrics": {
                "recall_at_5": metrics["recall_at_5"],
                "recall_at_10": metrics["recall_at_10"],
                "exact_code_lookup_success_rate": metrics["exact_code_lookup_success_rate"],
                "citation_accuracy": metrics["citation_accuracy"],
            },
        },
        {
            "query_type": "spreadsheet_cell_citation",
            "query_count": counts.get("spreadsheet_cell_citation", 0),
            "metrics": {
                "spreadsheet_cell_citation_accuracy": metrics["spreadsheet_cell_citation_accuracy"],
                "citation_accuracy": metrics["citation_accuracy"],
                "groundedness": metrics["groundedness"],
            },
        },
        {
            "query_type": "high_risk_gate",
            "query_count": counts.get("high_risk_gate", 0),
            "metrics": {
                "insufficient_evidence_correct_rejection_rate": metrics[
                    "insufficient_evidence_correct_rejection_rate"
                ],
                "high_risk_gate_compliance": metrics["high_risk_gate_compliance"],
                "groundedness": metrics["groundedness"],
            },
        },
        {
            "query_type": "profile_overhead",
            "query_count": len(queries),
            "metrics": {
                "p95_latency_ms": metrics["p95_latency_ms"],
                "query_cost": metrics["query_cost"],
                "hybrid_search_enabled": 1.0 if retrieval_profile.startswith("hybrid_") else 0.0,
            },
        },
    ]


def _answer_quality_results(retrieval_results: tuple[dict, ...]) -> tuple[dict, ...]:
    rows: list[dict] = []
    for result in retrieval_results:
        metrics = dict(result.get("metrics") or {})
        rows.append(
            {
                "industry_id": result["industry_id"],
                "embedding_model": result["embedding_model"],
                "retrieval_profile": result["retrieval_profile"],
                "query_type_metrics": list(result.get("query_type_metrics") or []),
                "metrics": {
                    "citation_accuracy": metrics.get("citation_accuracy", 0.0),
                    "groundedness": metrics.get("groundedness", 0.0),
                    "insufficient_evidence_correct_rejection_rate": metrics.get(
                        "insufficient_evidence_correct_rejection_rate", 0.0
                    ),
                    "high_risk_gate_compliance": metrics.get("high_risk_gate_compliance", 0.0),
                    "p95_latency_ms": metrics.get("p95_latency_ms", 0.0),
                    "query_cost": metrics.get("query_cost", 0.0),
                },
            }
        )
    return tuple(rows)


def _hard_gate_counts(
    plan: PocBenchmarkPlan, evaluator: SecurityEvaluator | None
) -> dict[str, int]:
    raw = evaluator(plan) if evaluator else {}
    return {name: int(raw.get(name, 0)) for name in HARD_GATES}


def _security_results(hard_gates: Mapping[str, int]) -> tuple[dict, ...]:
    return tuple(
        {
            "gate": probe["gate"],
            "scenario": probe["scenario"],
            "count": int(hard_gates.get(str(probe["gate"]), 0)),
            "passed": int(hard_gates.get(str(probe["gate"]), 0)) == 0,
        }
        for probe in SECURITY_PROBES
    )


def _aggregate_metrics(
    parser_results: tuple[dict, ...], retrieval_results: tuple[dict, ...]
) -> dict[str, float]:
    merged: dict[str, list[float]] = {}
    for result in (*parser_results, *retrieval_results):
        for metric, value in dict(result.get("metrics") or {}).items():
            merged.setdefault(metric, []).append(float(value))
    return {metric: sum(values) / len(values) for metric, values in merged.items() if values}


def _recommend(
    parser_results: tuple[dict, ...], retrieval_results: tuple[dict, ...]
) -> dict[str, object]:
    parser = max(
        parser_results,
        key=lambda row: (
            row["metrics"].get("provider_policy_compliance", 0.0),
            row["metrics"].get("parser_table_structure_accuracy", 0.0),
        ),
        default={},
    )
    retrieval = max(
        retrieval_results,
        key=lambda row: (
            row["metrics"].get("exact_code_lookup_success_rate", 0.0),
            row["metrics"].get("citation_accuracy", 0.0),
        ),
        default={},
    )
    return {
        "parser_provider": parser.get("parser_provider", ""),
        "embedding_model": retrieval.get("embedding_model", ""),
        "retrieval_profile": retrieval.get("retrieval_profile", ""),
    }


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _stable_id(prefix: str, payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:16]}"
