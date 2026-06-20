"""T052 — **SECURITY HARD GATE SC-MFG-008** (US6 / FR-MFG-013): department / factory / role /
equipment-area access control as a MAPPING onto the existing 001 ACL — NOT a new authz mechanism.

Mechanism-pin, in the style of ``tests/security/test_acl_leak.py`` + ``test_tenant_isolation.py``
(esp. case5 ``store.last_prefiltered_count``). An unauthorized user (wrong factory / department /
role / equipment-area, or cross-tenant) MUST NOT see a confidential manufacturing document — customer
name + defect + drawing reference — in search, in answer citations (answer is insufficient_evidence
or cites only authorized docs), or surfaced via a draft generated from their context. Leakage = 0.

TDD RED for missing impl: this gate pins the US6 entrypoint contract that wires the
``raku_rag.manufacturing.domain.acl_mapping`` helper (department->001 group/role, factory->Factory
COLLECTION territory, role->role, equipment-area->Process/Equipment DOCUMENT scope) into the LIVE
retrieval ACL of ``ManufacturingSystem`` so the 001 deny-by-default PRE-FILTER (inside
``InMemoryVectorStore.search``) inherits it. The contract under test:

    ``ManufacturingSystem.grant_scope(scope: ManufacturingScope) -> None``
        Translate the manufacturing scope to 001 ``ACLGrant`` records via
        ``acl_mapping.grants_for_scope`` and add them to the SAME 001 ``AclPolicy`` the reused 001
        ``RetrievalService`` consults — building NO bespoke authorization. (Built endpoints today:
        answer / search / drafts = US1/US2/US4. US3 trouble-cases + US5 dashboard are NOT built yet;
        when they land they MUST route their visibility through this SAME ``grant_scope`` / mapping
        helper — do not add a parallel authz path.)

``ManufacturingSystem`` has no such method yet (it only exposes the raw 001 ``grant`` primitive), so
the seeding here that maps department/factory/role/equipment-area onto the 001 ACL FAILS now — RED
for the missing US6 wiring, NOT an unrelated import error. T053–T056 implement ``grant_scope`` by
delegating to the mapping helper; this file must then go GREEN unchanged.

Reuses 001: ``raku_rag.core.security.acl.AclPolicy`` (visibility/can_read), ``enforce_same_tenant``,
the Phase-2 ``acl_mapping`` helper, and the 001 retrieval pre-filter (``store.last_prefiltered_count``).

stdlib only. Authoritative: spec FR-MFG-013, SC-MFG-008; quickstart S7; contracts/mfg-openapi.md §A.
"""

from __future__ import annotations

import unittest

from raku_rag.core.errors import TenantIsolationError
from raku_rag.core.security.acl import AclPolicy
from raku_rag.core.tenancy import enforce_same_tenant
from raku_rag.domain.models import Chunk, Citation, ScopeType, SubjectType
from raku_rag.manufacturing.domain.acl_mapping import (
    ManufacturingScope,
    acl_policy_for_scopes,
    can_read_chunk,
    factory_scope,
    grants_for_scope,
)
from raku_rag.manufacturing.domain.draft import DraftType
from raku_rag.manufacturing.domain.entities import Process
from tests.manufacturing.helpers import claims, fresh, mfg_meta

T = "tenant_mfg"
T_OTHER = "tenant_other"

# Distinctive confidential payload for factory B / quality dept (customer name + defect + drawing).
CUSTOMER = "AcmeMotors"
DEFECT = "cathode-delamination"
DRAWING = "drawing DWG-7781"
CONFIDENTIAL_BODY = (
    f"Customer {CUSTOMER} reported a {DEFECT} defect on the cathode line; see {DRAWING} "
    f"for the affected tolerance. Quality countermeasure pending sign-off."
)
# The query an unauthorized user would fire to try to dredge up the confidential factory-B doc.
PROBE_QUERY = f"{CUSTOMER} {DEFECT} {DRAWING} cathode customer defect"

# Factory-B confidential doc lives in factory B's ACL territory collection (the mapping target).
_, FACTORY_B_COLLECTION = factory_scope("facB")
_, FACTORY_A_COLLECTION = factory_scope("facA")
CONF_DOC = "doc_confidential_B"
CONF_PROC = "proc_quality_B"  # equipment-area (Process) tag on the confidential doc


