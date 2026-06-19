"""MVP composition root: wires the stdlib in-memory adapters into a working RAG system.

This is the single place that assembles interfaces + providers + services for US1/US2. The
production entrypoint will assemble the FastAPI/pgvector/Arq adapters behind the same interfaces.
"""
from __future__ import annotations

from raku_rag.core.config import Settings
from raku_rag.core.security.acl import AclPolicy
from raku_rag.core.security.token import TokenVerifier
from raku_rag.domain.models import ACLGrant, Answer, IdentityClaims, QueryProfile, ScopeType, SubjectType
from raku_rag.providers.chunkers import SentenceChunker
from raku_rag.providers.embeddings import HashingEmbeddingProvider
from raku_rag.providers.llms import ExtractiveLLMProvider
from raku_rag.providers.parsers import TextParser
from raku_rag.providers.rerankers import ScoreOrderReranker
from raku_rag.providers.vectorstores import InMemoryVectorStore
from raku_rag.services.answer import AnswerService
from raku_rag.services.cache import CacheService
from raku_rag.services.cost import CostService
from raku_rag.services.deletion import DeletionService
from raku_rag.services.groundedness import GroundednessGate
from raku_rag.services.ingestion import DocumentRegistry, IngestionService
from raku_rag.services.profile import ProfileRegistry
from raku_rag.services.retrieval import RetrievalService


class MvpSystem:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.registry = DocumentRegistry()
        self.store = InMemoryVectorStore()
        self.embedder = HashingEmbeddingProvider(dim=self.settings.embedding_dim)
        self.parser = TextParser()
        self.chunker = SentenceChunker()
        self.reranker = ScoreOrderReranker()
        self.llm = ExtractiveLLMProvider()
        self.acl = AclPolicy([])
        self.cost = CostService()
        self.cache = CacheService()
        self.profiles = ProfileRegistry(
            QueryProfile(
                score_threshold=self.settings.default_score_threshold,
                top_k=self.settings.default_top_k,
                minimum_evidence_count=self.settings.default_minimum_evidence_count,
            )
        )
        self.token_verifier = TokenVerifier(self.settings.token_signing_secret)

        self.retrieval = RetrievalService(self.store, self.embedder, self.acl, self.reranker)
        self.gate = GroundednessGate()
        self.ingestion = IngestionService(
            self.store, self.embedder, self.parser, self.chunker, self.registry
        )
        self.answer_service = AnswerService(
            self.retrieval, self.llm, self.gate, self.cost, self.registry.get
        )
        self.deletion = DeletionService(self.store, self.registry, self.cache)

    # --- convenience admin helpers (admin API analog) ---
    def grant(
        self,
        tenant_id: str,
        scope_type: ScopeType,
        scope_id: str,
        subject_type: SubjectType,
        subject_id: str,
    ) -> None:
        self.acl.add(ACLGrant(tenant_id, scope_type, scope_id, subject_type, subject_id))

    def ingest_text(
        self, *, tenant_id: str, collection_id: str, document_id: str, text: str, source_id: str = "src"
    ):
        return self.ingestion.ingest(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document_id,
            raw=text.encode("utf-8"),
            content_type="text/plain",
        )

    def answer(self, principal: IdentityClaims, query: str, collection_id: str | None = None) -> Answer:
        return self.answer_service.answer(principal, query, self.profiles.resolve(collection_id))

    def search(self, principal: IdentityClaims, query: str, collection_id: str | None = None):
        return self.retrieval.retrieve(principal, query, self.profiles.resolve(collection_id))
