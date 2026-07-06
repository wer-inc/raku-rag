"""ADR-018 §14 Phase-0 — Golden ingestion-quality evaluator (deterministic, fixture-backed).

Release evaluation for the §8.4 extraction-quality gate. The PRIMARY metric is the false-accept rate
(§P5): gold cases that SHOULD be quarantined (mojibake / CID / empty) but the classifier waved through
as retrieval-eligible. That rate must stay 0 — the safety-first invariant of the whole ADR. A secondary
over-quarantine rate guards against a degenerate classifier that flags everything.

This mirrors eval/high_risk_recall.py: a small JSON corpus + a loader + a report. Real
representative-document curation and threshold tuning (OQ#2) extend this pack later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

from raku_rag.services.ingestion_quality import (
    EXTRACTION_QUALITY_STATUS_KEY,
    RETRIEVAL_BLOCKING_QUALITY_STATUSES,
    classify_text_extraction_quality,
)

DEFAULT_CORPUS_PATH = Path(__file__).resolve().parent / "fixtures" / "ingestion_quality_golden.json"

Classifier = Callable[..., Mapping[str, object]]


@dataclass(frozen=True)
class GoldenIngestionCase:
    case_id: str
    text: str
    gold_status: str
    content_type: str | None = None
    raw_size: int | None = None

    @property
    def effective_raw_size(self) -> int:
        return self.raw_size if self.raw_size is not None else max(1, len(self.text.encode("utf-8")))


@dataclass(frozen=True)
class IngestionQualityReport:
    version: str
    total: int
    gold_blocking_total: int
    gold_accepted_total: int
    false_accepts: tuple[str, ...] = ()
    over_quarantines: tuple[str, ...] = ()
    predicted: Mapping[str, str] = field(default_factory=dict)

    @property
    def false_accept_count(self) -> int:
        return len(self.false_accepts)

    @property
    def false_accept_rate(self) -> float:
        return self.false_accept_count / self.gold_blocking_total if self.gold_blocking_total else 0.0

    @property
    def over_quarantine_rate(self) -> float:
        return len(self.over_quarantines) / self.gold_accepted_total if self.gold_accepted_total else 0.0


def load_golden_ingestion_corpus(
    path: Path | str = DEFAULT_CORPUS_PATH,
) -> tuple[str, tuple[GoldenIngestionCase, ...]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    version = str(raw.get("version") or "unknown")
    cases = tuple(
        GoldenIngestionCase(
            case_id=str(item["case_id"]),
            text=str(item.get("text", "")),
            gold_status=str(item["gold_status"]),
            content_type=item.get("content_type"),
            raw_size=item.get("raw_size"),
        )
        for item in raw.get("cases") or ()
    )
    return version, cases


def _is_blocking(status: str) -> bool:
    return status in RETRIEVAL_BLOCKING_QUALITY_STATUSES


def evaluate_ingestion_quality(
    cases: Iterable[GoldenIngestionCase],
    *,
    version: str = "golden_ingestion.v1",
    classify: Classifier = classify_text_extraction_quality,
) -> IngestionQualityReport:
    cases = tuple(cases)
    false_accepts: list[str] = []
    over_quarantines: list[str] = []
    predicted: dict[str, str] = {}
    gold_blocking = 0
    gold_accepted = 0

    for case in cases:
        result = classify(
            case.text, raw_size=case.effective_raw_size, content_type=case.content_type
        )
        pred_status = str(result[EXTRACTION_QUALITY_STATUS_KEY])
        predicted[case.case_id] = pred_status
        gold_blocking_case = _is_blocking(case.gold_status)
        if gold_blocking_case:
            gold_blocking += 1
            if not _is_blocking(pred_status):
                false_accepts.append(case.case_id)  # §P5 primary failure
        else:
            gold_accepted += 1
            if _is_blocking(pred_status):
                over_quarantines.append(case.case_id)

    return IngestionQualityReport(
        version=version,
        total=len(cases),
        gold_blocking_total=gold_blocking,
        gold_accepted_total=gold_accepted,
        false_accepts=tuple(false_accepts),
        over_quarantines=tuple(over_quarantines),
        predicted=predicted,
    )


def run_default_golden_eval() -> IngestionQualityReport:
    version, cases = load_golden_ingestion_corpus()
    return evaluate_ingestion_quality(cases, version=version)
