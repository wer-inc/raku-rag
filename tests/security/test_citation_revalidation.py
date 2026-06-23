"""P1-14 / PR-013 — citation channel re-validates current document visibility."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Sequence

from raku_rag.core.errors import AnswerStatus
from raku_rag.domain.models import Chunk, Document, IdentityClaims, QueryProfile, ScoredChunk
from raku_rag.interfaces.base import LLMProvider
from raku_rag.providers.llms import ExtractiveLLMProvider
from raku_rag.services.answer import AnswerService
from raku_rag.services.cost import CostService

T = "tenant_a"


class _FakeRetrieval:
    def __init__(
        self,
        scored: Sequence[ScoredChunk],
        *,
        visible: bool = True,
        visibility_by_chunk: dict[str, bool] | None = None,
    ) -> None:
        self.scored = tuple(scored)
        self.visible = visible
        self.visibility_by_chunk = visibility_by_chunk or {}

    def retrieve(self, *_args, **_kwargs) -> list[ScoredChunk]:
        return list(self.scored)

    def is_visible(self, _principal: IdentityClaims, chunk: Chunk) -> bool:
        return self.visibility_by_chunk.get(chunk.chunk_id, self.visible)


class _FakeGate:
    def __init__(self, evidence: Sequence[ScoredChunk]) -> None:
        self.evidence = tuple(evidence)

    def pre_gate(self, *_args, **_kwargs):
        return SimpleNamespace(passed=True, reason="", evidence=list(self.evidence))

    def post_check(self, *_args, **_kwargs):
        return SimpleNamespace(passed=True, reason="")


class _RecordingLLM(LLMProvider):
    model = "recording-test"

    def __init__(self, text: str) -> None:
        self.text = text
        self.context_chunk_ids: list[str] = []

    def generate(self, _query: str, context: Sequence[Chunk]) -> str:
        self.context_chunk_ids = [chunk.chunk_id for chunk in context]
        return self.text


class CitationRevalidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.principal = IdentityClaims(tenant_id=T, user_id="alice")
        self.profile = QueryProfile(top_k=1, minimum_evidence_count=1)
        self.chunk = Chunk(
            tenant_id=T,
            collection_id="manuals",
            document_id="doc1",
            chunk_id="doc1:0",
            text="Emergency escalation path is the north gate.",
        )
        self.scored = ScoredChunk(chunk=self.chunk, retrieval_score=0.99)

    def _service(
        self,
        *,
        doc: Document | None,
        visible: bool = True,
        evidence: Sequence[ScoredChunk] | None = None,
        llm: LLMProvider | None = None,
    ) -> AnswerService:
        selected = tuple(evidence or (self.scored,))
        return AnswerService(
            _FakeRetrieval(selected, visible=visible),  # type: ignore[arg-type]
            llm or ExtractiveLLMProvider(),
            _FakeGate(selected),  # type: ignore[arg-type]
            CostService(),
            lambda _tenant_id, _document_id: doc,
        )

    def test_tombstoned_document_cannot_be_served_as_a_citation(self) -> None:
        doc = Document(
            tenant_id=T,
            collection_id="manuals",
            document_id="doc1",
            source_id="src",
            tombstone=True,
        )

        ans = self._service(doc=doc).answer(
            self.principal, "What is the emergency escalation path?", self.profile
        )

        self.assertEqual(ans.status, AnswerStatus.INSUFFICIENT_EVIDENCE.value)
        self.assertEqual(ans.citations, ())
        self.assertEqual(ans.used_chunks, ())

    def test_revoked_chunk_is_not_passed_to_generation_context(self) -> None:
        valid = Chunk(
            tenant_id=T,
            collection_id="manuals",
            document_id="doc1",
            chunk_id="doc1:0",
            text="Valid procedure remains available.",
        )
        revoked = Chunk(
            tenant_id=T,
            collection_id="manuals",
            document_id="doc2",
            chunk_id="doc2:0",
            text="Revoked procedure must not reach the model.",
        )
        evidence = (
            ScoredChunk(chunk=valid, retrieval_score=0.99),
            ScoredChunk(chunk=revoked, retrieval_score=0.98),
        )
        docs = {
            "doc1": Document(
                tenant_id=T,
                collection_id="manuals",
                document_id="doc1",
                source_id="src1",
                tombstone=False,
            ),
            "doc2": Document(
                tenant_id=T,
                collection_id="manuals",
                document_id="doc2",
                source_id="src2",
                tombstone=True,
            ),
        }
        llm = _RecordingLLM("Valid procedure remains available.")
        service = AnswerService(
            _FakeRetrieval(evidence),  # type: ignore[arg-type]
            llm,
            _FakeGate(evidence),  # type: ignore[arg-type]
            CostService(),
            lambda _tenant_id, document_id: docs.get(document_id),
        )

        ans = service.answer(
            self.principal,
            "Which procedure remains available?",
            QueryProfile(top_k=2, minimum_evidence_count=1),
        )

        self.assertEqual(ans.status, AnswerStatus.OK.value)
        self.assertEqual(llm.context_chunk_ids, ["doc1:0"])
        self.assertEqual(ans.used_chunks, ("doc1:0",))

    def test_acl_revoked_chunk_cannot_be_served_as_a_citation(self) -> None:
        doc = Document(
            tenant_id=T,
            collection_id="manuals",
            document_id="doc1",
            source_id="src",
            tombstone=False,
        )

        ans = self._service(doc=doc, visible=False).answer(
            self.principal, "What is the emergency escalation path?", self.profile
        )

        self.assertEqual(ans.status, AnswerStatus.INSUFFICIENT_EVIDENCE.value)
        self.assertEqual(ans.citations, ())
        self.assertEqual(ans.used_chunks, ())


if __name__ == "__main__":
    unittest.main()
