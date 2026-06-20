"""T062/T063 — Governance / DataUsePolicy API SHAPE contract (contracts/mfg-openapi.md §F).

Response-shape contract for the NEW governance endpoints exposed by the in-memory
``ManufacturingSystem``:
  - GET  /v1/manufacturing/policy/data-use         -> get_data_use_policy(tenant_id)
  - PUT  /v1/manufacturing/policy/data-use (admin) -> update_data_use_policy(*, tenant_id, patch, actor)
  - GET  /v1/manufacturing/governance/status       -> governance_status(tenant_id)

This is the SHAPE axis only; the load-bearing no-train behaviour (opt-in required, block-not-degrade)
is pinned by T060 (test_no_train.py) and audit coverage by T061 (test_audit_coverage.py).

Entrypoint contract the stage-2 ManufacturingSystem must satisfy:

  get_data_use_policy(tenant_id) -> DataUsePolicy
      GET /v1/manufacturing/policy/data-use. Auto-seeds the GQ1/GQ2 safe default (no_train_default=
      True, training_opt_in=False, provider_no_train_required=True, no_train_fallback="block",
      retention_customer=365, retention_audit=365, export_enabled=False) with a non-empty policy_version.
  update_data_use_policy(*, tenant_id, patch, actor) -> DataUsePolicy
      PUT (admin). Applies a partial patch, bumps policy_version, records the change in the audit log
      (FR-MFG-019). training_opt_in=True without a non-empty opt_in_contract_ref is REJECTED (FR-MFG-018).
  governance_status(tenant_id) -> dict
      GET /v1/manufacturing/governance/status. Presents the AI-governance core features
      (no_train / audit_coverage / safety_gate / draft_review / groundedness) + an
      ismap_readiness_memo that states "見据えた設計" and does NOT claim ISMAP registration/compliance
      (FR-MFG-024~026).

TDD: RED now because these governance entrypoints are unimplemented on ManufacturingSystem
(missing-impl), NOT an unrelated import error. Assertion style mirrors
tests/manufacturing/test_drafts_contract.py.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.domain.policy import NoTrainFallback

T = "tenant_mfg"


def _admin(tenant: str = T, user: str = "admin-1") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user, roles=("admin",))


class TestGetDataUsePolicyShape(unittest.TestCase):
    """GET /v1/manufacturing/policy/data-use — GQ1/GQ2 safe-posture defaults, explainable."""

    def test_default_policy_shape(self) -> None:
        sys = ManufacturingSystem()
        p = sys.get_data_use_policy(T)
        self.assertEqual(p.tenant_id, T)
        self.assertTrue(p.no_train_default)
        self.assertFalse(p.training_opt_in)
        self.assertIsNone(p.opt_in_contract_ref)
        self.assertTrue(p.provider_no_train_required)
        self.assertEqual(p.no_train_fallback, NoTrainFallback.BLOCK)
        self.assertEqual(p.retention_customer, 365)
        self.assertEqual(p.retention_audit, 365)
        self.assertFalse(p.export_enabled)
        self.assertTrue(p.policy_version, "policy_version must be present (FR-MFG-019)")

    def test_policy_is_tenant_scoped(self) -> None:
        sys = ManufacturingSystem()
        sys.update_data_use_policy(tenant_id=T, patch={"export_enabled": True}, actor=_admin())
        self.assertFalse(sys.get_data_use_policy("tenant_other").export_enabled)
        self.assertTrue(sys.get_data_use_policy(T).export_enabled)


class TestUpdateDataUsePolicyShape(unittest.TestCase):
    """PUT /v1/manufacturing/policy/data-use — patch + version bump + opt-in invariant + audit."""

    def test_update_bumps_policy_version(self) -> None:
        sys = ManufacturingSystem()
        v0 = sys.get_data_use_policy(T).policy_version
        p1 = sys.update_data_use_policy(
            tenant_id=T, patch={"retention_customer": 730}, actor=_admin()
        )
        self.assertEqual(p1.retention_customer, 730)
        self.assertNotEqual(p1.policy_version, v0)

    def test_opt_in_requires_contract_ref(self) -> None:
        sys = ManufacturingSystem()
        with self.assertRaises(ValueError):
            sys.update_data_use_policy(tenant_id=T, patch={"training_opt_in": True}, actor=_admin())

    def test_opt_in_with_contract_ref_succeeds(self) -> None:
        sys = ManufacturingSystem()
        p = sys.update_data_use_policy(
            tenant_id=T,
            patch={"training_opt_in": True, "opt_in_contract_ref": "CONTRACT-1"},
            actor=_admin(),
        )
        self.assertTrue(p.training_opt_in)
        self.assertEqual(p.opt_in_contract_ref, "CONTRACT-1")

    def test_policy_change_is_audited(self) -> None:
        # FR-MFG-019: a policy change is recorded in the audit log (reference IDs only).
        sys = ManufacturingSystem()
        sys.update_data_use_policy(tenant_id=T, patch={"export_enabled": True}, actor=_admin())
        entries = sys.audit.read_all(_admin())
        self.assertTrue(
            any(
                "policy" in (getattr(e, "action", "") or "").lower()
                or "no_train" in (getattr(e, "action", "") or "").lower()
                or "retention" in (getattr(e, "action", "") or "").lower()
                for e in entries
            ),
            "a DataUsePolicy change must emit an audit entry (FR-MFG-019/021)",
        )


class TestGovernanceStatusShape(unittest.TestCase):
    """GET /v1/manufacturing/governance/status — AI-governance core features + ISMAP memo."""

    def test_status_presents_core_features(self) -> None:
        sys = ManufacturingSystem()
        status = sys.governance_status(T)
        self.assertIsInstance(status, dict)
        for key in ("no_train", "audit_coverage", "safety_gate", "draft_review", "groundedness"):
            self.assertIn(
                key, status, f"governance status must present core feature {key!r} (FR-MFG-024)"
            )

    def test_ismap_memo_does_not_claim_compliance(self) -> None:
        # FR-MFG-026: MUST NOT claim "ISMAP registered / fully compliant".
        sys = ManufacturingSystem()
        status = sys.governance_status(T)
        memo = str(status.get("ismap_readiness_memo", ""))
        self.assertTrue(memo, "an ismap_readiness_memo must be present (FR-MFG-025/026)")
        lowered = memo.lower()
        self.assertNotIn("registered", lowered)
        self.assertNotIn("fully compliant", lowered)
        self.assertNotIn("登録済み", memo)


if __name__ == "__main__":
    unittest.main()
