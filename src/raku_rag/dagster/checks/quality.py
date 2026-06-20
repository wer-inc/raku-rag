"""T059a - Dagster-compatible quality check assets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from raku_rag.domain.models import Chunk


@dataclass(frozen=True)
class QualityCheckResult:
    name: str
    passed: bool
    value: float | int | str = 0
    threshold: float | int | str = 0
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "value": self.value,
            "threshold": self.threshold,
            "reason": self.reason,
        }


def check_embedding_coverage(chunks: Iterable[Chunk]) -> QualityCheckResult:
    items = tuple(chunks)
    missing = [chunk.chunk_id for chunk in items if not chunk.embedding_model_version]
    return QualityCheckResult(
        name="embedding_coverage",
        passed=not missing,
        value=len(items) - len(missing),
        threshold=len(items),
        reason="" if not missing else f"missing embeddings for {','.join(missing)}",
    )


def check_chunk_count(document_id: str, chunk_count: int) -> QualityCheckResult:
    return QualityCheckResult(
        name="chunk_count_positive",
        passed=chunk_count > 0,
        value=chunk_count,
        threshold=1,
        reason="" if chunk_count > 0 else f"{document_id} has no chunks",
    )


def check_parser_output_schema(parsed_texts: Iterable[str]) -> QualityCheckResult:
    texts = tuple(parsed_texts)
    passed = all(isinstance(text, str) and bool(text.strip()) for text in texts)
    return QualityCheckResult(
        name="parser_output_schema_valid",
        passed=passed,
        value=len(texts),
        threshold=len(texts),
        reason="" if passed else "parser output must be non-empty normalized text",
    )


def check_spreadsheet_citation_cell_ranges(citations: Iterable[object]) -> QualityCheckResult:
    invalid = 0
    for citation in citations:
        cell_range = getattr(citation, "cell_range", None)
        if cell_range is None:
            continue
        if not (
            isinstance(cell_range, tuple)
            and len(cell_range) == 4
            and all(isinstance(value, int) and value >= 1 for value in cell_range)
        ):
            invalid += 1
    return QualityCheckResult(
        name="spreadsheet_citation_cell_range_valid",
        passed=invalid == 0,
        value=invalid,
        threshold=0,
        reason="" if invalid == 0 else "invalid spreadsheet cell ranges present",
    )


def check_deleted_documents_not_searchable(
    deleted_document_ids: Iterable[str],
    retrieved_document_ids: Iterable[str],
) -> QualityCheckResult:
    deleted = set(deleted_document_ids)
    retrieved = set(retrieved_document_ids)
    leaked = sorted(deleted & retrieved)
    return QualityCheckResult(
        name="deleted_documents_not_searchable",
        passed=not leaked,
        value=len(leaked),
        threshold=0,
        reason="" if not leaked else f"deleted documents retrieved: {','.join(leaked)}",
    )


def check_acl_leakage(leakage_count: int) -> QualityCheckResult:
    return QualityCheckResult(
        name="acl_leakage_zero",
        passed=leakage_count == 0,
        value=leakage_count,
        threshold=0,
        reason="" if leakage_count == 0 else "ACL leakage detected",
    )


def check_tenant_isolation(leakage_count: int) -> QualityCheckResult:
    return QualityCheckResult(
        name="tenant_isolation_leakage_zero",
        passed=leakage_count == 0,
        value=leakage_count,
        threshold=0,
        reason="" if leakage_count == 0 else "tenant isolation leakage detected",
    )


def check_baseline_regression(
    metrics: dict,
    baseline_metrics: dict,
    *,
    recall_drop_tolerance: float = 0.0,
    citation_drop_tolerance: float = 0.0,
) -> QualityCheckResult:
    recall_delta = float(metrics.get("recall_at_k", 0.0)) - float(
        baseline_metrics.get("recall_at_k", 0.0)
    )
    citation_delta = float(metrics.get("citation_accuracy", 0.0)) - float(
        baseline_metrics.get("citation_accuracy", 0.0)
    )
    passed = recall_delta >= -recall_drop_tolerance and citation_delta >= -citation_drop_tolerance
    return QualityCheckResult(
        name="recall_citation_baseline_regression",
        passed=passed,
        value=min(recall_delta, citation_delta),
        threshold=-max(recall_drop_tolerance, citation_drop_tolerance),
        reason="" if passed else "recall or citation accuracy regressed beyond tolerance",
    )
