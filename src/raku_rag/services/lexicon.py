"""★V2 LexiconService — DEFAULTS ⊕ tenant overrides, additive by construction.

Resolution merges the caller-supplied defaults with the tenant's stored entries: per-key values
are UNIONed and unknown keys are added, so built-in vocabulary can be EXTENDED but never removed
— a tenant can widen danger detection, never weaken it (the safety invariant is structural, not a
policy check). Values are short vocabulary strings / message text; never document content.
"""

from __future__ import annotations

from typing import Mapping

# Namespaces a tenant_admin may edit through the public API. Anything else is rejected so the
# lexicon cannot become a general-purpose config backdoor.
EDITABLE_NAMESPACES: frozenset[str] = frozenset(
    {
        "safety.high_risk_keywords",
        "chat.handoff_triggers",
        "phone.intents",
        "messages.chat",
        "messages.phone",
    }
)
_MAX_VALUES_PER_KEY = 200
_MAX_VALUE_LENGTH = 200


class LexiconError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class LexiconService:
    def __init__(self, repository, *, audit=None) -> None:
        self._repo = repository
        self._audit = audit

    def resolve(
        self,
        tenant_id: str,
        namespace: str,
        defaults: Mapping[str, tuple[str, ...]] | None = None,
    ) -> dict[str, tuple[str, ...]]:
        merged: dict[str, tuple[str, ...]] = {
            key: tuple(values) for key, values in (defaults or {}).items()
        }
        for key, values in self._repo.get_namespace(tenant_id, namespace).items():
            base = merged.get(key, ())
            extras = tuple(v for v in values if v not in base)
            merged[key] = (*base, *extras)
        return merged

    def entries(self, tenant_id: str, namespace: str) -> dict[str, tuple[str, ...]]:
        """Tenant-stored overrides only (what the admin API shows/edits)."""
        return self._repo.get_namespace(tenant_id, namespace)

    def update(
        self,
        tenant_id: str,
        namespace: str,
        key: str,
        values: list[str],
        *,
        actor_id: str,
    ) -> tuple[str, ...]:
        if namespace not in EDITABLE_NAMESPACES:
            raise LexiconError("unknown_namespace")
        if not key or len(key) > 100:
            raise LexiconError("invalid_key")
        cleaned = tuple(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))
        if not cleaned:
            raise LexiconError("values_required")
        if len(cleaned) > _MAX_VALUES_PER_KEY or any(len(v) > _MAX_VALUE_LENGTH for v in cleaned):
            raise LexiconError("values_too_large")
        self._repo.upsert(tenant_id, namespace, key, cleaned, actor_id)
        self._record_audit(tenant_id, actor_id, namespace, key, len(cleaned), "updated")
        return cleaned

    def remove(self, tenant_id: str, namespace: str, key: str, *, actor_id: str) -> bool:
        if namespace not in EDITABLE_NAMESPACES:
            raise LexiconError("unknown_namespace")
        removed = self._repo.delete(tenant_id, namespace, key)
        if removed:
            # Removing a tenant OVERRIDE only ever falls back to built-in defaults — it can
            # never remove default vocabulary (resolution starts from defaults).
            self._record_audit(tenant_id, actor_id, namespace, key, 0, "removed")
        return removed

    def _record_audit(
        self, tenant_id: str, actor_id: str, namespace: str, key: str, count: int, decision: str
    ) -> None:
        if self._audit is None:
            return
        try:
            from raku_rag.manufacturing.api.audit import _now as _audit_now
            from raku_rag.manufacturing.domain.audit import AuditLogEntry

            self._audit.record(
                AuditLogEntry(
                    tenant_id=tenant_id,
                    log_id=f"lexicon:{namespace}:{key}:{_audit_now()}",
                    timestamp=_audit_now(),
                    actor_id=actor_id,
                    action="lexicon.updated",
                    resource_type="tenant_lexicon",
                    resource_id=f"{namespace}/{key}",
                    decision=decision,
                    reason=f"values={count}",
                )
            )
        except Exception:  # noqa: BLE001 — audit best-effort must not break the request
            pass
