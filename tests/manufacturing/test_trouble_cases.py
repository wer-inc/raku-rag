"""T033 — Similar-trouble-case retrieval INTEGRATION + two load-bearing invariants (US3).

Seeds past TroubleCases, fires the symptom query "振動増加 + 異音" (vibration increase + abnormal
noise), and asserts the similar TroubleCases come back with their FailureMode (cause), Countermeasure,
recurrence-prevention note, and citations. On top of that base behaviour it pins TWO invariants that
are mechanism, not output:

  (a) HARD RULE 4 (FR-MFG-009): a Countermeasure whose source is a PAST TroubleCase is displayed as a
      candidate / past-example EVEN WHEN ``measure_class=permanent`` — it is NEVER presented as a
      definitive work order. provisional vs permanent is shown as a SEPARATE measure_class axis.

  (b) ACL (extends SC-MFG-008 to this endpoint): trouble-case search routes through the SAME US6
      ``grant_scope`` / ``acl_mapping`` seam + the reused 001 retrieval PRE-filter. A user WITHOUT the
      owning factory/department scope MUST NOT see a confidential TroubleCase (customer / defect) in
      results OR citations. POSITIVE CONTROL: the authorized user DOES see it (blocks a degenerate
      "deny everything"). PRE-filter (not post-filter): the confidential chunk is excluded BEFORE
      scoring (mirrors tests/security/test_tenant_isolation.py case5 last_prefiltered_count).

This builds NO new authz / retrieval / labelling mechanism: the visibility decision is 001's
deny-by-default ACL (reached via ``grant_scope``), and retrieval is the 001 RetrievalService. US3
MUST wire through the SAME helper US6 built — not a parallel path.

TDD: RED now because ``raku_rag.manufacturing.app.ManufacturingSystem`` has no trouble-case
entrypoints yet (missing-impl on register_trouble_case / search_trouble_cases), NOT an unrelated
import error. T034–T037 implement them; this file must then go GREEN unchanged.

Reuses 001: RetrievalService + the 001 ACL PRE-filter (``store.last_prefiltered_count``), the Phase-2
entities (TroubleCase/FailureMode/Countermeasure/TroubleCaseResult), the US6
``acl_mapping.grant_scope`` seam, and AuditLogWriter.

stdlib only. Authoritative: spec FR-MFG-008/009, Hard Rule 4; quickstart S5; contracts/mfg-openapi.md
§C; data-model §D; SC-MFG-008 (extended to this endpoint).
"""
from __future__ import annotations

import unittest

from raku_rag.manufacturing.domain.acl_mapping import ManufacturingScope, factory_scope
from raku_rag.manufacturing.domain.entities import (
    Countermeasure,
    CountermeasureType,
    FailureMode,
    MeasureClass,
    TroubleCase,
)
from tests.manufacturing.helpers import claims, fresh, mfg_meta

T = "tenant_mfg"
T_OTHER = "tenant_other"

# ------------------------------------------------------------------------------------------------
# A NON-confidential past TroubleCase: gearbox vibration + abnormal noise, bearing wear cause, with
# a PROVISIONAL and a PERMANENT countermeasure. Lives in factory A's collection (both principals may
# read it) so the Hard-Rule-4 assertions are about LABELLING, not visibility.
# ------------------------------------------------------------------------------------------------
_, FACTORY_A_COLLECTION = factory_scope("facA")
_, FACTORY_B_COLLECTION = factory_scope("facB")

SHARED_TC_BODY = (
    "Trouble report: the gearbox showed vibration increase and abnormal noise. Root cause: bearing "
    "wear. Provisional countermeasure: reduce feed rate and monitor closely. Permanent "
    "countermeasure: replace the worn bearing and install a vibration sensor. Recurrence prevention: "
    "add the bearing to the periodic replacement schedule."
)
SYMPTOM_QUERY = "振動増加 異音 vibration increase abnormal noise gearbox bearing"

