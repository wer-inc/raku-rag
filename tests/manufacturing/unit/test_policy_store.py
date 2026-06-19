"""T010 unit tests — InMemoryDataUsePolicyStore defaults / opt-in invariant / versioning.

Covers: (a) GQ1/GQ2 defaults, (b) training_opt_in=True without contract ref raises (FR-MFG-018),
(c) policy_version increments on accepted change (FR-MFG-019). Tenant-scoped, stdlib only.
"""
from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.policy import NoTrainFallback
from raku_rag.manufacturing.governance.no_train import (
    InMemoryDataUsePolicyStore,
    default_policy,
)


def _actor(tenant_id: str = "t1") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant_id, user_id="admin-1", roles=("admin",))


class TestDataUsePolicyStore(unittest.TestCase):
    # (a) defaults correct -------------------------------------------------
    def test_defaults_match_gq1_gq2_safe_posture(self) -> None:
        store = InMemoryDataUsePolicyStore()
        p = store.get("t1")
        self.assertEqual(p.tenant_id, "t1")
        self.assertTrue(p.no_train_default)
        self.assertFalse(p.training_opt_in)
        self.assertIsNone(p.opt_in_contract_ref)
        self.assertTrue(p.provider_no_train_required)
        self.assertEqual(p.no_train_fallback, NoTrainFallback.BLOCK)
        self.assertEqual(p.no_train_fallback.value, "block")
        self.assertEqual(p.retention_customer, 365)
        self.assertEqual(p.retention_audit, 365)
        self.assertFalse(p.export_enabled)
        self.assertTrue(p.policy_version)  # versioned from the start (FR-MFG-019)

    def test_default_policy_helper_matches_store(self) -> None:
        self.assertEqual(default_policy("t9").tenant_id, "t9")
        self.assertTrue(default_policy("t9").no_train_default)

    def test_get_is_tenant_scoped_and_isolated(self) -> None:
        store = InMemoryDataUsePolicyStore()
        store.update("t1", {"export_enabled": True}, _actor("t1"))
        # different tenant gets the untouched default
        self.assertFalse(store.get("t2").export_enabled)
        self.assertTrue(store.get("t1").export_enabled)

    def test_get_returns_a_copy_not_the_stored_object(self) -> None:
        store = InMemoryDataUsePolicyStore()
        p = store.get("t1")
        p.export_enabled = True  # mutate the returned copy
        self.assertFalse(store.get("t1").export_enabled)  # store unaffected

    # (b) opt-in without contract ref raises -------------------------------
    def test_opt_in_without_contract_ref_raises(self) -> None:
        store = InMemoryDataUsePolicyStore()
        with self.assertRaises(ValueError):
            store.update("t1", {"training_opt_in": True}, _actor())

    def test_opt_in_with_blank_contract_ref_raises(self) -> None:
        store = InMemoryDataUsePolicyStore()
        with self.assertRaises(ValueError):
            store.update(
                "t1", {"training_opt_in": True, "opt_in_contract_ref": "   "}, _actor()
            )

    def test_failed_opt_in_leaves_stored_policy_unchanged(self) -> None:
        store = InMemoryDataUsePolicyStore()
        before = store.get("t1")
        with self.assertRaises(ValueError):
            store.update("t1", {"training_opt_in": True}, _actor())
        after = store.get("t1")
        self.assertFalse(after.training_opt_in)
        self.assertEqual(after.policy_version, before.policy_version)  # not bumped

    def test_opt_in_with_contract_ref_succeeds(self) -> None:
        store = InMemoryDataUsePolicyStore()
        p = store.update(
            "t1",
            {"training_opt_in": True, "opt_in_contract_ref": "CONTRACT-2026-001"},
            _actor(),
        )
        self.assertTrue(p.training_opt_in)
        self.assertEqual(p.opt_in_contract_ref, "CONTRACT-2026-001")

    # (c) policy_version increments on change ------------------------------
    def test_policy_version_increments_on_change(self) -> None:
        store = InMemoryDataUsePolicyStore()
        v0 = store.get("t1").policy_version
        p1 = store.update("t1", {"export_enabled": True}, _actor())
        self.assertNotEqual(p1.policy_version, v0)
        p2 = store.update("t1", {"export_enabled": False}, _actor())
        self.assertNotEqual(p2.policy_version, p1.policy_version)
        # monotonic numeric bump
        self.assertEqual(int(p2.policy_version), int(p1.policy_version) + 1)
        self.assertEqual(int(p1.policy_version), int(v0) + 1)

    def test_update_records_actor_as_updated_by(self) -> None:
        store = InMemoryDataUsePolicyStore()
        p = store.update("t1", {"export_enabled": True}, _actor())
        self.assertEqual(p.updated_by, "admin-1")

    def test_unknown_patch_field_raises(self) -> None:
        store = InMemoryDataUsePolicyStore()
        with self.assertRaises(ValueError):
            store.update("t1", {"tenant_id": "evil"}, _actor())
        with self.assertRaises(ValueError):
            store.update("t1", {"policy_version": "99"}, _actor())


if __name__ == "__main__":
    unittest.main()
