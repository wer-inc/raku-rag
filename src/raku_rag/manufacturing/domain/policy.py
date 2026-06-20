"""T006 — DataUsePolicy + RetentionConfig (data-model §G, FR-MFG-016~020/029, GQ1/GQ2).

Per-tenant data-use governance, explainable in sales / admin / audit (``policy_version`` required).
Defaults encode the safety posture: no-train ON, opt-in OFF, provider no-train REQUIRED, and a
``block`` fallback when no no-train-guaranteed provider exists for a capability (GQ1).

Field names intentionally expose both the short task aliases and the data-model long names so
stage-2 stores can pick either; ``no_train_default`` etc. are the canonical attributes here.

Schema + enums only — no enforcement (stage-2 DataUsePolicyStore / NoTrainGuard / RetentionManager).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NoTrainFallback(str, Enum):
    """GQ1: capability without a no-train-guaranteed provider is unavailable by default."""

    BLOCK = "block"


@dataclass(frozen=True)
class RetentionConfig:
    """Effective retention returned by RetentionManager (contracts §7). Guide range 30–3650 days."""

    tenant_id: str
    retention_customer_days: int = 365  # GQ2 default
    retention_audit_days: int = 365  # GQ2 default


@dataclass
class DataUsePolicy:
    """Tenant data-use policy (data-model §G). Defaults are the GQ1/GQ2-resolved safe posture."""

    tenant_id: str
    no_train_default: bool = True  # FR-MFG-016 — true by default (fixed default)
    training_opt_in: bool = False  # FR-MFG-018 — admin explicit opt-in + separate contract
    opt_in_contract_ref: str | None = None
    provider_no_train_required: bool = True  # FR-MFG-017
    no_train_fallback: NoTrainFallback = NoTrainFallback.BLOCK  # GQ1
    retention_customer: int = 365  # retention_period_customer_days; GQ2; tenant-overridable
    retention_audit: int = 365  # retention_period_audit_days; GQ2; tenant-overridable
    export_enabled: bool = False
    policy_version: str = ""
    updated_by: str | None = None
    updated_at: str | None = None
