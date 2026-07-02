"""T018/T054/T056 — Call scenario lifecycle (FR-019..024, US3).

Lifecycle: draft -> in_review -> approved -> (scheduled) -> published -> archived.
Published versions are immutable; publish REQUIRES a prior explicit approve action and returns
``scenario_version_not_approved`` otherwise (FR-022 — the MVP authorization matrix gives approve
and publish to the same roles, so requiring the separate approve step is the not-weaker reading
of "publish cannot silently approve a draft"). Rollback publishes a NEW version that references
``rollback_target_version_id`` so past calls keep their original version trace (FR-021, SC-007).
"""

from __future__ import annotations

from raku_rag.domain.models import IdentityClaims
from raku_rag.phone.domain import (
    MANDATORY_HANDOFF_REASONS,
    CallScenario,
    ScenarioVersion,
    assert_scenario_transition,
    new_id,
    now_iso,
)
from raku_rag.phone.interfaces import ScenarioRepository

SCENARIO_MANAGE_ROLES = frozenset({"tenant_admin", "scenario_admin"})
SCENARIO_APPROVE_ROLES = frozenset({"tenant_admin", "scenario_approver"})
SCENARIO_READ_ROLES = SCENARIO_MANAGE_ROLES | SCENARIO_APPROVE_ROLES | frozenset({"ops_owner"})

_ACTION_TARGET = {
    "submit-review": "in_review",
    "approve": "approved",
    "publish": "published",
    "schedule": "scheduled",
    "archive": "archived",
}


