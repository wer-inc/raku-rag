"""T011/T052 — Scenario version lifecycle: draft/approval/publish/immutability/rollback (US3)."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.persistence.phone_models import InMemoryPhoneScenarioRepository
from raku_rag.phone.domain import MANDATORY_HANDOFF_REASONS
from raku_rag.phone.scenarios import PhoneScenarioService, ScenarioError

ADMIN = IdentityClaims(tenant_id="tenant_a", user_id="admin", roles=("tenant_admin",))
APPROVER = IdentityClaims(tenant_id="tenant_a", user_id="approver", roles=("scenario_approver",))


def _service() -> PhoneScenarioService:
    return PhoneScenarioService(InMemoryPhoneScenarioRepository())


def _created(service: PhoneScenarioService):
    return service.create(ADMIN, {"name": "FAQ基本対応", "intent": "faq"})


class TestScenarioCreation(unittest.TestCase):
    def test_create_derives_id_and_seeds_draft_version(self) -> None:
        service = _service()
        scenario = _created(service)
        self.assertEqual(scenario.scenario_id, "faq-basic")
        version = scenario.version("scv_1")
        self.assertIsNotNone(version)
        self.assertEqual(version.status, "draft")

    def test_mandatory_handoff_conditions_are_seeded(self) -> None:
        service = _service()
        scenario = _created(service)
        reasons = {c["reason"] for c in scenario.version("scv_1").handoff_conditions}
        for reason in MANDATORY_HANDOFF_REASONS:
            self.assertIn(reason, reasons)

    def test_duplicate_create_conflicts(self) -> None:
        service = _service()
        _created(service)
        with self.assertRaises(ScenarioError) as ctx:
            _created(service)
        self.assertEqual(ctx.exception.status, 409)


class TestVersionUpsert(unittest.TestCase):
    def test_upsert_keeps_mandatory_handoff_conditions(self) -> None:
        service = _service()
        _created(service)
        version = service.upsert_version(
            ADMIN,
            "faq-basic",
            "scv_1",
            {"handoff_conditions": [{"reason": "negative_sentiment", "enabled": True}]},
        )
        reasons = {c["reason"] for c in version.handoff_conditions}
        self.assertIn("negative_sentiment", reasons)
        for reason in MANDATORY_HANDOFF_REASONS:
            self.assertIn(reason, reasons)

    def test_published_version_is_immutable(self) -> None:
        service = _service()
        _created(service)
        service.action(ADMIN, "faq-basic", "scv_1", "submit-review", {})
        service.action(APPROVER, "faq-basic", "scv_1", "approve", {})
        service.action(APPROVER, "faq-basic", "scv_1", "publish", {})
        with self.assertRaises(ScenarioError) as ctx:
            service.upsert_version(ADMIN, "faq-basic", "scv_1", {"fallback_message": "x"})
        self.assertEqual(ctx.exception.code, "scenario_version_immutable")


class TestLifecycleActions(unittest.TestCase):
    def test_publish_requires_prior_approval(self) -> None:
        service = _service()
        _created(service)
        with self.assertRaises(ScenarioError) as ctx:
            service.action(APPROVER, "faq-basic", "scv_1", "publish", {})
        self.assertEqual(ctx.exception.code, "scenario_version_not_approved")

    def test_full_lifecycle_sets_active_version(self) -> None:
        service = _service()
        _created(service)
        service.action(ADMIN, "faq-basic", "scv_1", "submit-review", {})
        _, version = service.action(APPROVER, "faq-basic", "scv_1", "approve", {})
        self.assertEqual(version.approved_by, "approver")
        scenario, version = service.action(APPROVER, "faq-basic", "scv_1", "publish", {})
        self.assertEqual(scenario.active_version_id, "scv_1")
        self.assertEqual(version.status, "published")
        self.assertEqual(version.published_by, "approver")

    def test_archive_clears_active_version(self) -> None:
        service = _service()
        _created(service)
        service.action(ADMIN, "faq-basic", "scv_1", "submit-review", {})
        service.action(APPROVER, "faq-basic", "scv_1", "approve", {})
        service.action(APPROVER, "faq-basic", "scv_1", "publish", {})
        scenario, _ = service.action(APPROVER, "faq-basic", "scv_1", "archive", {})
        self.assertIsNone(scenario.active_version_id)


class TestRollback(unittest.TestCase):
    def _publish(self, service, version_id, body=None) -> None:
        if body is not None:
            service.upsert_version(ADMIN, "faq-basic", version_id, body)
        service.action(ADMIN, "faq-basic", version_id, "submit-review", {})
        service.action(APPROVER, "faq-basic", version_id, "approve", {})
        service.action(APPROVER, "faq-basic", version_id, "publish", {})

    def test_rollback_creates_new_version_referencing_target(self) -> None:
        service = _service()
        _created(service)
        self._publish(service, "scv_1")
        service.upsert_version(ADMIN, "faq-basic", "scv_2", {"fallback_message": "v2"})
        self._publish(service, "scv_2")

        scenario, new_version = service.rollback(
            APPROVER, "faq-basic", {"target_version_id": "scv_1"}
        )
        self.assertEqual(new_version.rollback_target_version_id, "scv_1")
        self.assertEqual(scenario.active_version_id, new_version.scenario_version_id)
        self.assertNotEqual(new_version.scenario_version_id, "scv_1")
        # Past versions keep their identity/payload (SC-007).
        self.assertEqual(scenario.version("scv_1").status, "published")
        self.assertEqual(scenario.version("scv_2").status, "published")

    def test_rollback_to_never_approved_version_conflicts(self) -> None:
        service = _service()
        _created(service)
        self._publish(service, "scv_1")
        service.upsert_version(ADMIN, "faq-basic", "scv_3", {})
        with self.assertRaises(ScenarioError) as ctx:
            service.rollback(APPROVER, "faq-basic", {"target_version_id": "scv_3"})
        self.assertEqual(ctx.exception.code, "scenario_version_not_approved")


if __name__ == "__main__":
    unittest.main()
