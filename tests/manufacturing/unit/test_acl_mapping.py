"""T011 unit — Manufacturing ACL mapping (FR-MFG-013).

Verifies the mapping translates manufacturing scopes into 001 ACL inputs and DELEGATES the visibility
decision to the existing 001 ``AclPolicy`` — it builds no bespoke authorization mechanism.
"""

from __future__ import annotations

import unittest

from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import (
    ACLGrant,
    Chunk,
    IdentityClaims,
    ScopeType,
    SubjectType,
)
from raku_rag.manufacturing.domain.acl_mapping import (
    ManufacturingScope,
    acl_policy_for_scopes,
    can_read_chunk,
    department_subject,
    equipment_area_scope,
    factory_scope,
    grants_for_scope,
    visibility_filter,
)
from raku_rag.manufacturing.domain.entities import Equipment, Factory, Process

T = "tenant_a"


def _claims(user: str, groups=(), roles=(), tenant: str = T) -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user, groups=tuple(groups), roles=tuple(roles))


def _chunk(tenant: str, collection_id: str, document_id: str) -> Chunk:
    return Chunk(
        tenant_id=tenant,
        chunk_id=f"{document_id}#0",
        document_id=document_id,
        collection_id=collection_id,
        text="body",
    )


class TestDepartmentMapping(unittest.TestCase):
    """(a) department maps to a base ACL group/role — never a new entity."""

    def test_department_subject_is_base_acl_group(self) -> None:
        st, sid = department_subject("press_dept")
        self.assertEqual(st, SubjectType.GROUP)  # department == base ACL group (FR-MFG-013)
        self.assertEqual(sid, "press_dept")

    def test_department_subject_can_be_role(self) -> None:
        st, sid = department_subject("press_dept", as_role=True)
        self.assertEqual(st, SubjectType.ROLE)
        self.assertEqual(sid, "press_dept")

    def test_department_grant_subject_is_group(self) -> None:
        scope = ManufacturingScope(tenant_id=T, department="press_dept")
        grants = grants_for_scope(scope)
        self.assertTrue(grants, "department should yield at least one grant")
        for g in grants:
            self.assertIsInstance(g, ACLGrant)  # produces 001 ACLGrant, not a new type
            self.assertEqual(g.subject_type, SubjectType.GROUP)
            self.assertEqual(g.subject_id, "press_dept")
            self.assertEqual(g.tenant_id, T)
            self.assertEqual(g.permission, "read")

    def test_role_dimension_maps_to_base_acl_role(self) -> None:
        scope = ManufacturingScope(tenant_id=T, roles=("supervisor",))
        grants = grants_for_scope(scope)
        self.assertTrue(
            any(g.subject_type == SubjectType.ROLE and g.subject_id == "supervisor" for g in grants)
        )


class TestFactoryAndEquipmentScopeMapping(unittest.TestCase):
    """(b) factory scope maps to the Factory entity; equipment-area to Process/Equipment metadata."""

    def test_factory_scope_maps_to_factory_entity_collection(self) -> None:
        fac = Factory(tenant_id=T, factory_id="fac1", name="Plant 1")
        scope_type, scope_id = factory_scope(fac)
        self.assertEqual(scope_type, ScopeType.COLLECTION)  # factory = ACL territory unit
        self.assertIn("fac1", scope_id)
        # accepts the raw id too, producing the same scope id
        self.assertEqual(factory_scope("fac1"), (scope_type, scope_id))

    def test_factory_scope_drives_grant_scope(self) -> None:
        fac = Factory(tenant_id=T, factory_id="fac1")
        scope = ManufacturingScope(
            tenant_id=T, department="press_dept", factory_ids=(fac.factory_id,)
        )
        grants = grants_for_scope(scope)
        _, fac_scope_id = factory_scope(fac)
        self.assertTrue(grants)
        for g in grants:
            self.assertEqual(g.scope_type, ScopeType.COLLECTION)
            self.assertEqual(g.scope_id, fac_scope_id)

    def test_equipment_area_maps_to_process_or_equipment_id(self) -> None:
        proc = Process(tenant_id=T, process_id="proc9", factory_id="fac1")
        equip = Equipment(tenant_id=T, equipment_id="eq7", factory_id="fac1")
        self.assertEqual(equipment_area_scope(proc), (ScopeType.DOCUMENT, "proc9"))
        self.assertEqual(equipment_area_scope(equip), (ScopeType.DOCUMENT, "eq7"))
        self.assertEqual(equipment_area_scope("raw_id"), (ScopeType.DOCUMENT, "raw_id"))


class TestDelegatesToBase001AclPolicy(unittest.TestCase):
    """(c) the helper delegates to the 001 AclPolicy — it produces a 001 visibility filter."""

    def test_builds_a_real_001_aclpolicy(self) -> None:
        scope = ManufacturingScope(tenant_id=T, department="press_dept", factory_ids=("fac1",))
        policy = acl_policy_for_scopes([scope])
        self.assertIsInstance(policy, AclPolicy)  # exactly the 001 engine, not a bespoke one

    def test_visibility_filter_is_the_001_predicate(self) -> None:
        # Same grants, two ways: (1) via the manufacturing mapping, (2) hand-built 001 AclPolicy.
        # The mapping's predicate must agree with the 001 engine for every chunk.
        scope = ManufacturingScope(tenant_id=T, department="press_dept", factory_ids=("fac1",))
        _, fac_collection = factory_scope("fac1")
        baseline = AclPolicy(grants_for_scope(scope))

        alice = _claims("alice", groups=["press_dept"])
        mapped_pred = visibility_filter([scope], alice)
        base_pred = baseline.visibility(alice)

        in_factory = _chunk(T, fac_collection, "docA")
        other_factory = _chunk(T, "factory:fac2", "docB")
        for ch in (in_factory, other_factory):
            self.assertEqual(
                mapped_pred(ch),
                base_pred(ch),
                "mapping must delegate to the 001 AclPolicy predicate, not a bespoke one",
            )

    def test_deny_by_default_for_unmapped_subject(self) -> None:
        # A user with no matching department/role/factory grant is denied (001 deny-by-default).
        scope = ManufacturingScope(tenant_id=T, department="press_dept", factory_ids=("fac1",))
        _, fac_collection = factory_scope("fac1")
        bob = _claims("bob", groups=["weld_dept"])  # different department
        pred = visibility_filter([scope], bob)
        self.assertFalse(pred(_chunk(T, fac_collection, "docA")))

    def test_authorized_department_can_read_its_factory(self) -> None:
        scope = ManufacturingScope(tenant_id=T, department="press_dept", factory_ids=("fac1",))
        _, fac_collection = factory_scope("fac1")
        alice = _claims("alice", groups=["press_dept"])
        self.assertTrue(can_read_chunk([scope], alice, _chunk(T, fac_collection, "docA")))

    def test_cross_tenant_chunk_is_denied_via_001_tenancy(self) -> None:
        # can_read_chunk binds tenant via 001 enforce_same_tenant before delegating.
        scope = ManufacturingScope(tenant_id=T, department="press_dept", factory_ids=("fac1",))
        _, fac_collection = factory_scope("fac1")
        alice = _claims("alice", groups=["press_dept"], tenant=T)
        foreign_chunk = _chunk("tenant_b", fac_collection, "docA")
        from raku_rag.core.errors import TenantIsolationError

        with self.assertRaises(TenantIsolationError):
            can_read_chunk([scope], alice, foreign_chunk)


if __name__ == "__main__":
    unittest.main()
