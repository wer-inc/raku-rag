"""U19 (追い質問の文脈維持 on the Answers screen) — the answer path's follow-up context carry.

The Answers screen renders a THREAD but historically sent only `{query, collection_id}`, so a
referential follow-up (「その締付トルクは?」) lost the prior turn's identifier entirely. The fix
reuses the chatbot L2 rung's deterministic coreference logic — now shared in
`raku_rag.core.coreference` — on `/internal/manufacturing/answer` via an optional `history` field:
the rewritten standalone query drives RETRIEVAL while the RAW follow-up is threaded as
`intent_query`, the SAFETY INVARIANT the chatbot established (chatbot/coreference.py's "Finding":
high-risk classification + the approved-citation requirement must bind to what the user actually
asked, never to prior-turn terms the rewrite carried in).

Three mandatory proofs, replayed through the ANSWER path (`ManufacturingSystem.answer`, exactly the
two-line application `apps/answer-service/server.py` performs — the HTTP wire itself is covered by
tests/integration/test_answer_followup_endpoint.py):
  (a) the benign P-101 torque follow-up now answers with the RIGHT citation;
  (b) a dangerous follow-up (「その圧力の抜き方を教えて」 style, mirroring
      tests/unit/test_chatbot_service.py's ChatbotL2CoreferenceHighRiskSafetyTest scenarios — those
      protected tests are NOT modified) still classifies high-risk from the RAW text and blocks
      APPROVED_CITATION_MISSING when the on-topic document is not approved;
  (c) no history / non-referential => behavior byte-identical to today.

Stdlib-only (offline, in-memory ManufacturingSystem), consistent with Track A.
"""

from __future__ import annotations

import dataclasses
import unittest

from raku_rag.core.coreference import followup_from_history
from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.domain.metadata import ApprovalStatus
from tests.manufacturing.helpers import mfg_meta

T = "tenant_answer_followup"


def _principal() -> IdentityClaims:
    return IdentityClaims(tenant_id=T, user_id="alice")


