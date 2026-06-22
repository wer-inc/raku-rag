"""High-risk recall evaluator for the manufacturing safety boundary.

This is intentionally deterministic and fixture-backed: release evaluation should catch a classifier
that misses known dangerous phrasings, and should also catch a degenerate implementation that marks
every benign question high-risk.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Mapping

from raku_rag.manufacturing.safety.classifier import RuleHighRiskClassifier

DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parent / "fixtures" / ("high_risk_adversarial_corpus.json")
)


@dataclass(frozen=True)
class HighRiskRecallCase:
    case_id: str
    query: str
    intent_hint: str | None = None
    expected_reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class HighRiskRecallReport:
    corpus_version: str
    dangerous_total: int
    benign_total: int
    missed_dangerous: tuple[str, ...] = ()
    wrong_reason: tuple[str, ...] = ()
    benign_false_positive: tuple[str, ...] = ()

    @property
    def leakage_count(self) -> int:
        return len(self.missed_dangerous) + len(self.wrong_reason) + len(self.benign_false_positive)


def load_high_risk_corpus(
    path: Path | str = DEFAULT_CORPUS_PATH,
) -> tuple[str, tuple[HighRiskRecallCase, ...], tuple[HighRiskRecallCase, ...]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    version = str(raw.get("version") or "unknown")
    dangerous = tuple(_case_from_mapping(item) for item in raw.get("dangerous") or ())
    benign = tuple(_case_from_mapping(item) for item in raw.get("benign") or ())
    return version, dangerous, benign


def evaluate_high_risk_recall(
    classifier: object | None = None,
    *,
    dangerous: Iterable[HighRiskRecallCase] | None = None,
    benign: Iterable[HighRiskRecallCase] | None = None,
    corpus_path: Path | str = DEFAULT_CORPUS_PATH,
) -> HighRiskRecallReport:
    version, default_dangerous, default_benign = load_high_risk_corpus(corpus_path)
    dangerous_cases = tuple(default_dangerous if dangerous is None else dangerous)
    benign_cases = tuple(default_benign if benign is None else benign)
    clf = classifier or RuleHighRiskClassifier()

    missed: list[str] = []
    wrong_reason: list[str] = []
    false_positive: list[str] = []

    for case in dangerous_cases:
        result = clf.classify(case.query, [], intent_hint=case.intent_hint)
        if not getattr(result, "is_high_risk", False):
            missed.append(case.case_id)
            continue
        if case.expected_reason_codes:
            reason_codes = set(getattr(result, "reason_codes", ()) or ())
            if not reason_codes.intersection(case.expected_reason_codes):
                wrong_reason.append(case.case_id)

    for case in benign_cases:
        result = clf.classify(case.query, [], intent_hint=case.intent_hint)
        if getattr(result, "is_high_risk", False):
            false_positive.append(case.case_id)

    return HighRiskRecallReport(
        corpus_version=version,
        dangerous_total=len(dangerous_cases),
        benign_total=len(benign_cases),
        missed_dangerous=tuple(missed),
        wrong_reason=tuple(wrong_reason),
        benign_false_positive=tuple(false_positive),
    )


def _case_from_mapping(raw: Mapping[str, object]) -> HighRiskRecallCase:
    return HighRiskRecallCase(
        case_id=str(raw.get("id") or ""),
        query=str(raw.get("query") or ""),
        intent_hint=(str(raw["intent_hint"]) if raw.get("intent_hint") else None),
        expected_reason_codes=tuple(str(code) for code in raw.get("expected_reason_codes") or ()),
    )
