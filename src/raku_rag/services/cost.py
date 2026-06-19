"""T021 — CostService + Budget (FR-032/034). Resolves prior-analyze C1: cost exists from MVP.

Records per-tenant/collection/query cost and enforces budget. On budget exhaustion the caller
returns ``budget_exceeded`` WITHOUT weakening groundedness or ACL (FR-034).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CostService:
    # tenant_id -> accumulated cost
    _spent: dict[str, float] = field(default_factory=dict)
    # tenant_id -> budget (None = unlimited)
    _budgets: dict[str, float] = field(default_factory=dict)

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

    def record(self, tenant_id: str, amount: float, kind: str = "query") -> dict:
        self._spent[tenant_id] = self._spent.get(tenant_id, 0.0) + amount
        return {"kind": kind, "amount": amount, "tenant_total": self._spent[tenant_id]}
