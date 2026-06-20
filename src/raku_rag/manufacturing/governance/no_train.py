"""T010 — in-memory, tenant-scoped DataUsePolicyStore + default seed (data-model §G, GQ1/GQ2).

Implements the §7 ``DataUsePolicyStore`` ABC from ``raku_rag.manufacturing.interfaces``.

Behaviour (no new authz — 001 tenancy is reused for scoping):
- Each tenant gets the GQ1/GQ2-resolved safe-posture default on first ``get`` (auto-seeded):
  ``no_train_default=True``, ``training_opt_in=False``, ``provider_no_train_required=True``,
  ``no_train_fallback=block``, ``retention_customer=365``, ``retention_audit=365``.
- ``update`` applies a partial patch, validates the opt-in invariant, and bumps ``policy_version``
  on every accepted change (FR-MFG-019 — explainable, versioned policy).
- INVARIANT (FR-MFG-018): ``training_opt_in=True`` requires a non-empty ``opt_in_contract_ref``;
  otherwise a ``ValueError`` is raised and the stored policy is left unchanged.

stdlib only — in-memory dict keyed by tenant_id. Audit emission is stage-2 wiring; the store
returns the new ``DataUsePolicy`` so the caller can record the change via AuditLogWriter.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.policy import DataUsePolicy, NoTrainFallback
from raku_rag.manufacturing.interfaces import DataUsePolicyStore, NoTrainGuard

# Fields a tenant admin may patch via ``update``. ``tenant_id`` / ``policy_version`` are not
# externally settable — the store owns identity and versioning.
_PATCHABLE_FIELDS = frozenset(
    {
        "no_train_default",
        "training_opt_in",
        "opt_in_contract_ref",
        "provider_no_train_required",
        "no_train_fallback",
        "retention_customer",
        "retention_audit",
        "export_enabled",
        "updated_by",
        "updated_at",
    }
)


def default_policy(tenant_id: str) -> DataUsePolicy:
    """GQ1/GQ2-resolved safe-posture default policy for a tenant (initial ``policy_version='1'``)."""
    return DataUsePolicy(
        tenant_id=tenant_id,
        no_train_default=True,  # FR-MFG-016
        training_opt_in=False,  # FR-MFG-018
        opt_in_contract_ref=None,
        provider_no_train_required=True,  # FR-MFG-017
        no_train_fallback=NoTrainFallback.BLOCK,  # GQ1
        retention_customer=365,  # GQ2
        retention_audit=365,  # GQ2
        export_enabled=False,
        policy_version="1",
    )


def _validate(policy: DataUsePolicy) -> None:
    """Enforce the opt-in invariant (FR-MFG-018) before a policy is persisted."""
    if policy.training_opt_in and not (policy.opt_in_contract_ref or "").strip():
        raise ValueError(
            "training_opt_in=True requires a non-empty opt_in_contract_ref (FR-MFG-018)"
        )


class InMemoryDataUsePolicyStore(DataUsePolicyStore):
    """In-memory, tenant-scoped ``DataUsePolicyStore`` (data-model §G)."""

    def __init__(self) -> None:
        self._by_tenant: dict[str, DataUsePolicy] = {}

    def get(self, tenant_id: str) -> DataUsePolicy:
        """Return the tenant policy, auto-seeding the safe default on first access."""
        policy = self._by_tenant.get(tenant_id)
        if policy is None:
            policy = default_policy(tenant_id)
            self._by_tenant[tenant_id] = policy
        return copy.copy(policy)

    def update(self, tenant_id: str, patch: dict, actor: IdentityClaims) -> DataUsePolicy:
        """Apply a partial patch, validate the opt-in invariant, and bump ``policy_version``.

        The patch is validated against the *resulting* policy; an invalid patch raises and the
        stored policy is left untouched. ``policy_version`` increments on every accepted change
        (FR-MFG-019). Returns the new policy for the caller to audit (FR-MFG-019/021).
        """
        unknown = set(patch) - _PATCHABLE_FIELDS
        if unknown:
            raise ValueError(f"non-patchable field(s): {sorted(unknown)}")

        current = self.get(tenant_id)
        candidate = copy.copy(current)
        for key, value in patch.items():
            setattr(candidate, key, value)

        # Identity / versioning are owned by the store, never the patch.
        candidate.tenant_id = tenant_id
        candidate.policy_version = _next_version(current.policy_version)
        if actor is not None and patch.get("updated_by") is None:
            candidate.updated_by = actor.user_id

        _validate(candidate)  # raises before persisting — stored policy unchanged on failure
        self._by_tenant[tenant_id] = candidate
        return copy.copy(candidate)


def _next_version(current: str) -> str:
    """Monotonically increment a numeric policy_version string (``''``/non-numeric -> ``'1'``→``'2'``)."""
    try:
        return str(int(current) + 1)
    except (TypeError, ValueError):
        return "2"


# --- T057: NoTrainGuard — opt-in enforcement + capability availability (GQ1) ---------------------
#
# Surfaced status for a capability whose only available providers are NOT no-train-guaranteed while
# ``provider_no_train_required`` is set: GQ1 = BLOCK (capability-origin), NOT a silent degrade.
CAPABILITY_OK = "ok"
CAPABILITY_BLOCKED = "temporarily_unavailable"


class NoTrainViolation(PermissionError):
    """Raised when customer data would be used for training/improvement without a valid opt-in."""


class InMemoryNoTrainGuard(NoTrainGuard):
    """T057 — minimal local NoTrainGuard (FR-MFG-016/017/018/029, SC-MFG-009, GQ1).

    Provider no-train *capability verification* is Base CR-001-B (001's job); this guard enforces the
    002 POLICY against an INJECTED provider-capability map:
      - ``assert_no_train`` REFUSES (raises) unless the tenant policy has ``training_opt_in=True`` AND
        a non-empty ``opt_in_contract_ref`` (FR-MFG-018). The default policy refuses (SC-MFG-009 = 0
        accepted training uses without opt-in).
      - ``capability_allowed`` is False when ``provider_no_train_required`` is set and NO available
        provider for the capability is in the injected no-train-guaranteed set (GQ1 = block); True
        when at least one available provider is no-train-guaranteed. An unknown capability with no
        providers is treated as having no no-train provider => blocked under the no-train requirement.

    Tenant-scoped via the reused per-tenant ``DataUsePolicyStore``; no new authz mechanism.
    """

    def __init__(
        self,
        store: DataUsePolicyStore,
        *,
        provider_capabilities: Mapping[str, Iterable[str]] | None = None,
        no_train_providers: Iterable[str] | None = None,
    ) -> None:
        self._store = store
        self._caps: dict[str, tuple[str, ...]] = {
            cap: tuple(providers) for cap, providers in (provider_capabilities or {}).items()
        }
        self._no_train_providers: frozenset[str] = frozenset(no_train_providers or ())

    def assert_no_train(self, tenant_id: str, data_kind: str) -> None:
        """Forbid training/improvement use without an explicit, contract-backed admin opt-in."""
        policy = self._store.get(tenant_id)
        if not (policy.training_opt_in and (policy.opt_in_contract_ref or "").strip()):
            raise NoTrainViolation(
                f"customer data may not be used for training/improvement "
                f"(data_kind={data_kind!r}): tenant has no valid admin opt-in (SC-MFG-009, FR-MFG-018)"
            )

    def capability_allowed(self, tenant_id: str, capability: str) -> bool:
        """False when no-train is required and no no-train-guaranteed provider serves the capability."""
        policy = self._store.get(tenant_id)
        if not policy.provider_no_train_required:
            return True
        providers = self._caps.get(capability, ())
        return any(p in self._no_train_providers for p in providers)

    def capability_status(self, tenant_id: str, capability: str) -> str:
        """GQ1: blocked capability surfaces ``temporarily_unavailable`` (no inferred answer)."""
        return (
            CAPABILITY_OK if self.capability_allowed(tenant_id, capability) else CAPABILITY_BLOCKED
        )

    def resolve_capability_provider(self, tenant_id: str, capability: str) -> str | None:
        """Return a no-train-guaranteed provider for the capability, or None when blocked (GQ1).

        NEVER returns a non-no-train provider for a blocked capability — no silent degrade. When the
        capability is allowed, returns the first available no-train-guaranteed provider.
        """
        if not self.capability_allowed(tenant_id, capability):
            return None
        for provider in self._caps.get(capability, ()):
            if provider in self._no_train_providers:
                return provider
        return None
