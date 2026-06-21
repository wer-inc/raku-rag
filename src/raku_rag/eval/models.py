"""T056 - evaluation set/run models with registration-time redaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Iterable, Mapping

from raku_rag.domain.models import BoundingBox
from raku_rag.observability.redaction import Redactor


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:16]}"


@dataclass(frozen=True)
class ExpectedEvidence:
    document_id: str
    chunk_id: str = ""
    kind: str = "text"
    asset_id: str = ""
    region_id: str = ""
    bbox: BoundingBox | None = None


@dataclass(frozen=True)
class EvaluationItem:
    question: str
    expected_answer: str = ""
    expected_evidence: tuple[ExpectedEvidence, ...] = ()
    item_id: str = ""

    @classmethod
    def from_mapping(
        cls, data: Mapping[str, object], redactor: Redactor | None = None
    ) -> "EvaluationItem":
        redactor = redactor or Redactor()
        question = redactor.redact(str(data.get("question") or ""))
        expected_answer = redactor.redact(str(data.get("expected_answer") or ""))
        evidence = []
        for raw in data.get("expected_evidence") or ():
            if isinstance(raw, str):
                evidence.append(ExpectedEvidence(document_id=raw))
            else:
                item = dict(raw)
                evidence.append(
                    ExpectedEvidence(
                        document_id=str(item.get("document_id") or ""),
                        chunk_id=str(item.get("chunk_id") or ""),
                        kind=str(item.get("kind") or "text"),
                        asset_id=str(item.get("asset_id") or ""),
                        region_id=str(item.get("region_id") or ""),
                        bbox=_bbox_from_mapping(item.get("bbox")),
                    )
                )
        item_id = str(data.get("item_id") or "") or _stable_id(
            "eval_item", [question, expected_answer, [e.__dict__ for e in evidence]]
        )
        return cls(
            question=question,
            expected_answer=expected_answer,
            expected_evidence=tuple(evidence),
            item_id=item_id,
        )


@dataclass(frozen=True)
class EvaluationSet:
    eval_set_id: str
    tenant_id: str
    items: tuple[EvaluationItem, ...]
    created_at: str = field(default_factory=_now)

    @classmethod
    def register(
        cls,
        *,
        tenant_id: str,
        items: Iterable[Mapping[str, object]],
        eval_set_id: str = "",
        redactor: Redactor | None = None,
    ) -> "EvaluationSet":
        redactor = redactor or Redactor()
        scrubbed = tuple(EvaluationItem.from_mapping(item, redactor) for item in items)
        set_id = eval_set_id or _stable_id(
            "eval_set",
            [tenant_id, [item.item_id for item in scrubbed]],
        )
        return cls(eval_set_id=set_id, tenant_id=tenant_id, items=scrubbed)


@dataclass(frozen=True)
class EvaluationExampleResult:
    item_id: str
    answer_status: str
    cited_document_ids: tuple[str, ...]
    retrieved_document_ids: tuple[str, ...]
    latency_ms: float
    query_cost: float
    cited_asset_ids: tuple[str, ...] = ()
    retrieved_asset_ids: tuple[str, ...] = ()
    cited_region_ids: tuple[str, ...] = ()
    retrieved_region_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationRun:
    run_id: str
    eval_set_id: str
    tenant_id: str
    status: str
    baseline: bool = False
    metrics: dict = field(default_factory=dict)
    baseline_comparison: dict = field(default_factory=dict)
    security_checks: dict = field(default_factory=dict)
    gate_result: str = "passed"
    examples: tuple[EvaluationExampleResult, ...] = ()
    probe_results: tuple[dict, ...] = ()
    probes_executed: bool = False
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "eval_set_id": self.eval_set_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "baseline": self.baseline,
            "metrics": dict(self.metrics),
            "baseline_comparison": dict(self.baseline_comparison),
            "security_checks": dict(self.security_checks),
            "gate_result": self.gate_result,
            "examples": [example.__dict__ for example in self.examples],
            "probe_results": [dict(result) for result in self.probe_results],
            "probes_executed": self.probes_executed,
            "created_at": self.created_at,
        }


def _bbox_from_mapping(raw: object) -> BoundingBox | None:
    if isinstance(raw, BoundingBox):
        return raw
    if not isinstance(raw, Mapping):
        return None
    return BoundingBox(
        x=float(raw.get("x", 0.0) or 0.0),
        y=float(raw.get("y", 0.0) or 0.0),
        width=float(raw.get("width", 0.0) or 0.0),
        height=float(raw.get("height", 0.0) or 0.0),
    )
