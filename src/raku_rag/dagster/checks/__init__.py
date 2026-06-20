"""Dagster-compatible quality check descriptors."""

from __future__ import annotations

from dataclasses import dataclass

from raku_rag.dagster.checks.quality import (
    QualityCheckResult,
    check_acl_leakage,
    check_baseline_regression,
    check_chunk_count,
    check_deleted_documents_not_searchable,
    check_embedding_coverage,
    check_parser_output_schema,
    check_spreadsheet_citation_cell_ranges,
    check_tenant_isolation,
)
from raku_rag.dagster.checks.manufacturing import (
    check_high_risk_approved_citations,
    manufacturing_quality_checks,
)


@dataclass(frozen=True)
class DagsterCheckSpec:
    name: str
    description: str
    hard_gate: bool = True
    request_path_allowed: bool = False


INGESTION_CHECKS: tuple[DagsterCheckSpec, ...] = (
    DagsterCheckSpec("embedding_coverage", "Every indexed text chunk has an embedding"),
    DagsterCheckSpec(
        "deleted_documents_not_searchable", "Tombstoned documents are absent from retrieval"
    ),
    DagsterCheckSpec(
        "tenant_isolation_leakage_zero", "Cross-tenant retrieval leakage remains zero"
    ),
)

__all__ = [
    "DagsterCheckSpec",
    "INGESTION_CHECKS",
    "QualityCheckResult",
    "check_acl_leakage",
    "check_high_risk_approved_citations",
    "check_baseline_regression",
    "check_chunk_count",
    "check_deleted_documents_not_searchable",
    "check_embedding_coverage",
    "check_parser_output_schema",
    "check_spreadsheet_citation_cell_ranges",
    "check_tenant_isolation",
    "manufacturing_quality_checks",
]
