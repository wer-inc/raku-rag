"""Embedding provider and dimension wiring contracts."""

from __future__ import annotations

import unittest

from raku_rag.app import MvpSystem
from raku_rag.core.config import Settings, settings_from_env
from raku_rag.providers.embeddings import (
    HashingEmbeddingProvider,
    embedding_dimension,
    embedding_provider_from_settings,
)
from workers.ingest.providers.embeddings.openai_embed3 import OpenAIEmbedding3Provider
from raku_rag.domain.models import Chunk
from raku_rag.persistence.postgres import PostgresVectorStore
from raku_rag.services.ingestion import IngestionService


class TestEmbeddingConfiguration(unittest.TestCase):
    def test_hashing_provider_uses_configured_dimension(self) -> None:
        provider = embedding_provider_from_settings(
            Settings(embedding_provider="hashing", embedding_dim=64)
        )

        self.assertIsInstance(provider, HashingEmbeddingProvider)
        self.assertEqual(embedding_dimension(provider), 64)
        self.assertEqual(len(provider.embed(["pump alarm"])[0]), 64)

    def test_cohere_provider_requires_1024_dimension(self) -> None:
        with self.assertRaises(ValueError):
            embedding_provider_from_settings(
                Settings(embedding_provider="bedrock_cohere_multilingual_v3", embedding_dim=256)
            )

    def test_embedding_env_settings_are_explicit(self) -> None:
        settings = settings_from_env(
            {
                "RAKU_EMBEDDING_PROVIDER": "hashing",
                "RAKU_EMBEDDING_DIM": "128",
                "AWS_DEFAULT_REGION": "us-west-2",
            }
        )

        self.assertEqual(settings.embedding_provider, "hashing")
        self.assertEqual(settings.embedding_dim, 128)
        self.assertEqual(settings.aws_region, "us-west-2")

    def test_production_profile_defaults_to_openai_small_256(self) -> None:
        provider = embedding_provider_from_settings(
            Settings(runtime_profile="production", openai_api_key="sk-test")
        )

        self.assertIsInstance(provider, OpenAIEmbedding3Provider)
        self.assertEqual(provider.model, "text-embedding-3-small")
        self.assertEqual(provider.dimensions, 256)

    def test_production_profile_can_explicitly_allow_hashing_for_staging(self) -> None:
        provider = embedding_provider_from_settings(
            Settings(
                runtime_profile="production",
                embedding_provider="hashing",
                embedding_dim=256,
                allow_hashing_embeddings_in_production=True,
            )
        )

        self.assertIsInstance(provider, HashingEmbeddingProvider)
        self.assertEqual(embedding_dimension(provider), 256)

    def test_production_profile_rejects_non_256_openai_default(self) -> None:
        with self.assertRaises(ValueError):
            embedding_provider_from_settings(
                Settings(
                    runtime_profile="production",
                    embedding_provider="hashing",
                    embedding_dim=1024,
                    openai_api_key="sk-test",
                )
            )

    def test_same_raw_document_reindexes_when_embedding_dimension_changes(self) -> None:
        sys = MvpSystem(Settings(embedding_provider="hashing", embedding_dim=32))
        text = "Pump P-12 vibration threshold is 4.2 mm/s."
        sys.ingest_text(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_1",
            text=text,
        )
        first = sys.registry.get("tenant_a", "doc_1")
        self.assertEqual(first.version, 1)
        self.assertEqual(first.metadata["embedding_dimension"], 32)

        sys.embedder = HashingEmbeddingProvider(dim=64)
        sys.ingestion = IngestionService(
            sys.store,
            sys.embedder,
            sys.parser,
            sys.chunker,
            sys.registry,
            sys.metrics,
            sys.tracer,
            pii_redaction_mode=sys.settings.pii_redaction_mode,
        )
        sys.ingest_text(
            tenant_id="tenant_a",
            collection_id="manuals",
            document_id="doc_1",
            text=text,
        )

        second = sys.registry.get("tenant_a", "doc_1")
        self.assertEqual(second.version, 2)
        self.assertEqual(second.metadata["embedding_dimension"], 64)

    def test_postgres_vector_store_rejects_wrong_embedding_dimension_before_sql(self) -> None:
        store = PostgresVectorStore(object(), embedding_dim=2)

        with self.assertRaises(ValueError):
            store.upsert(
                [
                    (
                        Chunk(
                            tenant_id="tenant_a",
                            collection_id="manuals",
                            document_id="doc_1",
                            chunk_id="doc_1:0",
                            text="hello",
                        ),
                        [1.0],
                    )
                ]
            )


if __name__ == "__main__":
    unittest.main()
