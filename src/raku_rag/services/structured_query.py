"""Structured/numeric query routing guard.

RAG can explain tables and cite rows, but it must not pretend vector retrieval is a database for
aggregation, ranking, exact numeric filters, or latest-value queries. This module classifies those
requests before retrieval so the answer path can refuse unless a structured tool is explicitly wired.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Mapping

from raku_rag.domain.models import IdentityClaims


@dataclass(frozen=True)
class StructuredQueryDecision:
    route: str
    reason: str = ""

    @property
    def requires_tool(self) -> bool:
        return self.route == "refused_structured_tool_required"


_AGGREGATION_RE = re.compile(r"\b(sum|average|avg|median|percentile)\b", re.I)
_TOTAL_OR_COUNT_RE = re.compile(r"\b(total|count)\b", re.I)
_AGGREGATION_CONTEXT_RE = re.compile(
    r"\b(by|per|across|overall|all|each|grouped\s+by|records?|rows?|defects?|"
    r"incidents?|tickets?|orders?|downtime|amounts?|costs?|sales)\b",
    re.I,
)

_STRUCTURED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ranking", re.compile(r"\b(top\s+\d+|highest|lowest|rank|ranking|most|least)\b", re.I)),
    ("latest_value", re.compile(r"\b(latest|newest|current value|last\s+\d+\s+days)\b", re.I)),
    (
        "numeric_comparison",
        # Bare "=" is NOT a comparison trigger: spec-style prose quotes parameters as assignments
        # ("AQL 1.0 で n=125、Ac=3") and must stay on the RAG route; the tool only implements </>
        # filtering anyway.
        re.compile(r"[<>]=?\s*\d|\b(greater|less|above|below|between)\b", re.I),
    ),
    (
        "period_filter",
        re.compile(r"\b(from|between|during|since|until)\s+\d{4}(?:[-/]\d{1,2})?", re.I),
    ),
    # 「いくつ」 is generic value-lookup Japanese ("AQL はいくつですか" = "what is the AQL?"), not an
    # aggregation request — routing it here starves RAG of answerable lookups.
    ("aggregation_ja", re.compile(r"(合計|平均|件数|集計|中央値|何件)")),
    ("ranking_ja", re.compile(r"(ランキング|上位|下位|最大|最小|最も多い|最も少ない)")),
    ("latest_ja", re.compile(r"(最新値|最新の値|直近|現在値)")),
    ("numeric_comparison_ja", re.compile(r"\d+\s*(以上|以下|超|未満|より大きい|より小さい)")),
    ("period_filter_ja", re.compile(r"(期間|以降|以前|から|まで).*\d{4}")),
)


def classify_structured_query(
    query: str, *, tool_available: bool = False
) -> StructuredQueryDecision:
    q = (query or "").strip()
    if not q:
        return StructuredQueryDecision(route="rag")
    if _is_aggregation_request(q):
        return StructuredQueryDecision(
            route="structured_tool" if tool_available else "refused_structured_tool_required",
            reason="aggregation",
        )
    for reason, pattern in _STRUCTURED_PATTERNS:
        if pattern.search(q):
            return StructuredQueryDecision(
                route="structured_tool" if tool_available else "refused_structured_tool_required",
                reason=reason,
            )
    return StructuredQueryDecision(route="rag")


def _is_aggregation_request(query: str) -> bool:
    if _AGGREGATION_RE.search(query):
        return True
    # "total" and "count" are often fields in invoices/estimates/reports. Treat them as structured
    # aggregation only when the query asks across rows, records, groups, or a measurable dataset.
    return bool(_TOTAL_OR_COUNT_RE.search(query) and _AGGREGATION_CONTEXT_RE.search(query))


SqlExecutor = Callable[[str, Mapping[str, object], float, int], list[Mapping[str, object]]]


class ReadOnlySqlTool:
    """Read-only SQL boundary for future structured tools.

    It only accepts allowlisted datasource IDs, trusted query templates, SELECT statements, a tenant
    parameter, a timeout, and a row limit. User text should select a template; it must never become raw
    SQL at this boundary.
    """

    def __init__(
        self,
        executors: Mapping[str, SqlExecutor],
        *,
        timeout_seconds: float = 2.0,
        row_limit: int = 100,
    ) -> None:
        self._executors = dict(executors)
        self._timeout_seconds = timeout_seconds
        self._row_limit = row_limit

    def execute(
        self,
        *,
        principal: IdentityClaims,
        datasource_id: str,
        sql: str,
        params: Mapping[str, object] | None = None,
        trusted_template_id: str = "",
    ) -> list[Mapping[str, object]]:
        if datasource_id not in self._executors:
            raise PermissionError("datasource_not_allowlisted")
        if not trusted_template_id:
            raise PermissionError("trusted_template_required")
        statement = sql.strip()
        if not re.match(r"^select\b", statement, flags=re.I):
            raise PermissionError("select_only")
        if ";" in statement.rstrip(";"):
            raise PermissionError("single_statement_only")
        if not re.search(r"(:tenant_id|%\(tenant_id\)s|\$tenant_id)", statement):
            raise PermissionError("tenant_scope_required")
        scoped_params = dict(params or {})
        scoped_params["tenant_id"] = principal.tenant_id
        rows = self._executors[datasource_id](
            statement, scoped_params, self._timeout_seconds, self._row_limit
        )
        return list(rows)[: self._row_limit]
