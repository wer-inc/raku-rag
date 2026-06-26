from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.providers.guardrails import GuardrailVerdict
from tests.helpers import claims, fresh

T = "tenant_a"


class _BlockingGuardrail:
    def check(self, text: str) -> GuardrailVerdict:
        return GuardrailVerdict(action="BLOCK", reason="unsafe_output")


class TestAnswerOutputGuardrail(unittest.TestCase):
    def test_blocked_output_is_not_returned_or_cited(self) -> None:
        sys = fresh()
        sys.answer_service._output_guardrail = _BlockingGuardrail()
        sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="The pump P-12 maintenance interval is ninety days.",
        )
        sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")

        ans = sys.answer(claims(T, "alice"), "what is the pump P-12 maintenance interval?")

        self.assertEqual(ans.status, "temporarily_unavailable")
        self.assertIsNone(ans.text)
        self.assertEqual(ans.citations, ())
        self.assertEqual(ans.used_chunks, ())


if __name__ == "__main__":
    unittest.main()
