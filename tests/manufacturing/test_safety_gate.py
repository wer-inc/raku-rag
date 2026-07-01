"""T014 — SAFETY HARD GATE SC-MFG-006 (FR-MFG-005/007/015/030).

This is an ABSOLUTE gate (loop-engineering §3 mechanism-pin): a classifier false-negative on danger,
or an asserted high-risk answer without an approved+effective citation, MUST fail this test. The
essence is **classifier recall on danger** plus the **approved-citation-required** block with its
**reason code**.

Mechanism pinned (do NOT weaken in stage 2):
 (1) LABELED high-risk set — intent variants AND metadata variants — every one MUST be high_risk.
     A false-negative (high_risk False on any labeled-dangerous case) FAILS the test.
 (2) high-risk + NO approved/effective citation => status == "insufficient_evidence" AND
     safety_block_reason == "approved_citation_missing" (assert the REASON CODE, not merely "no text").
 (3) POSITIVE CONTROL — high-risk WITH an approved+effective citation => status "ok", asserts,
     requires_onsite_confirmation True. (So a degenerate "block everything" implementation CANNOT pass.)
 (4) AMBIGUOUS query => treated high-risk (fail-safe).

Authoritative: spec FR-MFG-005/007/015/030, SC-MFG-006; contracts/mfg-openapi.md §A + §"安全・監査";
contracts/mfg-interfaces.md §4; quickstart S3; data-model §E. Assertion style mirrors
tests/security/test_acl_leak.py.

TDD: RED now because ``raku_rag.manufacturing.app.ManufacturingSystem`` is unimplemented.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.api.answer_ext import ONSITE_CONFIRMATION_NOTICE
from raku_rag.manufacturing.domain.metadata import ApprovalStatus, DocumentKind
from raku_rag.manufacturing.domain.safety import ClassificationSource
from raku_rag.manufacturing.safety.classifier import RuleHighRiskClassifier
from tests.manufacturing.helpers import T, claims, fresh, mfg_meta

# --- (1) LABELED high-risk set -------------------------------------------------------------------
# Each entry: (label, query, intent_hint). These are queries a field worker would actually ask about
# dangerous work or quality/shipment judgement. EVERY ONE must be classified high-risk; a classifier
# false-negative on ANY of them is a safety failure (FR-MFG-015: stop/disassemble/electrocution/
# high-temp/pressure/chemical/heavy/safety-device/quality-judgement/shipment/customer-impact/
# corrective => high-risk).
HIGH_RISK_INTENT_QUERIES = [
    ("equipment_stop", "How do I stop the press line to clear a jam?", None),
    ("disassembly", "How do I disassemble the gearbox to inspect the bearing?", None),
    ("electric_shock", "How do I work on the 400V panel without getting electrocuted?", None),
    ("high_temp", "What is the procedure to open the furnace door while it is hot?", None),
    ("pressure", "How do I release the pressure in the hydraulic accumulator?", None),
    ("chemical", "How do I handle the cleaning solvent chemical spill safely?", None),
    ("heavy_object", "How do I lift the heavy die with the crane?", None),
    ("safety_device", "Can I bypass the safety interlock light curtain to keep running?", None),
    ("quality_judgment", "Can I judge this lot as a quality pass with this surface defect?", None),
    (
        "shipment_decision",
        "Is it OK to ship this batch to the customer despite the deviation?",
        None,
    ),
    ("corrective_action", "What corrective action do I take after the safety incident?", None),
    # intent supplied only via the structured hint (query text deliberately terse).
    ("intent_hint_only", "panel work", "electric_shock"),
]


class TestHighRiskClassifierRecall(unittest.TestCase):
    """(1) Every labeled-dangerous query MUST be classified high-risk (recall on danger)."""

    def setUp(self) -> None:
        self.sys = fresh()
        # An UNRELATED non-safety doc so retrieval/answer can run; it is NOT an approved safety doc,
        # so these high-risk queries also exercise (2) the approved-citation-missing block.
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="generic1",
            text="The break room schedule lists lunch from twelve to one each weekday.",
            metadata=mfg_meta(tenant_id=T, document_id="generic1"),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def test_all_labeled_high_risk_queries_are_flagged(self) -> None:
        for label, query, intent in HIGH_RISK_INTENT_QUERIES:
            with self.subTest(label=label):
                ans = self.sys.answer(self.op, query, intent_hint=intent)
                self.assertTrue(
                    ans.high_risk,
                    f"classifier FALSE-NEGATIVE on dangerous query [{label}]: {query!r} "
                    f"was not flagged high-risk (FR-MFG-015 recall on danger)",
                )

    def test_metadata_tagged_doc_makes_query_high_risk(self) -> None:
        # (1b) METADATA variant: even a neutrally-worded query is high-risk when the candidate
        # evidence carries safety/hazard metadata (document-side classification, FR-MFG-015).
        sys = fresh()
        sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="safetydoc",
            text="The maintenance note describes the routine for the station fixture.",
            metadata=mfg_meta(
                tenant_id=T,
                document_id="safetydoc",
                document_kind=DocumentKind.WORK_INSTRUCTION,
                safety_category="lockout_tagout",
                equipment_operation_category="maintenance",
                hazard_tags=("感電", "高圧"),
                process_id="proc9",
                equipment_id="eq7",
            ),
        )
        sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        ans = sys.answer(
            claims(T, "op"), "what does the maintenance note say about the station fixture?"
        )
        self.assertTrue(
            ans.high_risk,
            "candidate evidence carrying safety_category/hazard_tags must force high_risk (metadata "
            "classification, FR-MFG-015)",
        )


class TestApprovedCitationRequired(unittest.TestCase):
    """(2) high-risk + NO approved/effective citation => block with the EXACT reason code."""

    def _seed(self, sys, *, status: ApprovalStatus, effective_date) -> None:
        sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="lockout",
            text=(
                "To disassemble the press, first stop the machine, apply lockout tagout, and "
                "release the stored hydraulic pressure before removing any guard."
            ),
            metadata=mfg_meta(
                tenant_id=T,
                document_id="lockout",
                approval_status=status,
                effective_date=effective_date,
                document_kind=DocumentKind.WORK_INSTRUCTION,
                safety_category="lockout_tagout",
                hazard_tags=("設備停止", "分解", "高圧"),
            ),
        )
        sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")

    def test_no_approved_evidence_blocks_with_approved_citation_missing(self) -> None:
        # The ONLY candidate evidence is a DRAFT safety doc => not an approved+effective citation.
        sys = fresh()
        self._seed(sys, status=ApprovalStatus.DRAFT, effective_date=None)
        ans = sys.answer(claims(T, "op"), "How do I disassemble the press safely?")
        self.assertTrue(ans.high_risk)
        # Hard assertions — the reason code, not merely "no answer".
        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(ans.safety_block_reason, "approved_citation_missing")
        # Must NOT assert a procedure (FR-MFG-005: 承認済み根拠が無い場合は断定してはならない).
        self.assertFalse(
            ans.text, "must not return an asserted procedure without approved evidence"
        )
        self.assertEqual(ans.used_chunks, ())

    def test_expired_effective_date_is_not_valid_evidence(self) -> None:
        # approved but effective_date is in the past/expired? Here we model a FUTURE effective date,
        # i.e. not yet valid → still no VALID approved citation → blocked (effective_date 有効性).
        sys = fresh()
        self._seed(sys, status=ApprovalStatus.APPROVED, effective_date="2099-01-01")
        ans = sys.answer(claims(T, "op"), "How do I disassemble the press safely?")
        self.assertTrue(ans.high_risk)
        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(ans.safety_block_reason, "approved_citation_missing")


class TestPositiveControl(unittest.TestCase):
    """(3) POSITIVE CONTROL — block-everything must NOT pass: approved+effective => asserts."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="lockout_approved",
            text=(
                "To disassemble the press, first stop the machine, apply lockout tagout, and "
                "release the stored hydraulic pressure before removing any guard."
            ),
            metadata=mfg_meta(
                tenant_id=T,
                document_id="lockout_approved",
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-01-10",
                document_kind=DocumentKind.WORK_INSTRUCTION,
                safety_category="lockout_tagout",
                hazard_tags=("設備停止", "分解", "高圧"),
            ),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def test_high_risk_with_approved_effective_citation_answers(self) -> None:
        ans = self.sys.answer(self.op, "How do I disassemble the press safely?")
        self.assertTrue(ans.high_risk, "this is a high-risk query")
        self.assertEqual(
            ans.status, "ok", "approved+effective safety citation must allow the answer"
        )
        self.assertIsNone(
            ans.safety_block_reason, "no block when an approved+effective citation exists"
        )
        self.assertTrue(ans.text)
        self.assertTrue(ans.citations)
        self.assertEqual(ans.citations[0].approval_status, "approved")
        # High-risk hazardous work surfaces the on-site confirmation requirement (FR-MFG-007).
        self.assertTrue(ans.requires_onsite_confirmation)
        self.assertEqual(
            ans.notice,
            ONSITE_CONFIRMATION_NOTICE,
            "high-risk hazardous work must surface the on-site confirmation NOTICE text (FR-MFG-007)",
        )


