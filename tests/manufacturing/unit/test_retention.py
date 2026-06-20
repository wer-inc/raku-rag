"""GAP-F1 unit tests — RetentionManager.effective_retention + _clamp (FR-MFG-020, GQ2).

Defaults are customer 365 / audit 365 (GQ2). A DataUsePolicy override is reflected; an out-of-band
override is CLAMPED into the 30..3650 guide band (advisory guidance, fails safe — not a hard reject).
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.governance.no_train import InMemoryDataUsePolicyStore
from raku_rag.manufacturing.governance.retention import (
    RETENTION_MAX_DAYS,
    RETENTION_MIN_DAYS,
    InMemoryRetentionManager,
    _clamp,
)

T = "t1"


def _admin(tenant: str = T) -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id="admin-1", roles=("admin",))


class TestEffectiveRetentionDefaults(unittest.TestCase):
    def test_default_is_365_365(self) -> None:
        mgr = InMemoryRetentionManager(InMemoryDataUsePolicyStore())
        rc = mgr.effective_retention(T)
        self.assertEqual(rc.tenant_id, T)
        self.assertEqual(rc.retention_customer_days, 365)
        self.assertEqual(rc.retention_audit_days, 365)

    def test_override_is_reflected(self) -> None:
        store = InMemoryDataUsePolicyStore()
        store.update(T, {"retention_customer": 730, "retention_audit": 1000}, _admin())
        rc = InMemoryRetentionManager(store).effective_retention(T)
        self.assertEqual(rc.retention_customer_days, 730)
        self.assertEqual(rc.retention_audit_days, 1000)

    def test_tenant_scoped(self) -> None:
        store = InMemoryDataUsePolicyStore()
        store.update(T, {"retention_customer": 730}, _admin())
        mgr = InMemoryRetentionManager(store)
        self.assertEqual(mgr.effective_retention(T).retention_customer_days, 730)
        self.assertEqual(mgr.effective_retention("t_other").retention_customer_days, 365)


class TestRetentionClamp(unittest.TestCase):
    def test_below_band_clamps_to_min(self) -> None:
        self.assertEqual(_clamp(5, default=365), RETENTION_MIN_DAYS)

    def test_above_band_clamps_to_max(self) -> None:
        self.assertEqual(_clamp(99999, default=365), RETENTION_MAX_DAYS)

    def test_in_band_passthrough(self) -> None:
        self.assertEqual(_clamp(730, default=365), 730)

    def test_non_int_falls_back_to_default(self) -> None:
        self.assertEqual(_clamp("x", default=365), 365)
        self.assertEqual(_clamp(None, default=180), 180)

    def test_out_of_band_override_is_clamped_through_resolver(self) -> None:
        # An admin who stores 5 / 99999 days (out of the 30..3650 guide) gets the clamped value.
        store = InMemoryDataUsePolicyStore()
        store.update(T, {"retention_customer": 5, "retention_audit": 99999}, _admin())
        rc = InMemoryRetentionManager(store).effective_retention(T)
        self.assertEqual(rc.retention_customer_days, RETENTION_MIN_DAYS)
        self.assertEqual(rc.retention_audit_days, RETENTION_MAX_DAYS)


if __name__ == "__main__":
    unittest.main()
