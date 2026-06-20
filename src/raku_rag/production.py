"""Production composition root (001 Step 2): the MVP system on Postgres-backed persistence.

``ProductionSystem`` is the analog of ``app.MvpSystem`` but swaps the three persistence seams
(VectorStore / DocumentRegistry / ACL grants) for the Postgres adapters in ``persistence.postgres``.
Everything else — the services (retrieval/answer/deletion/groundedness), the deterministic
``HashingEmbeddingProvider``, parser/chunker/reranker/LLM, ``AclPolicy`` decision logic, ``TokenVerifier``,
``CacheService`` — is reused unchanged. It therefore exposes the exact public surface the security hard
gates exercise, so they run against real Postgres+RLS via adapter parity (see ``tests/helpers.fresh``).
"""
from __future__ import annotations

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings
from raku_rag.core.security.token import TokenVerifier
from raku_rag.domain.models import QueryProfile
from raku_rag.persistence.postgres import (
    PostgresAclPolicy,
    PostgresDocumentRegistry,
    PostgresVectorStore,
    connect,
)
from raku_rag.providers.chunkers import SentenceChunker
from raku_rag.providers.embeddings import HashingEmbeddingProvider
from raku_rag.providers.llms import ExtractiveLLMProvider
from raku_rag.providers.parsers import TextParser
from raku_rag.providers.rerankers import ScoreOrderReranker
from raku_rag.services.answer import AnswerService
from raku_rag.services.cache import CacheService
from raku_rag.services.cost import CostService
from raku_rag.services.deletion import DeletionService
from raku_rag.services.groundedness import GroundednessGate
from raku_rag.services.ingestion import IngestionService
from raku_rag.services.profile import ProfileRegistry
from raku_rag.services.retrieval import RetrievalService

DEFAULT_DSN = "postgresql://raku:raku@127.0.0.1:5432/raku_parity"


class ProductionSystem(MvpSystem):
    """MvpSystem wired onto Postgres (chunks/documents/acl_grants) with RLS.

    Inherits ``grant`` / ``ingest_text`` / ``answer`` / ``search`` from ``MvpSystem`` unchanged — only the
    persistence seams differ. ``reset=True`` is a TEST convenience (clean slate via TRUNCATE on connect).
    """

    def __init__(
        self, dsn: str = DEFAULT_DSN, settings: Settings | None = None, *, reset: bool = False
    ) -> None:
        self.settings = settings or Settings()
        self._conn = connect(dsn, reset=reset)

        # Postgres-backed persistence seams.
        self.registry = PostgresDocumentRegistry(self._conn)
        self.store = PostgresVectorStore(self._conn)
        self.acl = PostgresAclPolicy(self._conn)

        # Reused, unchanged from MvpSystem.
        self.embedder = HashingEmbeddingProvider(dim=self.settings.embedding_dim)
        self.parser = TextParser()
        self.chunker = SentenceChunker()
        self.reranker = ScoreOrderReranker()
        self.llm = ExtractiveLLMProvider()
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

        # Same service wiring as MvpSystem, over the swapped seams.
        self.retrieval = RetrievalService(self.store, self.embedder, self.acl, self.reranker)
        self.gate = GroundednessGate()
        self.ingestion = IngestionService(
            self.store, self.embedder, self.parser, self.chunker, self.registry
        )
        self.answer_service = AnswerService(
            self.retrieval, self.llm, self.gate, self.cost, self.registry.get
        )
        self.deletion = DeletionService(self.store, self.registry, self.cache)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover - best-effort teardown
            pass

    def __del__(self) -> None:  # pragma: no cover - GC-time best-effort
        self.close()