class TestAmbiguousIsFailSafe(unittest.TestCase):
    """(4) AMBIGUOUS query => treated high-risk (fail-safe; FR-MFG-015 「迷えば high-risk」)."""

    def setUp(self) -> None:
        self.sys = fresh()
        # A bland, non-safety-tagged doc; the query is ambiguous w.r.t. danger.
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="ambi",
            text="The procedure document covers the handling step for the unit on the line.",
            metadata=mfg_meta(tenant_id=T, document_id="ambi"),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def test_ambiguous_query_treated_high_risk(self) -> None:
        # Vague "how do I handle this" — the classifier cannot rule danger out; fail safe to high-risk.
        ans = self.sys.answer(self.op, "how should I handle this?", intent_hint="ambiguous")
        self.assertTrue(
            ans.high_risk,
            "ambiguous/uncertain queries MUST be treated as high-risk (fail-safe, FR-MFG-015)",
        )


class TestPrecisionNegativeControl(unittest.TestCase):
    """(5) PRECISION negative control — pins the complement of recall (loop-engineering §3).

    A benign, well-specified, non-safety query against an APPROVED+effective, non-safety-tagged
    document MUST NOT be over-flagged: high_risk False, answers normally, no on-site confirmation.
    A degenerate "always high-risk" classifier — which would silently over-block every benign
    question — FAILS here. Added at the US1 phase boundary: T014 pinned recall on danger, but
    nothing pinned precision on benign queries.
    """

    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="torque_spec",
            text=(
                "The torque specification for the M8 bolt on the conveyor cover is "
                "twelve newton meters per the assembly standard."
            ),
            # APPROVED + effective, and NO safety/hazard metadata (mfg_meta safe defaults).
            metadata=mfg_meta(tenant_id=T, document_id="torque_spec"),
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        self.op = claims(T, "op")

    def test_benign_specific_query_is_not_high_risk_and_answers(self) -> None:
        ans = self.sys.answer(
            self.op,
            "What is the torque specification for the M8 bolt on the conveyor cover?",
        )
        self.assertFalse(
            ans.high_risk,
            "a benign, well-specified, non-safety query must NOT be flagged high-risk; a degenerate "
            "always-high-risk classifier would silently over-block benign questions (precision)",
        )
        self.assertEqual(
            ans.status, "ok", "benign query backed by an approved+effective doc should answer"
        )
        self.assertIsNone(ans.safety_block_reason)
        self.assertFalse(
            ans.requires_onsite_confirmation, "no on-site confirmation for a non-high-risk query"
        )
        self.assertIsNone(
            ans.notice, "a non-high-risk query must not carry the on-site confirmation notice"
        )


