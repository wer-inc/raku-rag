"""Runtime helpers for applying tenant provider policy before cloud bytes egress.

The policy model itself lives in ``workers.ingest.provider_policy`` so workers and production
adapters share one contract. This module is the small runtime bridge for providers that are selected
inside the structured parser path instead of through the visual/provider-policy routers.
"""

from __future__ import annotations

from collections.abc import Mapping

from workers.ingest.provider_policy import (
    ProviderPolicy,
    ProviderPolicyEnforcer,
    ProviderRequest,
    capability_for,
)

CLOUD_PROVIDER_FAMILIES = frozenset({"aws", "azure", "google"})

_PROVIDER_POLICY_ALIASES = {
    # Implementation-level provider ids used by the OCR/VLM modules -> policy/catalog ids.
    "azure_docintel": "azure_document_intelligence",
    "google_docai": "google_document_ai",
}


def provider_policy_allows(
    *,
    operation: str,
    provider: str,
    policy_resolver: object | None,
    tenant_id: str = "",
    collection_id: str = "",
    provider_policy_id: str = "default",
) -> bool:
    """Return whether tenant policy allows this provider call.

    No resolver or no tenant context means the caller is not in a tenant-scoped runtime, so this helper
    leaves existing local/test behavior unchanged. For cloud families, the policy must allow the call;
    local OSS providers remain controlled by their explicit runtime selection/env config.
    """

    if policy_resolver is None or not tenant_id:
        return True

    policy = _resolve_policy(
        policy_resolver,
        tenant_id=tenant_id,
        collection_id=collection_id,
        provider_policy_id=provider_policy_id,
    )
    enforcer = ProviderPolicyEnforcer()
    last_allowed = False
    for candidate in _candidate_provider_ids(provider):
        capability = capability_for(candidate)
        if capability.provider_family not in CLOUD_PROVIDER_FAMILIES:
            return True
        decision = enforcer.evaluate(
            policy,
            ProviderRequest(operation=operation, provider=candidate, capability=capability),
        )
        if decision.allowed:
            return True
        last_allowed = decision.allowed
    return last_allowed


def _candidate_provider_ids(provider: str) -> tuple[str, ...]:
    alias = _PROVIDER_POLICY_ALIASES.get(provider)
    if alias and alias != provider:
        return (provider, alias)
    return (provider,)


def _resolve_policy(
    resolver: object,
    *,
    tenant_id: str,
    collection_id: str,
    provider_policy_id: str,
) -> ProviderPolicy:
    raw: object
    if hasattr(resolver, "get"):
        raw = resolver.get(tenant_id, collection_id, provider_policy_id)  # type: ignore[attr-defined]
    elif hasattr(resolver, "get_mapping"):
        raw = resolver.get_mapping(  # type: ignore[attr-defined]
            tenant_id, collection_id, provider_policy_id
        )
    elif callable(resolver):
        raw = resolver(tenant_id, collection_id, provider_policy_id)
    else:
        raw = ProviderPolicy(tenant_id=tenant_id, provider_policy_id=provider_policy_id)

    if isinstance(raw, ProviderPolicy):
        return raw
    if isinstance(raw, Mapping):
        return ProviderPolicy.from_mapping(raw)
    return ProviderPolicy(tenant_id=tenant_id, provider_policy_id=provider_policy_id)