class ScenarioError(Exception):
    """Carries the HTTP status + error code the internal API returns."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _ensure_mandatory_handoff_conditions(conditions: list[dict]) -> list[dict]:
    """Every version must keep customer_requested_human / insufficient_evidence enabled defaults."""
    merged = [dict(c) for c in conditions]
    present = {str(c.get("reason") or "") for c in merged}
    for reason in MANDATORY_HANDOFF_REASONS:
        if reason not in present:
            merged.append({"reason": reason, "enabled": True})
    return merged


class PhoneScenarioService:
    """Tenant-scoped scenario CRUD + lifecycle over a ScenarioRepository."""

    def __init__(self, repository: ScenarioRepository) -> None:
        self._repo = repository

    # --- roles ---------------------------------------------------------------------------------

    def can_manage(self, principal: IdentityClaims) -> bool:
        return bool(set(principal.roles) & SCENARIO_MANAGE_ROLES)

    def can_approve(self, principal: IdentityClaims) -> bool:
        return bool(set(principal.roles) & SCENARIO_APPROVE_ROLES)

    def can_read(self, principal: IdentityClaims) -> bool:
        return bool(set(principal.roles) & SCENARIO_READ_ROLES)

    # --- CRUD ----------------------------------------------------------------------------------

    def list(self, principal: IdentityClaims) -> list[dict]:
        return [
            {
                "scenario_id": s.scenario_id,
                "name": s.name,
                "intent": s.intent,
                "status": s.status,
                "active_version_id": s.active_version_id,
                "updated_at": s.updated_at,
            }
            for s in self._repo.list(principal.tenant_id)
        ]

    def create(self, principal: IdentityClaims, body: dict) -> CallScenario:
        intent = str(body.get("intent") or "faq")
        scenario_id = str(body.get("scenario_id") or f"{intent}-basic")
        if self._repo.get(principal.tenant_id, scenario_id):
            raise ScenarioError(409, "scenario_already_exists")
        scenario = CallScenario(
            tenant_id=principal.tenant_id,
            scenario_id=scenario_id,
            name=str(body.get("name") or scenario_id),
            intent=intent,
            description=str(body.get("description") or "") or None,
            owner_group=str(body.get("owner_group") or "") or None,
            created_by=principal.user_id,
        )
        # Seed an editable draft version so quickstart's `PUT .../versions/scv_1` works directly.
        initial = ScenarioVersion(
            tenant_id=principal.tenant_id,
            scenario_id=scenario_id,
            scenario_version_id="scv_1",
            version_number=1,
            handoff_conditions=_ensure_mandatory_handoff_conditions([]),
            created_by=principal.user_id,
        )
        scenario.versions[initial.scenario_version_id] = initial
        self._repo.save(scenario)
        return scenario

    def get(self, principal: IdentityClaims, scenario_id: str) -> CallScenario:
        scenario = self._repo.get(principal.tenant_id, scenario_id)
        if not scenario:
            raise ScenarioError(404, "not_found")
        return scenario

    def upsert_version(
        self, principal: IdentityClaims, scenario_id: str, version_id: str, body: dict
    ) -> ScenarioVersion:
        scenario = self.get(principal, scenario_id)
        existing = scenario.version(version_id)
        if existing and existing.is_immutable():
            raise ScenarioError(409, "scenario_version_immutable")
        version = ScenarioVersion(
            tenant_id=principal.tenant_id,
            scenario_id=scenario_id,
            scenario_version_id=version_id,
            version_number=existing.version_number if existing else scenario.next_version_number(),
            status=existing.status if existing else "draft",
            entry_conditions=[dict(c) for c in body.get("entry_conditions") or (existing.entry_conditions if existing else [])],
            steps=[dict(s) for s in body.get("steps") or (existing.steps if existing else [])],
            required_slots=[dict(s) for s in body.get("required_slots") or (existing.required_slots if existing else [])],
            branch_conditions=[dict(c) for c in body.get("branch_conditions") or (existing.branch_conditions if existing else [])],
            allowed_actions=[str(a) for a in body.get("allowed_actions") or (existing.allowed_actions if existing else [])],
            handoff_conditions=_ensure_mandatory_handoff_conditions(
                [dict(c) for c in body.get("handoff_conditions") or (existing.handoff_conditions if existing else [])]
            ),
            fallback_message=str(
                body.get("fallback_message")
                or (existing.fallback_message if existing else "確認して担当者におつなぎします。")
            ),
            response_templates=[dict(t) for t in body.get("response_templates") or (existing.response_templates if existing else [])],
            approved_by=existing.approved_by if existing else None,
            approved_at=existing.approved_at if existing else None,
            created_by=existing.created_by if existing else principal.user_id,
            created_at=existing.created_at if existing else now_iso(),
        )
        scenario.versions[version_id] = version
        scenario.updated_at = now_iso()
        self._repo.save(scenario)
        return version

    # --- lifecycle -----------------------------------------------------------------------------

    def action(
        self,
        principal: IdentityClaims,
        scenario_id: str,
        version_id: str,
        action: str,
        body: dict,
    ) -> tuple[CallScenario, ScenarioVersion]:
        if action not in _ACTION_TARGET:
            raise ScenarioError(404, "not_found")
        scenario = self.get(principal, scenario_id)
        version = scenario.version(version_id)
        if not version:
            raise ScenarioError(404, "not_found")
        target = _ACTION_TARGET[action]

        if action == "publish" and version.status not in {"approved", "scheduled"}:
            # FR-022: publish never silently approves a draft/in-review version.
            raise ScenarioError(409, "scenario_version_not_approved")
        if action == "schedule" and version.status != "approved":
            raise ScenarioError(409, "scenario_version_not_approved")
        if version.is_immutable() and action != "archive":
            raise ScenarioError(409, "scenario_version_immutable")
        try:
            assert_scenario_transition(version.status, target)
        except ValueError:
            raise ScenarioError(409, "scenario_version_immutable") from None

        stamp = now_iso()
        version.status = target
        if action == "approve":
            version.approved_by = principal.user_id
            version.approved_at = stamp
        if action == "schedule":
            version.scheduled_publish_at = str(body.get("publish_at") or "")
        if action == "publish":
            version.published_by = principal.user_id
            version.published_at = stamp
            previous = scenario.active_version_id
            if previous and previous != version.scenario_version_id:
                version.supersedes_version_id = previous
            scenario.active_version_id = version.scenario_version_id
        if action == "archive":
            version.archived_by = principal.user_id
            version.archived_at = stamp
            if scenario.active_version_id == version.scenario_version_id:
                scenario.active_version_id = None
        scenario.status = version.status if action != "archive" else scenario.status
        scenario.updated_at = stamp
        self._repo.save(scenario)
        return scenario, version

    def rollback(
        self, principal: IdentityClaims, scenario_id: str, body: dict
    ) -> tuple[CallScenario, ScenarioVersion]:
        scenario = self.get(principal, scenario_id)
        target_id = str(body.get("target_version_id") or "")
        target = scenario.version(target_id)
        if not target:
            raise ScenarioError(404, "not_found")
        if target.status not in {"published", "archived", "approved"} or not target.approved_at:
            raise ScenarioError(409, "scenario_version_not_approved")

        stamp = now_iso()
        # A rollback publishes a NEW immutable version copying the target payload; the target and
        # all past calls keep their original identifiers (SC-007).
        new_version = ScenarioVersion(
            tenant_id=principal.tenant_id,
            scenario_id=scenario_id,
            scenario_version_id=f"scv_{scenario.next_version_number()}",
            version_number=scenario.next_version_number(),
            status="published",
            entry_conditions=[dict(c) for c in target.entry_conditions],
            steps=[dict(s) for s in target.steps],
            required_slots=[dict(s) for s in target.required_slots],
            branch_conditions=[dict(c) for c in target.branch_conditions],
            allowed_actions=list(target.allowed_actions),
            handoff_conditions=_ensure_mandatory_handoff_conditions(
                [dict(c) for c in target.handoff_conditions]
            ),
            fallback_message=target.fallback_message,
            response_templates=[dict(t) for t in target.response_templates],
            approved_by=target.approved_by,
            approved_at=target.approved_at,
            published_by=principal.user_id,
            published_at=stamp,
            supersedes_version_id=scenario.active_version_id,
            rollback_target_version_id=target.scenario_version_id,
            created_by=principal.user_id,
            created_at=stamp,
        )
        scenario.versions[new_version.scenario_version_id] = new_version
        scenario.active_version_id = new_version.scenario_version_id
        scenario.status = "published"
        scenario.updated_at = stamp
        self._repo.save(scenario)
        return scenario, new_version

    def resolve_for_call(self, tenant_id: str, scenario_id: str | None) -> ScenarioVersion | None:
        """The published version a new call should run under (None -> default behavior)."""
        if not scenario_id:
            return None
        scenario = self._repo.get(tenant_id, scenario_id)
        if not scenario:
            return None
        active = scenario.active_version()
        if active and active.status == "published":
            return active
        return None


def scenario_id_hint(body: dict) -> str | None:
    value = body.get("scenario_id")
    return str(value) if value else None


def new_version_id() -> str:
    return new_id("scv")
