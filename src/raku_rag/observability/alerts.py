"""T061 - alert rule catalog for platform observability."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertRule:
    name: str
    severity: str
    metric: str
    expression: str
    runbook: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "severity": self.severity,
            "metric": self.metric,
            "expression": self.expression,
            "runbook": self.runbook,
        }


ALERT_RULES: tuple[AlertRule, ...] = (
    AlertRule(
        name="acl_post_check_diff",
        severity="critical",
        metric="rag_acl_postcheck_diff_total",
        expression="increase(rag_acl_postcheck_diff_total[5m]) > 0",
        runbook="Investigate retrieval pre-filter and post-check mismatch; disable affected tenant profile.",
    ),
    AlertRule(
        name="deletion_reappearance",
        severity="critical",
        metric="rag_deleted_reappearance_total",
        expression="increase(rag_deleted_reappearance_total[5m]) > 0",
        runbook="Reapply tombstones, invalidate caches, and block affected collection until search is clean.",
    ),
    AlertRule(
        name="budget_exceed",
        severity="warning",
        metric="answer_requests_total",
        expression='increase(answer_requests_total{status="budget_exceeded"}[15m]) > 0',
        runbook="Review tenant budget policy and notify the application owner.",
    ),
    AlertRule(
        name="failed_jobs",
        severity="warning",
        metric="rag_stage_errors_total",
        expression='increase(rag_stage_errors_total{stage="ingestion"}[15m]) > 0',
        runbook="Open admin jobs, inspect failed ingestion runs, and retry safe candidates.",
    ),
    AlertRule(
        name="quality_regression",
        severity="critical",
        metric="rag_eval_gate_blocked_total",
        expression="increase(rag_eval_gate_blocked_total[1h]) > 0",
        runbook="Inspect evaluation run security checks and baseline comparison before promoting changes.",
    ),
)


def alert_rule_names() -> tuple[str, ...]:
    return tuple(rule.name for rule in ALERT_RULES)
