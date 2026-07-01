"""Deterministic query planning helpers for manufacturing-style RAG questions.

The planner is intentionally lightweight: it extracts safe structure that retrieval, diagnostics, and
eval can use without sending the raw query text into telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from raku_rag.core.hybrid_retrieval import lexical_query_terms, query_identifiers


@dataclass(frozen=True)
class QueryPlan:
    intent: str
    identifiers: tuple[str, ...]
    lexical_terms: tuple[str, ...]
    filter_hints: dict[str, tuple[str, ...]]
    rewrite_hints: tuple[str, ...]


HIGH_RISK_TERMS = (
    "loto",
    "lockout",
    "tagout",
    "electric shock",
    "live wire",
    "pressure test",
    "ロックアウト",
    "タグアウト",
    "感電",
    "活線",
    "高圧",
    "耐圧",
    "圧力容器",
    "薬液",
    "苛性",
    "naoh",
    "非常停止",
    "安全リレー",
    "pwht",
    "熱処理",
)
TROUBLESHOOTING_TERMS = (
    "cause",
    "countermeasure",
    "failure",
    "noise",
    "overheat",
    "leak",
    "crack",
    "原因",
    "対策",
    "異音",
    "発熱",
    "漏れ",
    "割れ",
    "不良",
    "故障",
    "トラブル",
    "ピンホール",
    "ヒケ",
    "ボイド",
    "摩耗",
)
PROCEDURE_TERMS = (
    "procedure",
    "step",
    "steps",
    "check",
    "inspect",
    "replace",
    "adjust",
    "手順",
    "やり方",
    "方法",
    "順番",
    "作業",
    "点検",
    "交換",
    "調整",
    "確認",
)
COMPARISON_TERMS = ("比較", "違い", "差分", "どちら", "vs", "versus")
AMBIGUOUS_REFERENTS = ("これ", "それ", "あれ", "この件", "その件")


def plan_query(query: str) -> QueryPlan:
    normalized = _normalize(query)
    identifiers = query_identifiers(query)
    terms = lexical_query_terms(query)
    intent = _intent(normalized, identifiers)
    filter_hints = _filter_hints(intent, identifiers, normalized)
    rewrite_hints = _rewrite_hints(identifiers, terms)
    return QueryPlan(
        intent=intent,
        identifiers=identifiers,
        lexical_terms=terms,
        filter_hints=filter_hints,
        rewrite_hints=rewrite_hints,
    )


def _intent(normalized: str, identifiers: tuple[str, ...]) -> str:
    if _contains_any(normalized, AMBIGUOUS_REFERENTS) and not identifiers and len(normalized) < 24:
        return "clarification"
    if _contains_any(normalized, HIGH_RISK_TERMS):
        return "safety_procedure"
    if _contains_any(normalized, TROUBLESHOOTING_TERMS):
        return "troubleshooting"
    if _contains_any(normalized, COMPARISON_TERMS):
        return "comparison"
    if _contains_any(normalized, PROCEDURE_TERMS):
        return "procedure"
    return "lookup"


def _filter_hints(
    intent: str, identifiers: tuple[str, ...], normalized: str
) -> dict[str, tuple[str, ...]]:
    hints: dict[str, tuple[str, ...]] = {"approval_state": ("approved_effective",)}
    if identifiers:
        hints["business_identifiers"] = identifiers
    if intent == "troubleshooting":
        hints["document_kind"] = ("trouble_case", "trouble_report", "quality_report")
    elif intent == "safety_procedure":
        hints["document_kind"] = ("safety", "work_instruction", "standard")
        hints["safety_scope"] = ("high_risk",)
    elif intent == "procedure":
        hints["document_kind"] = ("work_instruction", "standard", "inspection")
    elif intent == "comparison":
        hints["document_kind"] = ("standard", "inspection", "work_instruction")
    if re.search(r"\b[A-Z]{1,4}-?\d{1,4}\b", normalized, re.IGNORECASE):
        hints.setdefault("identifier_type", ("equipment_or_alarm_code",))
    return hints


def _rewrite_hints(identifiers: tuple[str, ...], terms: tuple[str, ...]) -> tuple[str, ...]:
    hints = list(identifiers)
    hints.extend(term for term in terms if term not in hints)
    return tuple(hints[:24])


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.casefold() in text for term in terms)


def _normalize(query: str) -> str:
    return " ".join(str(query or "").casefold().split())
