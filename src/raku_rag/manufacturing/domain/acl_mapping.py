"""T011 — Manufacturing ACL mapping helper (FR-MFG-013).

Translate manufacturing access scopes (department / factory / role / equipment-area) into the
inputs of the existing 001 deny-by-default ACL ([base:FR-022/025a]). This module builds **NO new
authorization mechanism**: it only produces 001 ``ACLGrant`` records and delegates the actual
visibility decision to :class:`raku_rag.core.security.acl.AclPolicy`. Tenant binding reuses
:func:`raku_rag.core.tenancy.enforce_same_tenant`.

Mapping (spec FR-MFG-013):
- **department** → base ACL ``group`` (no new entity; a department IS a 001 ACL group). A department
  may optionally be expressed as a ``role`` instead via :class:`ManufacturingScope`.
- **factory**    → the :class:`~raku_rag.manufacturing.domain.entities.Factory` entity, used as the
  ACL *scope* (permission territory unit). A factory grant becomes a 001 ``COLLECTION``-scoped grant
  keyed by the factory_id collection that carries the factory's documents.
- **role**       → base ACL ``role``.
- **equipment-area** → Process/Equipment metadata (``process_id`` / ``equipment_id``), expressed as a
  001 ``DOCUMENT``-scoped grant over the documents tagged with that equipment-area.

Schema/helper only — the visibility predicate itself is 001's. Stage-2 wires concrete grant sources;
this module is the pure translation layer.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from raku_rag.core.security.acl import AclPolicy
from raku_rag.core.tenancy import enforce_same_tenant
from raku_rag.domain.models import ACLGrant, Chunk, IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.domain.entities import Equipment, Factory, Process


@dataclass
class ManufacturingScope:
    """A manufacturing access scope expressed in FR-MFG-013 terms, before 001 translation.

    Every field is OPTIONAL; only the populated dimensions produce 001 grants. ``tenant_id`` is the
    hard isolation boundary ([base:FR-021]) and is stamped onto every emitted :class:`ACLGrant`.

    - ``department`` → 001 ACL group (department IS a group; no new entity, FR-MFG-013).
    - ``roles``      → 001 ACL roles.
    - ``factory_ids``/``factories`` → Factory-entity territory; COLLECTION-scoped grant keyed by
      ``factory_id`` (the factory's document collection).
    - ``equipment_areas`` → Process/Equipment metadata ids; DOCUMENT-scoped grants over the
      equipment-area's tagged documents. Accepts raw ids, Process or Equipment entities.
    """

    tenant_id: str
    subject_type: SubjectType = SubjectType.GROUP
    department: str | None = None  # FR-MFG-013: department == base ACL group
    roles: tuple[str, ...] = ()  # FR-MFG-013: role == base ACL role
    factory_ids: tuple[str, ...] = ()  # FR-MFG-013: factory == Factory entity (territory)
    equipment_areas: tuple[str, ...] = ()  # FR-MFG-013: equipment-area == Process/Equipment id


def _factory_collection_id(factory_id: str) -> str:
    """The 001 collection that holds a factory's documents (factory = ACL territory unit)."""
    return f"factory:{factory_id}"


def department_subject(department: str, *, as_role: bool = False) -> tuple[SubjectType, str]:
    """FR-MFG-013: department maps to a base ACL group (or role) subject — never a new entity."""
    return (SubjectType.ROLE if as_role else SubjectType.GROUP, department)


def factory_scope(factory: Factory | str) -> tuple[ScopeType, str]:
    """FR-MFG-013: a Factory entity maps to a 001 COLLECTION-scoped ACL territory."""
    factory_id = factory.factory_id if isinstance(factory, Factory) else factory
    return (ScopeType.COLLECTION, _factory_collection_id(factory_id))


def equipment_area_scope(area: Process | Equipment | str) -> tuple[ScopeType, str]:
    """FR-MFG-013: equipment-area (Process/Equipment metadata) maps to a 001 DOCUMENT-scoped grant."""
    if isinstance(area, Process):
        area_id = area.process_id
    elif isinstance(area, Equipment):
        area_id = area.equipment_id
    else:
        area_id = area
    return (ScopeType.DOCUMENT, area_id)


def grants_for_scope(scope: ManufacturingScope) -> list[ACLGrant]:
    """Translate a :class:`ManufacturingScope` into 001 ``ACLGrant`` records (read permission).

    Builds NO new authz: each dimension becomes a standard 001 ``ACLGrant`` consumable by
    :class:`AclPolicy`. The subject of every grant is the scope's department/role; factory and
    equipment-area become the grant *scope* (where the subject may read).
    """
    grants: list[ACLGrant] = []
    subjects: list[tuple[SubjectType, str]] = []
    if scope.department is not None:
        subjects.append((scope.subject_type, scope.department))
    subjects.extend((SubjectType.ROLE, r) for r in scope.roles)
    if not subjects:
        return grants

    # Targets = where these subjects may read. Default to the tenant scope when no narrower
    # territory is named (department-wide read within its own tenant).
    targets: list[tuple[ScopeType, str]] = []
    targets.extend(factory_scope(fid) for fid in scope.factory_ids)
    targets.extend(equipment_area_scope(a) for a in scope.equipment_areas)
    if not targets:
        targets.append((ScopeType.TENANT, scope.tenant_id))

    for subject_type, subject_id in subjects:
        for scope_type, scope_id in targets:
            grants.append(
                ACLGrant(
                    tenant_id=scope.tenant_id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    permission="read",
                )
            )
    return grants


def acl_policy_for_scopes(scopes: Iterable[ManufacturingScope]) -> AclPolicy:
    """Build a 001 :class:`AclPolicy` from manufacturing scopes — delegates the decision to 001.

    The returned policy is the *unmodified* 001 deny-by-default engine; this layer only supplies its
    grants. Callers use ``policy.visibility(principal)`` / ``policy.can_read(...)`` exactly as 001.
    """
    grants: list[ACLGrant] = []
    for s in scopes:
        grants.extend(grants_for_scope(s))
    return AclPolicy(grants)


def visibility_filter(scopes: Iterable[ManufacturingScope], principal: IdentityClaims):
    """Return the 001 ``AclPolicy.visibility`` predicate for ``principal`` over manufacturing scopes.

    This is a thin delegation: the predicate IS 001's, not a bespoke manufacturing filter. The
    principal must belong to the policy's tenant (001 tenancy, FR-MFG-013).
    """
    return acl_policy_for_scopes(scopes).visibility(principal)


def can_read_chunk(
    scopes: Iterable[ManufacturingScope],
    principal: IdentityClaims,
    chunk: Chunk,
) -> bool:
    """Convenience: enforce tenant binding then delegate the read decision to 001's ``AclPolicy``."""
    enforce_same_tenant(principal, resource_tenant_id=chunk.tenant_id)
    return visibility_filter(scopes, principal)(chunk)