# ------------------------------------------------------------------------------------------------
# A CONFIDENTIAL past TroubleCase owned by factory B / quality dept: a customer-named defect case.
# Its body shares the SAME symptom vocabulary so a naive (no-ACL) retriever WOULD surface it for the
# symptom query — that is exactly what the ACL pre-filter must prevent for an unauthorized user.
# ------------------------------------------------------------------------------------------------
CUSTOMER = "AcmeMotors"
DEFECT = "cathode-delamination"
CONF_TC_BODY = (
    f"Trouble report (confidential): customer {CUSTOMER} cathode line showed vibration increase and "
    f"abnormal noise preceding a {DEFECT} defect. Root cause: spindle imbalance. Permanent "
    f"countermeasure: rebalance and replace the spindle assembly. Recurrence prevention: tighten the "
    f"incoming inspection for {CUSTOMER}."
)
CONF_DOC = "tr_doc_confidential_B"
CONF_TC = "tc_confidential_B"
CONF_PROC = "proc_quality_B"
# A probe an unauthorized user fires hoping to dredge up the confidential customer case.
PROBE_QUERY = f"{CUSTOMER} {DEFECT} vibration increase abnormal noise customer defect"


def _seed_shared_case(sys) -> None:
    """A non-confidential factory-A gearbox case with provisional + permanent countermeasures."""
    sys.register_trouble_case(
        tenant_id=T,
        collection_id=FACTORY_A_COLLECTION,
        source_document_id="tr_doc_A",
        text=SHARED_TC_BODY,
        metadata=mfg_meta(tenant_id=T, document_id="tr_doc_A"),
        trouble_case=TroubleCase(
            tenant_id=T,
            trouble_case_id="tc_A",
            symptom="振動増加＋異音",
            equipment_id="eq_gearbox",
            process_id="pr_assembly",
            failure_mode_id="fm_bearing",
            source_document_id="tr_doc_A",
        ),
        failure_mode=FailureMode(
            tenant_id=T,
            failure_mode_id="fm_bearing",
            name="軸受摩耗",
            description="bearing wear from prolonged load",
        ),
        countermeasures=(
            Countermeasure(
                tenant_id=T,
                measure_id="m_A_prov",
                trouble_case_id="tc_A",
                description="reduce feed rate and monitor closely",
                measure_class=MeasureClass.PROVISIONAL,
                source_document_id="tr_doc_A",
            ),
            Countermeasure(
                tenant_id=T,
                measure_id="m_A_perm",
                trouble_case_id="tc_A",
                description="replace the worn bearing and install a vibration sensor",
                # Stored as PERMANENT (恒久) — Hard Rule 4: a permanent past-case measure is STILL
                # displayed as a candidate / past-example, never a definitive work order.
                measure_class=MeasureClass.PERMANENT,
                source_document_id="tr_doc_A",
            ),
        ),
        recurrence_prevention="add the bearing to the periodic replacement schedule",
    )


def _seed_confidential_case(sys) -> None:
    """A CONFIDENTIAL factory-B / quality-dept customer-defect TroubleCase (ACL-controlled)."""
    sys.register_trouble_case(
        tenant_id=T,
        collection_id=FACTORY_B_COLLECTION,
        source_document_id=CONF_DOC,
        text=CONF_TC_BODY,
        metadata=mfg_meta(
            tenant_id=T, document_id=CONF_DOC, customer=CUSTOMER, defect_type=DEFECT, process_id=CONF_PROC
        ),
        trouble_case=TroubleCase(
            tenant_id=T,
            trouble_case_id=CONF_TC,
            symptom="振動増加＋異音 (customer line)",
            equipment_id="eq_spindle_B",
            process_id=CONF_PROC,
            failure_mode_id="fm_spindle",
            source_document_id=CONF_DOC,
        ),
        failure_mode=FailureMode(
            tenant_id=T, failure_mode_id="fm_spindle", name="主軸アンバランス", description="spindle imbalance"
        ),
        countermeasures=(
            Countermeasure(
                tenant_id=T,
                measure_id="m_B_perm",
                trouble_case_id=CONF_TC,
                description="rebalance and replace the spindle assembly",
                measure_class=MeasureClass.PERMANENT,
                source_document_id=CONF_DOC,
            ),
        ),
        recurrence_prevention=f"tighten the incoming inspection for {CUSTOMER}",
    )


