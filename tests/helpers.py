"""Shared test helpers.

``fresh()`` is backend-aware so the EXACT same proven test bodies (esp. ``tests/security/*``) run against
either the in-memory MVP (default — keeps Tier A at ~ms) or the Postgres-backed ``ProductionSystem``
(adapter parity, exercised in Tier B). Set ``RAKU_TEST_BACKEND=postgres`` (+ optional ``POSTGRES_URL``) to
switch — see ``docs/production-gate-strategy.md`` and ``scripts/gate.sh b``.
"""

from __future__ import annotations

import os

from raku_rag.app import MvpSystem
from raku_rag.domain.models import IdentityClaims


def fresh():
    """Return a clean system for the active backend (default: in-memory MvpSystem)."""
    if os.environ.get("RAKU_TEST_BACKEND") == "postgres":
        from raku_rag.production import DEFAULT_DSN, ProductionSystem

        return ProductionSystem(os.environ.get("POSTGRES_URL", DEFAULT_DSN), reset=True)
    return MvpSystem()


def claims(tenant: str, user: str, groups=(), roles=()) -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user, groups=tuple(groups), roles=tuple(roles))
