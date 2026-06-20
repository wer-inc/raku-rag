"""T021 — CostService + Budget (FR-032/034). Resolves prior-analyze C1: cost exists from MVP.

Records per-tenant/collection/query cost and enforces budget. On budget exhaustion the caller
returns ``budget_exceeded`` WITHOUT weakening groundedness or ACL (FR-034).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

VISUAL_COST_KINDS: tuple[str, ...] = (
    "ocr_cost",
    "layout_extraction_cost",
    "captioning_cost",
    "visual_embedding_cost",
    "vlm_image_tokens",
    "thumbnail_crop_generation_cost",
    "visual_storage_cost",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CostRecord:
    tenant_id: str
    kind: str
    amount: float
    trace_id: str = ""
    collection_id: str = ""
    query_id: str = ""
    job_id: str = ""
    quantity: int = 0
    unit: str = ""
    billable: bool = True
    created_at: str = field(default_factory=_now)
    metadata: dict = field(default_factory=dict)


@dataclass
class CostService:
    # tenant_id -> accumulated cost
    _spent: dict[str, float] = field(default_factory=dict)
    # tenant_id -> budget (None = unlimited)
    _budgets: dict[str, float] = field(default_factory=dict)
    _records: list[CostRecord] = field(default_factory=list)

    def set_budget(self, tenant_id: str, budget: float | None) -> None:
        if budget is None:
            self._budgets.pop(tenant_id, None)
        else:
            self._budgets[tenant_id] = budget

    def would_exceed(self, tenant_id: str, estimated: float) -> bool:
        budget = self._budgets.get(tenant_id)
        if budget is None:
            return False
        return self._spent.get(tenant_id, 0.0) + estimated > budget

    def record(
        self,
        tenant_id: str,
        amount: float,
        kind: str = "query",
        *,
        trace_id: str = "",
        collection_id: str = "",
        query_id: str = "",
        job_id: str = "",
        quantity: int = 0,
        unit: str = "",
        billable: bool = True,
        metadata: dict | None = None,
    ) -> dict:
        if billable:
            self._spent[tenant_id] = self._spent.get(tenant_id, 0.0) + amount
        else:
            self._spent.setdefault(tenant_id, self._spent.get(tenant_id, 0.0))
        record = CostRecord(
            tenant_id=tenant_id,
            kind=kind,
            amount=amount,
            trace_id=trace_id,
            collection_id=collection_id,
            query_id=query_id,
            job_id=job_id,
            quantity=quantity,
            unit=unit,
            billable=billable,
            metadata=dict(metadata or {}),
        )
        self._records.append(record)
        return {"kind": kind, "amount": amount, "tenant_total": self._spent.get(tenant_id, 0.0)}

    def record_tokens(
        self,
        tenant_id: str,
        *,
        kind: str,
        tokens: int,
        trace_id: str = "",
        collection_id: str = "",
        query_id: str = "",
        job_id: str = "",
        metadata: dict | None = None,
    ) -> CostRecord:
        self.record(
            tenant_id,
            0.0,
            kind=kind,
            trace_id=trace_id,
            collection_id=collection_id,
            query_id=query_id,
            job_id=job_id,
            quantity=max(0, tokens),
            unit="tokens",
            billable=False,
            metadata=metadata,
        )
        return self._records[-1]

    def record_visual_cost(
        self,
        tenant_id: str,
        *,
        kind: str,
        amount: float,
        collection_id: str = "",
        query_id: str = "",
        job_id: str = "",
        trace_id: str = "",
        quantity: int = 0,
        unit: str = "",
        metadata: dict | None = None,
        billable: bool = True,
    ) -> CostRecord:
        if kind not in VISUAL_COST_KINDS:
            raise ValueError(f"unknown visual cost kind: {kind}")
        self.record(
            tenant_id,
            max(0.0, amount),
            kind=kind,
            trace_id=trace_id,
            collection_id=collection_id,
            query_id=query_id,
            job_id=job_id,
            quantity=max(0, quantity),
            unit=unit,
            billable=billable,
            metadata=metadata,
        )
        return self._records[-1]

    def records(self, tenant_id: str | None = None, *, kind: str = "") -> tuple[CostRecord, ...]:
        records = self._records
        if tenant_id is not None:
            records = [record for record in records if record.tenant_id == tenant_id]
        if kind:
            records = [record for record in records if record.kind == kind]
        return tuple(records)