class TestNonHighRiskEvidenceScope(unittest.TestCase):
    """FR-MFG-005/006 SCOPE: approved+effective is required ONLY for high-risk. A benign,
    NON-high-risk query may be answered from non-draft/non-obsolete evidence (e.g. pending_review);
    only draft/obsolete are excluded as primary evidence (FR-MFG-006). Pins against over-blocking
    non-high-risk queries (the gate must not apply the high-risk approved-citation rule universally).
    """

    def test_non_high_risk_pending_review_evidence_answers(self) -> None:
        sys = fresh()
        sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="c",
            document_id="pending1",
            text=(
                "The torque specification for the M8 bolt on the conveyor cover is "
                "twelve newton meters per the assembly standard."
            ),
            # pending_review: NOT approved, but NOT draft/obsolete either => usable for non-high-risk.
            metadata=mfg_meta(
                tenant_id=T,
                document_id="pending1",
                approval_status=ApprovalStatus.PENDING_REVIEW,
                effective_date=None,
            ),
        )
        sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")
        ans = sys.answer(
            claims(T, "op"),
            "What is the torque specification for the M8 bolt on the conveyor cover?",
        )
        self.assertFalse(ans.high_risk, "benign query is not high-risk")
        self.assertEqual(
            ans.status,
            "ok",
            "a non-high-risk query backed by non-draft/non-obsolete (pending_review) evidence must "
            "answer; approved+effective is required only for high-risk (FR-MFG-005)",
        )
        self.assertIsNone(ans.safety_block_reason)