def _comparable(ans) -> dict:
    """A ManufacturingAnswer as a comparable dict, with only the inherently per-call/per-boot
    diagnostics normalized: correlation_id (fresh uuid) dropped, floats rounded (retrieval scores
    carry a wall-clock freshness component that drifts ~1e-8 between calls), and ingest wall-clock
    timestamps blanked (two identically-built systems ingest microseconds apart). Every
    decision-bearing field — status, text, citations, safety extension — is compared exactly."""

    _CLOCK_KEYS = {"indexed_at", "updated_at", "source_freshness"}

    def norm(value):
        if isinstance(value, float):
            return round(value, 6)
        if isinstance(value, dict):
            return {k: ("<ts>" if k in _CLOCK_KEYS and v else norm(v)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [norm(v) for v in value]
        return value

    payload = dataclasses.asdict(ans)
    payload.pop("correlation_id", None)
    return norm(payload)


class FollowupFromHistoryTest(unittest.TestCase):
    """The pure resolution function the answer endpoint applies to the optional `history` field."""

    HISTORY = [{"question": "P-101 の点検手順を教えて", "cited_document_ids": ["eq-p101"]}]

    def test_no_history_returns_query_unchanged_with_no_intent(self):
        self.assertEqual(
            followup_from_history("その締付トルクは?", None), ("その締付トルクは?", None)
        )
        self.assertEqual(
            followup_from_history("その締付トルクは?", []), ("その締付トルクは?", None)
        )

    def test_non_referential_query_is_untouched_even_with_history(self):
        query = "締付トルクの基準は?"
        self.assertEqual(followup_from_history(query, self.HISTORY), (query, None))

    def test_query_naming_its_own_identifier_is_never_rewritten(self):
        query = "P-101のその締付トルクは?"
        self.assertEqual(followup_from_history(query, self.HISTORY), (query, None))

    def test_referential_followup_carries_previous_question_identifier_and_raw_intent(self):
        retrieval_query, intent_query = followup_from_history("その締付トルクは?", self.HISTORY)

        self.assertIn("その締付トルクは?", retrieval_query)
        self.assertIn("p-101", retrieval_query.casefold())
        self.assertEqual(intent_query, "その締付トルクは?")

    def test_falls_back_to_cited_document_ids_when_previous_question_names_no_identifier(self):
        history = [
            {"question": "モータの端子台トルクは?", "cited_document_ids": ["eq-motor-m8-torque"]}
        ]

        retrieval_query, intent_query = followup_from_history("その値は?", history)

        self.assertIn("eq-motor-m8-torque", retrieval_query)
        self.assertEqual(intent_query, "その値は?")

    def test_most_recent_usable_turn_anchors_the_reference(self):
        history = [
            {"question": "X-900 の点検手順を教えて", "cited_document_ids": ["eq-x900"]},
            {"question": "P-101 の点検手順を教えて", "cited_document_ids": ["eq-p101"]},
            {"question": "   ", "cited_document_ids": ["ignored-blank-question-turn"]},
        ]

        retrieval_query, _ = followup_from_history("その締付トルクは?", history)

        self.assertIn("p-101", retrieval_query.casefold())
        self.assertNotIn("x-900", retrieval_query.casefold())
        self.assertNotIn("ignored-blank-question-turn", retrieval_query)

    def test_turns_older_than_the_server_cap_are_ignored(self):
        # 6 turns, only the OLDEST has a usable question: the cap (5) drops it, so there is nothing
        # to resolve against and the call must stay byte-identical.
        history = [{"question": "P-101 の点検手順を教えて"}] + [{"question": ""}] * 5

        self.assertEqual(
            followup_from_history("その締付トルクは?", history), ("その締付トルクは?", None)
        )

    def test_rewrite_that_adds_nothing_reports_no_context_carry(self):
        # Every carryable term of the prior turn already appears in the query => rewritten == query
        # => (query, None), so the caller does not report a context carry that never happened.
        history = [{"question": "その締付トルクは?"}]

        self.assertEqual(
            followup_from_history("その締付トルクは?", history), ("その締付トルクは?", None)
        )

    def test_malformed_history_entries_are_ignored_not_fatal(self):
        history = ["not-a-mapping", 42, None, {"question": "P-101 の点検手順を教えて"}]

        retrieval_query, intent_query = followup_from_history("その締付トルクは?", history)

        self.assertIn("p-101", retrieval_query.casefold())
        self.assertEqual(intent_query, "その締付トルクは?")


class AnswerPathFollowupContextTest(unittest.TestCase):
    """Proof (a)+(c): the P-101 torque scenario (the chatbot L2 flagship, replayed through the
    ANSWER path) and the no-history byte-identical guarantee.

    Corpus has TWO equipment documents with DIFFERENT torque values so "answered at all" cannot
    masquerade as "answered correctly": without the carried identifier the follow-up's own terms
    (締付トルク) match both documents and the wrong equipment's value wins.
    """

    def _system(self) -> ManufacturingSystem:
        mfg_sys = ManufacturingSystem()
        for document_id, text in (
            (
                "eq-p101",
                "P-101の点検手順は電源停止、外観確認、記録の順です。締付トルクは25N・mです。",
            ),
            ("eq-p203", "P-203の点検手順は加圧停止、清掃、記録の順です。締付トルクは60N・mです。"),
        ):
            mfg_sys.ingest_manufacturing(
                tenant_id=T,
                collection_id="manuals",
                document_id=document_id,
                text=text,
                metadata=mfg_meta(
                    tenant_id=T,
                    document_id=document_id,
                    approval_status=ApprovalStatus.APPROVED,
                    effective_date="2026-01-01",
                ),
            )
        mfg_sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        return mfg_sys

    def _answer_with_history(self, mfg_sys: ManufacturingSystem, query: str, history):
        """Exactly the two-line application `/internal/manufacturing/answer` performs."""
        retrieval_query, intent_query = followup_from_history(query, history)
        ans = mfg_sys.answer(_principal(), retrieval_query, "manuals", intent_query=intent_query)
        return ans, retrieval_query, intent_query

    HISTORY = [{"question": "P-101 の点検手順を教えて", "cited_document_ids": ["eq-p101"]}]

    def test_benign_referential_followup_answers_with_the_right_citation(self):
        ans, retrieval_query, intent_query = self._answer_with_history(
            self._system(), "その締付トルクは?", self.HISTORY
        )

        self.assertEqual(ans.status, "ok")
        self.assertEqual(ans.citations[0].document_id, "eq-p101")
        self.assertIn("25N・m", ans.text)
        self.assertNotIn("60N・m", ans.text)
        # Retrieval received the carried identifier; the safety gate judged the RAW follow-up.
        self.assertIn("p-101", retrieval_query.casefold())
        self.assertEqual(intent_query, "その締付トルクは?")

    def test_without_history_the_same_followup_answers_the_wrong_equipment_the_bug_u19_closes(self):
        # Documents the "before" behavior: no carried identifier, so the follow-up's generic terms
        # (締付トルク) rank the OTHER equipment's document first and the user gets the wrong torque.
        ans, retrieval_query, intent_query = self._answer_with_history(
            self._system(), "その締付トルクは?", []
        )

        self.assertIsNone(intent_query)
        self.assertEqual(retrieval_query, "その締付トルクは?")
        self.assertEqual(ans.citations[0].document_id, "eq-p203")
        self.assertIn("60N・m", ans.text)
        self.assertNotIn("25N・m", ans.text)

    def test_no_history_is_byte_identical_to_a_direct_answer_call(self):
        # Two identically-built systems, ONE call each (per-tenant cost counters advance per call,
        # so a same-system before/after comparison could never be equal by construction).
        query = "P-101 の点検手順を教えて"

        via_endpoint_logic, retrieval_query, intent_query = self._answer_with_history(
            self._system(), query, []
        )
        direct = self._system().answer(_principal(), query, "manuals")

        self.assertEqual(retrieval_query, query)
        self.assertIsNone(intent_query)
        self.assertEqual(_comparable(via_endpoint_logic), _comparable(direct))

    def test_non_referential_query_with_history_is_byte_identical_too(self):
        query = "P-203 の点検手順を教えて"

        via_endpoint_logic, retrieval_query, intent_query = self._answer_with_history(
            self._system(), query, self.HISTORY
        )
        direct = self._system().answer(_principal(), query, "manuals")

        self.assertEqual(retrieval_query, query)
        self.assertIsNone(intent_query)
        self.assertEqual(_comparable(via_endpoint_logic), _comparable(direct))


class AnswerPathFollowupHighRiskSafetyTest(unittest.TestCase):
    """Proof (b): the dangerous-follow-up scenarios from the chatbot's
    ChatbotL2CoreferenceHighRiskSafetyTest (protected, unmodified), replayed through the ANSWER
    path's history mechanism. Turn 1 is an ordinary query citing an APPROVED but UNRELATED document;
    turn 2 is a short referential follow-up whose RAW text is high-risk while the genuinely on-topic
    document is only PENDING_REVIEW. Correct behavior: block APPROVED_CITATION_MISSING — the carried
    prior-turn terms must neither launder the high-risk classification nor let the unrelated
    approved document satisfy the approved-citation requirement.
    """

    CONTEXT_QUERY = "How often is routine equipment inspection performed?"
    CONTEXT_DOC_ID = "routine-inspection-schedule"
    CONTEXT_DOC_TEXT = (
        "Routine inspection of the equipment is performed every 30 days by the maintenance team."
    )
    # Keyword-stage high-risk ("圧力") and ambiguous-fail-safe high-risk (no listed hazard keyword)
    # variants — the same two shapes the chatbot bypass tests pin.
    FOLLOWUP_QUERY = "その圧力の抜き方を教えて"
    NO_KEYWORD_FOLLOWUP = "その排出弁の開け方を教えて"
    REAL_DOC_ID = "accumulator-pressure-release-pending"
    REAL_DOC_TEXT = "蓄圧器の圧力を抜く際は、手動排出弁をゆっくり開いてから配管を開放してください。"
    HISTORY = [{"question": CONTEXT_QUERY, "cited_document_ids": [CONTEXT_DOC_ID]}]

    def _system(self, *, real_doc_status, real_doc_effective=None) -> ManufacturingSystem:
        mfg_sys = ManufacturingSystem()
        mfg_sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="manuals",
            document_id=self.CONTEXT_DOC_ID,
            text=self.CONTEXT_DOC_TEXT,
            metadata=mfg_meta(
                tenant_id=T,
                document_id=self.CONTEXT_DOC_ID,
                approval_status=ApprovalStatus.APPROVED,
                effective_date="2026-01-01",
            ),
        )
        real_meta_kwargs = {"safety_category": "pressure"}
        if real_doc_effective is not None:
            real_meta_kwargs["effective_date"] = real_doc_effective
        mfg_sys.ingest_manufacturing(
            tenant_id=T,
            collection_id="manuals",
            document_id=self.REAL_DOC_ID,
            text=self.REAL_DOC_TEXT,
            metadata=mfg_meta(
                tenant_id=T,
                document_id=self.REAL_DOC_ID,
                approval_status=real_doc_status,
                **real_meta_kwargs,
            ),
        )
        mfg_sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")
        return mfg_sys

    def _answer_with_history(self, mfg_sys: ManufacturingSystem, query: str, *, thread_intent=True):
        retrieval_query, intent_query = followup_from_history(query, self.HISTORY)
        # thread_intent=False DROPS the raw intent before it reaches the manufacturing chain —
        # simulating a (hypothetical) endpoint that rewrote without threading, for the regression
        # pin proving the threading is load-bearing, not dead code.
        ans = mfg_sys.answer(
            _principal(),
            retrieval_query,
            "manuals",
            intent_query=intent_query if thread_intent else None,
        )
        return ans, retrieval_query, intent_query

    def test_the_followups_do_rewrite_so_these_scenarios_exercise_the_carry_path(self):
        for followup in (self.FOLLOWUP_QUERY, self.NO_KEYWORD_FOLLOWUP):
            retrieval_query, intent_query = followup_from_history(followup, self.HISTORY)
            self.assertNotEqual(retrieval_query, followup)
            self.assertEqual(intent_query, followup)

    def test_dangerous_keyword_followup_blocks_from_the_raw_text(self):
        mfg_sys = self._system(real_doc_status=ApprovalStatus.PENDING_REVIEW)

        ans, _, _ = self._answer_with_history(mfg_sys, self.FOLLOWUP_QUERY)

        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertTrue(ans.high_risk, "classification must bind to the RAW follow-up text")
        self.assertEqual(ans.safety_block_reason, "approved_citation_missing")
        self.assertIsNone(ans.text)
        self.assertEqual(ans.citations, ())

    def test_dangerous_no_keyword_followup_blocks_from_the_raw_text(self):
        # The shape the chatbot's earlier keyword-only guard famously missed: high-risk only via the
        # classifier's ambiguous fail-safe. The answer path must block it identically.
        mfg_sys = self._system(real_doc_status=ApprovalStatus.PENDING_REVIEW)

        ans, _, _ = self._answer_with_history(mfg_sys, self.NO_KEYWORD_FOLLOWUP)

        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertTrue(ans.high_risk)
        self.assertEqual(ans.safety_block_reason, "approved_citation_missing")
        self.assertIsNone(ans.text)
        self.assertEqual(ans.citations, ())

    def test_regression_pin_dropping_the_intent_reproduces_the_bypass(self):
        # Proves the intent_query threading is load-bearing on the answer path: the SAME rewritten
        # query WITHOUT the raw intent flips the block into status="ok" citing the unrelated
        # approved document — the exact corruption chatbot/coreference.py's Finding documents.
        mfg_sys = self._system(real_doc_status=ApprovalStatus.PENDING_REVIEW)

        ans, _, _ = self._answer_with_history(mfg_sys, self.FOLLOWUP_QUERY, thread_intent=False)

        self.assertEqual(ans.status, "ok", "documents the bug the threading prevents")
        self.assertEqual([c.document_id for c in ans.citations], [self.CONTEXT_DOC_ID])

    def test_positive_control_answers_when_the_real_topic_has_an_approved_citation(self):
        # Guards against a degenerate "block everything" outcome (same philosophy as the chatbot
        # test's positive control): with the on-topic document APPROVED+effective the high-risk
        # follow-up must answer, citing the REAL document, never the carried-in unrelated one.
        mfg_sys = self._system(
            real_doc_status=ApprovalStatus.APPROVED, real_doc_effective="2026-01-01"
        )

        ans, _, _ = self._answer_with_history(mfg_sys, self.FOLLOWUP_QUERY)

        self.assertEqual(ans.status, "ok")
        self.assertTrue(ans.high_risk)
        self.assertEqual([c.document_id for c in ans.citations], [self.REAL_DOC_ID])


if __name__ == "__main__":
    unittest.main()
