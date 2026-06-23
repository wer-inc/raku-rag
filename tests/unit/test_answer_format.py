import unittest
from types import SimpleNamespace

from raku_rag.domain.models import Answer, Citation
from raku_rag.services.answer_format import (
    ANSWER_TEMPLATE_VERSION,
    answer_format_metadata,
)


class TestAnswerFormat(unittest.TestCase):
    def test_grounded_answer_sections_include_answer_and_evidence(self) -> None:
        answer = Answer(
            status="ok",
            text="The pump must be locked out before maintenance.",
            citations=(
                Citation(
                    kind="text",
                    document_id="doc_1",
                    source_id="manual.pdf",
                    version=3,
                    chunk_id="doc_1:0",
                    retrieval_score=0.9,
                ),
            ),
        )

        formatted = answer_format_metadata(answer)
        sections = {section["id"]: section for section in formatted["display_sections"]}

        self.assertEqual(formatted["answer_template_version"], ANSWER_TEMPLATE_VERSION)
        self.assertEqual(sections["status"]["text"], "ok")
        self.assertEqual(sections["answer"]["text"], answer.text)
        self.assertEqual(sections["evidence"]["items"][0]["document_id"], "doc_1")

    def test_safety_section_is_added_for_manufacturing_answer(self) -> None:
        answer = SimpleNamespace(
            status="insufficient_evidence",
            text=None,
            citations=(),
            high_risk=True,
            safety_block_reason="approved_citation_missing",
            obsolete_warning=False,
            requires_onsite_confirmation=True,
            notice="Confirm with a qualified supervisor before work.",
        )

        sections = {
            section["id"]: section for section in answer_format_metadata(answer)["display_sections"]
        }

        self.assertEqual(
            sections["safety"]["fields"]["safety_block_reason"], "approved_citation_missing"
        )
        self.assertTrue(sections["safety"]["fields"]["requires_onsite_confirmation"])

    def test_insufficient_answer_still_has_status_section(self) -> None:
        answer = Answer(status="insufficient_evidence")

        sections = answer_format_metadata(answer)["display_sections"]

        self.assertEqual(
            sections, [{"id": "status", "title": "Status", "text": "insufficient_evidence"}]
        )


if __name__ == "__main__":
    unittest.main()