def _seed(sys) -> None:
    """Seed a CONFIDENTIAL factory-B / quality-dept doc and an unrelated factory-A doc."""
    # Confidential factory-B / quality department / quality-process equipment-area document.
    sys.ingest_manufacturing(
        tenant_id=T,
        collection_id=FACTORY_B_COLLECTION,
        document_id=CONF_DOC,
        text=CONFIDENTIAL_BODY,
        metadata=mfg_meta(
            tenant_id=T,
            document_id=CONF_DOC,
            process_id=CONF_PROC,
        ),
    )
    # A benign factory-A doc the unauthorized maintenance user IS allowed to read (positive baseline).
    sys.ingest_manufacturing(
        tenant_id=T,
        collection_id=FACTORY_A_COLLECTION,
        document_id="doc_factoryA",
        text="Routine lubrication interval for the press is every two weeks per maintenance plan.",
        metadata=mfg_meta(tenant_id=T, document_id="doc_factoryA"),
    )


class TestUs6AclMappingHardGate(unittest.TestCase):
    """SC-MFG-008: 0 leakage of confidential docs to an unauthorized factory/department/role/area."""

    def setUp(self) -> None:
        self.sys = fresh()
        _seed(self.sys)

        # AUTHORIZED principal: factory-B quality department, supervisor role, quality equipment-area.
        # Granted via the US6 mapping entrypoint (department->group, factory->Factory COLLECTION,
        # role->role, equipment-area->Process/Equipment DOCUMENT) — NOT a raw bespoke grant.
        self.authorized_scope = ManufacturingScope(
            tenant_id=T,
            department="quality_dept",
            roles=("supervisor",),
            factory_ids=("facB",),
            equipment_areas=(Process(tenant_id=T, process_id=CONF_PROC, factory_id="facB"),),
        )
        self.sys.grant_scope(self.authorized_scope)  # << missing impl: RED until T053–T056
        self.authorized = claims(T, "qb_user", groups=["quality_dept"], roles=["supervisor"])

        # Also map a factory-A maintenance department scope so the unauthorized user is a real,
        # legitimately-provisioned user (blocks "denied because they have no grants at all").
        self.sys.grant_scope(
            ManufacturingScope(
                tenant_id=T,
                department="maintenance_dept",
                roles=("technician",),
                factory_ids=("facA",),
            )
        )
        # UNAUTHORIZED principal: WRONG factory (A not B), WRONG department, WRONG role, WRONG area.
        self.unauthorized = claims(T, "fa_user", groups=["maintenance_dept"], roles=["technician"])

    # ---------------------------------------------------------------------------------------------
    # (1) Leakage = 0 across search / answer-citation / draft for the unauthorized user.
    # ---------------------------------------------------------------------------------------------
    def test_unauthorized_doc_absent_from_search(self) -> None:
        results = self.sys.search(self.unauthorized, PROBE_QUERY)
        for r in results:
            self.assertNotEqual(
                r.document_id, CONF_DOC, "confidential factory-B doc leaked into search"
            )

    def test_unauthorized_answer_insufficient_or_only_authorized(self) -> None:
        ans = self.sys.answer(self.unauthorized, f"what defect did {CUSTOMER} report?")
        # Either insufficient_evidence (no visible grounding) OR cites only authorized docs.
        if ans.status == "ok":
            for c in ans.citations:
                self.assertNotEqual(c.document_id, CONF_DOC)
        else:
            self.assertEqual(ans.status, "insufficient_evidence")
            self.assertEqual(ans.used_chunks, ())
        # The confidential body MUST NOT appear in the answer text, and the doc never cited.
        for c in ans.citations:
            self.assertNotEqual(
                c.document_id, CONF_DOC, "confidential doc cited to unauthorized user"
            )
        if ans.text:
            self.assertNotIn(CUSTOMER, ans.text)
            self.assertNotIn(DEFECT, ans.text)

    def test_unauthorized_draft_does_not_surface_confidential_doc(self) -> None:
        # A draft the unauthorized user generates from THEIR context must not carry the factory-B doc
        # in its provenance or body. The only authorized grounding they can supply is their own area.
        ans = self.sys.answer(self.unauthorized, f"summary of {CUSTOMER} {DEFECT}")
        draft = self.sys.generate_draft(
            principal=self.unauthorized,
            kind=DraftType.QUALITY_REPORT,
            context_citations=ans.citations,  # whatever the unauthorized user could legitimately see
            source_document_ids=tuple(c.document_id for c in ans.citations),
        )
        self.assertNotIn(CONF_DOC, draft.source_document_ids)
        self.assertNotIn(CONF_DOC, " ".join(draft.source_citations))
        body = repr(draft.content)
        self.assertNotIn(CONF_DOC, body)
        self.assertNotIn(CUSTOMER, body)
        self.assertNotIn(DEFECT, body)

    def test_unauthorized_draft_rejects_directly_passed_confidential_source(self) -> None:
        # GAP-F11 (ACL leakage via drafts, SC-MFG-008): the unauthorized user passes the confidential
        # id DIRECTLY (a forged citation + source_document_ids), bypassing the ACL-filtered answer path
        # the test above relied on. The draft path itself MUST exclude it from provenance/citations.
        forged = Citation(
            kind="text",
            document_id=CONF_DOC,
            source_id="src",
            version=1,
            retrieval_score=0.99,
            chunk_id=f"{CONF_DOC}#0",
        )
        draft = self.sys.generate_draft(
            principal=self.unauthorized,
            kind=DraftType.QUALITY_REPORT,
            context_citations=(forged,),
            source_document_ids=(CONF_DOC,),
        )
        self.assertNotIn(CONF_DOC, draft.source_document_ids)
        self.assertNotIn(CONF_DOC, " ".join(draft.source_citations))
        body = repr(draft.content)
        self.assertNotIn(CONF_DOC, body)
        self.assertNotIn(CUSTOMER, body)
        self.assertNotIn(DEFECT, body)

    def test_authorized_user_directly_passed_source_is_kept(self) -> None:
        # POSITIVE CONTROL: the authorized factory-B/quality user MAY use their own confidential doc
        # as a draft source — blocks a degenerate "drop everything" implementation.
        draft = self.sys.generate_draft(
            principal=self.authorized,
            kind=DraftType.QUALITY_REPORT,
            source_document_ids=(CONF_DOC,),
        )
        self.assertIn(CONF_DOC, draft.source_document_ids)

    def test_tombstoned_source_excluded_from_draft(self) -> None:
        # GAP-F10 (deleted-content via drafts): a deleted (tombstoned) doc the user COULD otherwise
        # read must still be excluded from a draft source (data-model.md:86 immediate tombstone
        # exclusion). doc_factoryA is readable by the unauthorized user until it is deleted.
        self.sys.delete_document(tenant_id=T, document_id="doc_factoryA", actor=self.unauthorized)
        draft = self.sys.generate_draft(
            principal=self.unauthorized,
            kind=DraftType.QUALITY_REPORT,
            source_document_ids=("doc_factoryA",),
        )
        self.assertNotIn("doc_factoryA", draft.source_document_ids)

    # ---------------------------------------------------------------------------------------------
    # (2) PRE-FILTER (not post-filter): the confidential chunk is excluded BEFORE scoring.
    #     A post-filter impl that returns the right output but scored the doc first FAILS here.
    #     (Mirrors tests/security/test_tenant_isolation.py case5 last_prefiltered_count.)
    # ---------------------------------------------------------------------------------------------
    def test_prefilter_excludes_confidential_before_scoring(self) -> None:
        self.sys.search(self.unauthorized, PROBE_QUERY)
        prefiltered = self.sys._mvp.store.last_prefiltered_count
        # Only the factory-A doc the unauthorized user MAY read survives the pre-filter; the
        # confidential factory-B doc is gone before any cosine score is computed.
        self.assertEqual(
            prefiltered,
            1,
            "exactly the one factory-A chunk visible to the unauthorized user should be pre-filtered "
            "in — the confidential factory-B chunk must be excluded BEFORE scoring (pre-, not post-filter)",
        )

    def test_prefilter_admits_confidential_only_for_authorized(self) -> None:
        # Positive side of the pre-filter mechanism: the authorized user's pre-filter set INCLUDES
        # the confidential chunk (proves the count above is a real ACL boundary, not e.g. an empty index).
        self.sys.search(self.authorized, PROBE_QUERY)
        prefiltered = self.sys._mvp.store.last_prefiltered_count
        self.assertEqual(
            prefiltered,
            1,
            "the authorized factory-B/quality user's pre-filter must admit exactly the confidential "
            "factory-B chunk (they cannot read the factory-A doc)",
        )

    # ---------------------------------------------------------------------------------------------
    # (3) POSITIVE CONTROL: the authorized factory-B / quality-dept user CAN see the doc.
    #     Blocks a degenerate "deny everything" implementation.
    # ---------------------------------------------------------------------------------------------
    def test_authorized_user_can_search_confidential_doc(self) -> None:
        results = self.sys.search(self.authorized, PROBE_QUERY)
        self.assertTrue(
            any(r.document_id == CONF_DOC for r in results),
            "authorized factory-B/quality user must be able to find their own confidential doc",
        )

    def test_authorized_user_can_cite_confidential_doc(self) -> None:
        ans = self.sys.answer(self.authorized, f"what defect did {CUSTOMER} report?")
        self.assertEqual(ans.status, "ok")
        self.assertTrue(
            any(c.document_id == CONF_DOC for c in ans.citations),
            "authorized user must be able to ground an answer on their confidential doc",
        )

    # ---------------------------------------------------------------------------------------------
    # (4) CROSS-TENANT: a different-tenant user is rejected (reuse 001 enforce_same_tenant).
    # ---------------------------------------------------------------------------------------------
    def test_cross_tenant_user_sees_nothing(self) -> None:
        # A user in a DIFFERENT tenant, even granted an identically-shaped factory-B scope in their
        # own tenant, sees none of tenant_mfg's confidential docs (001 structural tenant boundary).
        self.sys.grant_scope(
            ManufacturingScope(tenant_id=T_OTHER, department="quality_dept", factory_ids=("facB",))
        )
        foreign = claims(T_OTHER, "outsider", groups=["quality_dept"])
        results = self.sys.search(foreign, PROBE_QUERY)
        for r in results:
            self.assertNotEqual(r.document_id, CONF_DOC)
        ans = self.sys.answer(foreign, f"what defect did {CUSTOMER} report?")
        for c in ans.citations:
            self.assertNotEqual(c.document_id, CONF_DOC)

    def test_cross_tenant_chunk_rejected_by_001_tenancy(self) -> None:
        # The mapping helper binds tenant via 001 enforce_same_tenant before any visibility decision.
        foreign = claims(T_OTHER, "outsider", groups=["quality_dept"])
        foreign_view_of_conf = Chunk(
            tenant_id=T,  # resource is tenant_mfg's confidential doc
            chunk_id=f"{CONF_DOC}#0",
            document_id=CONF_DOC,
            collection_id=FACTORY_B_COLLECTION,
            text=CONFIDENTIAL_BODY,
        )
        with self.assertRaises(TenantIsolationError):
            can_read_chunk([self.authorized_scope], foreign, foreign_view_of_conf)
        # And the raw 001 primitive agrees structurally.
        with self.assertRaises(TenantIsolationError):
            enforce_same_tenant(foreign, resource_tenant_id=T)

    # ---------------------------------------------------------------------------------------------
    # (5) MAPPING: department->001 group/role, factory->Factory COLLECTION, role->role,
    #     equipment-area->Process/Equipment DOCUMENT scope drive the 001 visibility decision.
    #     Assert the helper produces a 001 AclPolicy filter, not a bespoke one.
    # ---------------------------------------------------------------------------------------------
    def test_mapping_produces_real_001_aclpolicy(self) -> None:
        policy = acl_policy_for_scopes([self.authorized_scope])
        self.assertIsInstance(
            policy, AclPolicy, "mapping must yield the 001 AclPolicy, not a bespoke one"
        )

    def test_mapping_emits_001_grants_for_every_dimension(self) -> None:
        grants = grants_for_scope(self.authorized_scope)
        # department -> base ACL group subject
        self.assertTrue(
            any(
                g.subject_type == SubjectType.GROUP and g.subject_id == "quality_dept"
                for g in grants
            ),
            "department must map to a base ACL group subject (FR-MFG-013)",
        )
        # role -> base ACL role subject
        self.assertTrue(
            any(
                g.subject_type == SubjectType.ROLE and g.subject_id == "supervisor" for g in grants
            ),
            "role must map to a base ACL role subject (FR-MFG-013)",
        )
        # factory -> COLLECTION-scoped territory keyed by the factory collection
        self.assertTrue(
            any(
                g.scope_type == ScopeType.COLLECTION and g.scope_id == FACTORY_B_COLLECTION
                for g in grants
            ),
            "factory must map to a 001 COLLECTION-scoped Factory territory (FR-MFG-013)",
        )
        # equipment-area -> DOCUMENT-scoped Process/Equipment metadata
        self.assertTrue(
            any(g.scope_type == ScopeType.DOCUMENT and g.scope_id == CONF_PROC for g in grants),
            "equipment-area must map to a 001 DOCUMENT-scoped Process/Equipment id (FR-MFG-013)",
        )
        # every emitted grant is a 001 read grant in the right tenant — no new permission verb.
        for g in grants:
            self.assertEqual(g.permission, "read")
            self.assertEqual(g.tenant_id, T)

    def test_mapping_predicate_decides_visibility_via_001(self) -> None:
        # The mapping's read decision IS the 001 AclPolicy decision: authorized sees the confidential
        # chunk, the wrong-department/wrong-factory user does not.
        conf_chunk = Chunk(
            tenant_id=T,
            chunk_id=f"{CONF_DOC}#0",
            document_id=CONF_DOC,
            collection_id=FACTORY_B_COLLECTION,
            text=CONFIDENTIAL_BODY,
        )
        unauth_scope = ManufacturingScope(
            tenant_id=T, department="maintenance_dept", roles=("technician",), factory_ids=("facA",)
        )
        self.assertTrue(can_read_chunk([self.authorized_scope], self.authorized, conf_chunk))
        self.assertFalse(can_read_chunk([unauth_scope], self.unauthorized, conf_chunk))


if __name__ == "__main__":
    unittest.main()
