"""T058 — RetentionManager: effective retention + expiry delegation (FR-MFG-020, GQ2).

Per-tenant data retention governance built ON TOP of the 001 deletion/tombstone path. This layer
defines NO new deletion mechanism: ``expire`` resolves which documents are past their retention
window and delegates the actual removal to the reused 001 ``DeletionService`` (tombstone + cascade,
SC-003). It only OWNS the policy (how long) — the 001 tombstone owns the how.

Defaults (GQ2-resolved): customer data 365 days / audit 365 days. A tenant admin may override via the
``DataUsePolicy`` (``retention_customer`` / ``retention_audit``); the guide range is 30..3650 days
(an out-of-range override is clamped into the guide band — the policy is advisory guidance, not a
hard reject, so a misconfiguration fails safe to the bounded value).

stdlib only — in-memory; structurally satisfies ``raku_rag.manufacturing.interfaces.RetentionManager``.
"""

from __future__ import annotations

from raku_rag.manufacturing.domain.policy import RetentionConfig
from raku_rag.manufacturing.interfaces import DataUsePolicyStore, RetentionManager

# Guide range for a tenant retention override (days). Out-of-range values clamp into this band.
RETENTION_MIN_DAYS = 30
RETENTION_MAX_DAYS = 3650


def _clamp(days: int, *, default: int) -> int:
    """Clamp a retention value into the guide band, falling back to ``default`` if not an int."""
    try:
        value = int(days)
    except (TypeError, ValueError):
        return default
    return max(RETENTION_MIN_DAYS, min(RETENTION_MAX_DAYS, value))


class InMemoryRetentionManager(RetentionManager):
    """Effective retention resolver (GQ2 defaults) with expiry delegated to the 001 tombstone path.

    Reuses the per-tenant ``DataUsePolicyStore`` for the (overridable) retention values and the 001
    ``DeletionService`` for the actual expiry (tombstone + cascade). No new deletion mechanism.
    """

    def __init__(self, store: DataUsePolicyStore, *, deletion=None) -> None:
        self._store = store
        self._deletion = (
            deletion  # 001 DeletionService (tombstone/cascade); optional for resolution
        )

    def effective_retention(self, tenant_id: str) -> RetentionConfig:
        """Return the tenant's effective retention (default 365/365, GQ2; override clamped to guide)."""
        policy = self._store.get(tenant_id)
        return RetentionConfig(
            tenant_id=tenant_id,
            retention_customer_days=_clamp(policy.retention_customer, default=365),
            retention_audit_days=_clamp(policy.retention_audit, default=365),
        )

    def expire_document(self, tenant_id: str, document_id: str):
        """Expire (delete) a document past its retention window via the reused 001 tombstone path.

        Delegates to the 001 ``DeletionService`` (tombstone + cascade); a deleted document never
        reappears in search/answer/citation (SC-003). Raises if no deletion service was wired.
        """
        if self._deletion is None:
            raise RuntimeError("RetentionManager has no DeletionService wired for expiry")
        return self._deletion.delete(tenant_id, document_id)
