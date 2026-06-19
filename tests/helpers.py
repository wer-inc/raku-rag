"""Shared test helpers."""
from __future__ import annotations

from raku_rag.app import MvpSystem
from raku_rag.domain.models import IdentityClaims


def fresh() -> MvpSystem:
    return MvpSystem()


def claims(tenant: str, user: str, groups=(), roles=()) -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user, groups=tuple(groups), roles=tuple(roles))