def _enum_value(v):
    return getattr(v, "value", v)


def _all_countermeasures(match):
    return tuple(match.countermeasures.provisional) + tuple(match.countermeasures.permanent)


def _match_for(resp, trouble_case_id):
    for m in resp.results:
        if m.trouble_case_id == trouble_case_id:
            return m
    return None


# ================================================================================================
# Base behaviour + INVARIANT (a): Hard Rule 4.
# ================================================================================================
class TestHardRule4PastCaseCandidate(unittest.TestCase):
    """A past-case countermeasure is candidate/past-example even when permanent (FR-MFG-009)."""

    def setUp(self) -> None:
        self.sys = fresh()
        _seed_shared_case(self.sys)
        # Provision factory-A maintenance scope via the US6 grant_scope seam (NOT a raw grant).
        self.sys.grant_scope(
            ManufacturingScope(
                tenant_id=T,
                department="maintenance_dept",
                roles=("technician",),
                factory_ids=("facA",),
            )
        )
        self.op = claims(T, "fa_user", groups=["maintenance_dept"], roles=["technician"])

    def test_symptom_query_lists_similar_case_with_cause_and_recurrence(self) -> None:
        # Base US3 behaviour: similar TroubleCase + FailureMode (cause) + recurrence + citation.
        resp = self.sys.search_trouble_cases(self.op, SYMPTOM_QUERY)
        self.assertEqual(_enum_value(resp.status), "ok")
        m = _match_for(resp, "tc_A")
        self.assertIsNotNone(m, "the seeded gearbox case must be retrieved for the symptom query")
        self.assertIsNotNone(m.failure_mode)
        self.assertEqual(m.failure_mode.name, "軸受摩耗")
        self.assertTrue(m.recurrence_prevention)
        self.assertTrue(m.citations, "the similar case must be cited (出典つき)")
        self.assertTrue(any(c.document_id == "tr_doc_A" for c in m.citations))

    def test_provisional_and_permanent_kept_on_separate_axis(self) -> None:
        # G4 / FR-MFG-008: provisional vs permanent is the measure_class axis, SEPARATE buckets.
        m = _match_for(self.sys.search_trouble_cases(self.op, SYMPTOM_QUERY), "tc_A")
        self.assertIsNotNone(m)
        prov_ids = {c.measure_id for c in m.countermeasures.provisional}
        perm_ids = {c.measure_id for c in m.countermeasures.permanent}
        self.assertIn("m_A_prov", prov_ids, "provisional measure must be in the provisional bucket")
        self.assertIn("m_A_perm", perm_ids, "permanent measure must be in the permanent bucket")
        self.assertEqual(prov_ids & perm_ids, set(), "the two measure_class buckets must be disjoint")
        for c in m.countermeasures.provisional:
            self.assertEqual(_enum_value(c.measure_class), MeasureClass.PROVISIONAL.value)
        for c in m.countermeasures.permanent:
            self.assertEqual(_enum_value(c.measure_class), MeasureClass.PERMANENT.value)

    def test_permanent_past_case_measure_is_candidate_not_definitive(self) -> None:
        # HARD RULE 4 (the load-bearing assertion): the PERMANENT measure that came FROM a past
        # TroubleCase is displayed as candidate / past-example — NOT a definitive work instruction —
        # even though its measure_class is permanent.
        m = _match_for(self.sys.search_trouble_cases(self.op, SYMPTOM_QUERY), "tc_A")
        self.assertIsNotNone(m)
        self.assertTrue(m.countermeasures.permanent, "expected the permanent past-case measure")
        perm = next(c for c in m.countermeasures.permanent if c.measure_id == "m_A_perm")
        # measure_class is still permanent (the nature axis is preserved, NOT overwritten)...
        self.assertEqual(_enum_value(perm.measure_class), MeasureClass.PERMANENT.value)
        # ...but the DISPLAY type is candidate (the evidence/display axis), never a definitive order.
        self.assertEqual(
            _enum_value(perm.type),
            CountermeasureType.CANDIDATE.value,
            "Hard Rule 4: a permanent past-case countermeasure must display as candidate, not definitive",
        )
        # The display type is one of the two non-definitive display classes — never "definitive".
        self.assertIn(
            _enum_value(perm.type),
            (CountermeasureType.CANDIDATE.value, CountermeasureType.REFERENCE.value),
            "a past-case countermeasure's display type must be candidate/reference, not definitive",
        )
        # The display label marks it as a past-example candidate (not an authoritative work order).
        self.assertTrue(perm.label, "a candidate/past-example label must be present")
        # Mechanism check: the label must NOT read as a definitive work instruction / official order.
        label = perm.label
        for forbidden in ("正式手順", "正式作業指示", "definitive work order", "official work instruction"):
            self.assertNotIn(
                forbidden,
                label,
                "a past-case countermeasure must NOT be labelled a definitive/official work order",
            )

    def test_every_displayed_countermeasure_is_candidate(self) -> None:
        m = _match_for(self.sys.search_trouble_cases(self.op, SYMPTOM_QUERY), "tc_A")
        self.assertIsNotNone(m)
        cms = _all_countermeasures(m)
        self.assertTrue(cms)
        for c in cms:
            self.assertEqual(
                _enum_value(c.type),
                CountermeasureType.CANDIDATE.value,
                "all past-case countermeasures (provisional AND permanent) display as candidate",
            )
            self.assertTrue(c.label, "every displayed countermeasure carries a candidate/reference label")


