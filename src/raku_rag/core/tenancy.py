"""T012 — tenancy enforcement: bind every operation to a single tenant; deny cross-tenant.

Cross-tenant search is forbidden in the MVP (FR-021a). Collections/documents named in a request
that belong to another tenant are treated as non-existent (no existence disclosure).
"""

from __future__ import annotations

from raku_rag.core.errors import TenantIsolationError
from raku_rag.domain.models import IdentityClaims


def enforce_same_tenant(principal: IdentityClaims, *, resource_tenant_id: str) -> None:
    """Raise if a principal touches another tenant's resource. Message leaks nothing."""
    if principal.tenant_id != resource_tenant_id:
        raise TenantIsolationError("resource not found")  # generic; no existence disclosure


def collection_belongs_to(principal: IdentityClaims, collection_tenant_id: str) -> bool:
    return principal.tenant_id == collection_tenant_id
