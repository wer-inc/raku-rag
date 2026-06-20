"""Manufacturing Dagster-compatible quality checks."""

from __future__ import annotations

from typing import Iterable, Mapping

from raku_rag.dagster.checks.quality import (
    QualityCheckResult,
    check_acl_leakage,
    check_baseline_regression,
    check_deleted_documents_not_searchable,
    check_spreadsheet_citation_cell_ranges,
    check_tenant_isolation,
)


def check_high_risk_approved_citations(decisions: Iterable[object]) -> QualityCheckResult:
    """High-risk answers must either block or carry at least one approved/effective citation."""

    violations: list[str] = []
    total = 0
    for index, decision in enumerate(decisions):
        high_risk = _get_bool(decision, "high_risk")
        if not high_risk:
            continue
        total += 1
        blocked_reason = _get(decision, "safety_block_reason")
        approved = _get_bool(decision, "approved_effective_citation_present")
        if not approved and not blocked_reason:
            violations.append(str(_get(decision, "query_id") or index))
    return QualityCheckResult(
        name="manufacturing_high_risk_approved_citation_requirement",
        passed=not violations,
        value=total - len(violations),
        threshold=total,
        reason="" if not violations else f"missing approved citations: {','.join(violations)}",
    )


def manufacturing_quality_checks(
    *,
    safety_decisions: Iterable[object] = (),
    acl_leakage_count: int = 0,
    tenant_isolation_leakage_count: int = 0,
    deleted_document_ids: Iterable[str] = (),
    retrieved_document_ids: Iterable[str] = (),
    citations: Iterable[object] = (),
    metrics: Mapping[str, float] | None = None,
    baseline_metrics: Mapping[str, float] | None = None,
    recall_drop_tolerance: float = 0.0,
    citation_drop_tolerance: float = 0.0,
) -> tuple[QualityCheckResult, ...]:
    """Return the complete manufacturing quality-check bundle from T071a."""

    return (
        check_high_risk_approved_citations(safety_decisions),
        check_acl_leakage(acl_leakage_count),
        check_tenant_isolation(tenant_isolation_leakage_count),
        check_deleted_documents_not_searchable(deleted_document_ids, retrieved_document_ids),
        check_spreadsheet_citation_cell_ranges(citations),
        check_baseline_regression(
            dict(metrics or {}),
            dict(baseline_metrics or {}),
            recall_drop_tolerance=recall_drop_tolerance,
            citation_drop_tolerance=citation_drop_tolerance,
        ),
    )


def _get(item: object, key: str) -> object:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def _get_bool(item: object, key: str) -> bool:
    return bool(_get(item, key))


__all__ = [
    "check_high_risk_approved_citations",
    "manufacturing_quality_checks",
]