# ================================================================================================
# INVARIANT (b): ACL on trouble-cases (extends SC-MFG-008), routed through the US6 grant_scope seam.
# ================================================================================================
class TestTroubleCaseAclHardGate(unittest.TestCase):
    """A confidential TroubleCase never leaks to an unauthorized user; PRE-filter routed; +ve control."""

    def setUp(self) -> None:
        self.sys = fresh()
        _seed_shared_case(self.sys)
        _seed_confidential_case(self.sys)

        # AUTHORIZED principal: factory-B quality dept + the confidential case's equipment-area.
        # Granted ONLY via the US6 grant_scope/acl_mapping seam (department->group, factory->Factory
        # COLLECTION, equipment-area->Process DOCUMENT) — the SAME path US6 built, no parallel authz.
        from raku_rag.manufacturing.domain.entities import Process

        self.authorized_scope = ManufacturingScope(
            tenant_id=T,
            department="quality_dept",
            roles=("supervisor",),
            factory_ids=("facB",),
            equipment_areas=(Process(tenant_id=T, process_id=CONF_PROC, factory_id="facB"),),
        )
        self.sys.grant_scope(self.authorized_scope)
        self.authorized = claims(T, "qb_user", groups=["quality_dept"], roles=["supervisor"])

        # UNAUTHORIZED principal: a real, legitimately-provisioned factory-A maintenance user with
        # the WRONG factory / department / role / equipment-area (so denial is ACL, not "no grants").
        self.sys.grant_scope(
            ManufacturingScope(
                tenant_id=T,
                department="maintenance_dept",
                roles=("technician",),
                factory_ids=("facA",),
            )
        )
        self.unauthorized = claims(T, "fa_user", groups=["maintenance_dept"], roles=["technician"])

    # --- leakage = 0 in RESULTS -------------------------------------------------------------------
    def test_unauthorized_user_does_not_see_confidential_case_in_results(self) -> None:
        resp = self.sys.search_trouble_cases(self.unauthorized, PROBE_QUERY)
        for m in resp.results:
            self.assertNotEqual(
                m.trouble_case_id, CONF_TC, "confidential factory-B TroubleCase leaked into results"
            )
            # the confidential customer/defect must not ride along on any field of the match
            blob = repr(m)
            self.assertNotIn(CUSTOMER, blob, "confidential customer name leaked into a result")
            self.assertNotIn(DEFECT, blob, "confidential defect leaked into a result")

    # --- leakage = 0 in CITATIONS -----------------------------------------------------------------
    def test_unauthorized_user_does_not_see_confidential_case_in_citations(self) -> None:
        resp = self.sys.search_trouble_cases(self.unauthorized, PROBE_QUERY)
        for m in resp.results:
            for c in m.citations:
                self.assertNotEqual(
                    c.document_id, CONF_DOC, "confidential TroubleCase source cited to unauthorized user"
                )

    # --- PRE-filter (not post-filter): confidential chunk excluded BEFORE scoring -----------------
    def test_prefilter_excludes_confidential_trouble_case_before_scoring(self) -> None:
        # Mirrors tests/security/test_tenant_isolation.py case5: the unauthorized factory-A user's
        # pre-filter admits ONLY the factory-A gearbox chunk; the confidential factory-B chunk is gone
        # before any cosine score is computed (proves it routes through the 001 deny-by-default
        # PRE-filter via grant_scope, not a post-hoc result scrub).
        self.sys.search_trouble_cases(self.unauthorized, PROBE_QUERY)
        self.assertEqual(
            self.sys._mvp.store.last_prefiltered_count,
            1,
            "exactly the one factory-A chunk visible to the unauthorized user should be pre-filtered "
            "in — the confidential factory-B TroubleCase chunk must be excluded BEFORE scoring",
        )

    def test_prefilter_admits_confidential_only_for_authorized(self) -> None:
        # Positive side of the pre-filter mechanism: the authorized factory-B/quality user's
        # pre-filter set INCLUDES the confidential chunk (and excludes the factory-A doc they cannot
        # read) — proving the count above is a real ACL boundary, not an empty index.
        self.sys.search_trouble_cases(self.authorized, PROBE_QUERY)
        self.assertEqual(
            self.sys._mvp.store.last_prefiltered_count,
            1,
            "the authorized factory-B/quality user's pre-filter must admit exactly the confidential "
            "factory-B TroubleCase chunk (they cannot read the factory-A doc)",
        )

    # --- POSITIVE CONTROL: the authorized user DOES see the confidential case ---------------------
    def test_authorized_user_sees_confidential_case(self) -> None:
        resp = self.sys.search_trouble_cases(self.authorized, PROBE_QUERY)
        self.assertEqual(_enum_value(resp.status), "ok")
        m = _match_for(resp, CONF_TC)
        self.assertIsNotNone(
            m, "authorized factory-B/quality user must be able to find their own confidential case"
        )
        self.assertTrue(
            any(c.document_id == CONF_DOC for c in m.citations),
            "authorized user must get the confidential TroubleCase's source citation",
        )

    # --- CROSS-TENANT: a different-tenant user sees nothing (001 structural boundary) -------------
    def test_cross_tenant_user_sees_no_confidential_case(self) -> None:
        # Even granted an identically-shaped factory-B scope in their OWN tenant, a foreign-tenant
        # user sees none of tenant_mfg's confidential cases (001 enforce_same_tenant / pre-filter).
        self.sys.grant_scope(
            ManufacturingScope(tenant_id=T_OTHER, department="quality_dept", factory_ids=("facB",))
        )
        foreign = claims(T_OTHER, "outsider", groups=["quality_dept"])
        resp = self.sys.search_trouble_cases(foreign, PROBE_QUERY)
        for m in resp.results:
            self.assertNotEqual(m.trouble_case_id, CONF_TC)
            for c in m.citations:
                self.assertNotEqual(c.document_id, CONF_DOC)


if __name__ == "__main__":
    unittest.main()