class TestHighRiskQuerySignal(unittest.TestCase):
    """`ManufacturingSystem.is_high_risk_query_signal` / `ManufacturingAnswerService.
    classify_query_signal` (chatbot-conversational-agent-roadmap P3 safety fix; see
    `chatbot/coreference.py`'s module docstring "Finding"). A retrieval-independent, CONCRETE
    pre-check the chatbot coreference rewrite consults, before any retrieval runs this turn, to
    decide whether it is safe to enrich a follow-up's outgoing query text. Deliberately NARROWER
    than plain `classifier.classify(...).is_high_risk` — see the ambiguous-exclusion test below,
    which is the property this method exists to encode.
    """

    def test_concrete_intent_keyword_query_is_flagged(self) -> None:
        sys = fresh()
        self.assertTrue(
            sys.is_high_risk_query_signal(
                "How do I release the pressure in the hydraulic accumulator?"
            )
        )
        self.assertTrue(sys.is_high_risk_query_signal("その圧力の抜き方を教えて"))

    def test_benign_well_specified_query_is_not_flagged(self) -> None:
        sys = fresh()
        self.assertFalse(
            sys.is_high_risk_query_signal(
                "where is the employee cafeteria located inside building seven"
            )
        )

    def test_short_ambiguous_japanese_query_is_not_flagged_despite_the_classifier_failing_safe(
        self,
    ) -> None:
        # The critical distinction this method exists for: RuleHighRiskClassifier.classify(...) on a
        # bare, terse Japanese sentence fails safe to is_high_risk=True via the stage-3 "ambiguous"
        # catch-all (core.text.content_tokens cannot word-segment CJK text, so a whole short sentence
        # collapses to one "token", under the classifier's 3-token floor) -- correct for the FINAL
        # "may this answer assert" decision, but NOT itself evidence that THIS query text names a
        # concrete hazard. This exact follow-up is P3's own flagship coreference scenario
        # (test_chatbot_coreference.py / test_chatbot_service.py's ChatbotL2CoreferenceTest);
        # treating the ambiguous fail-safe as a "this query is dangerous" signal here would block the
        # coreference rewrite for nearly every short Japanese follow-up, with no safety benefit (the
        # real classifier + safety gate still run for real, unaffected, on whatever text reaches
        # `inner.answer(...)`).
        classifier = RuleHighRiskClassifier()
        premise = classifier.classify("その締付トルクは?", ())
        self.assertTrue(
            premise.is_high_risk, "premise: the raw classifier DOES fail safe to high_risk here"
        )
        self.assertEqual(premise.classification_source, ClassificationSource.RULE)

        sys = fresh()
        self.assertFalse(
            sys.is_high_risk_query_signal("その締付トルクは?"),
            "the concrete-signal pre-check must not treat the ambiguous fail-safe as a danger signal",
        )


if __name__ == "__main__":
    unittest.main()
