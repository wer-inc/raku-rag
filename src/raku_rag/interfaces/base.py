"""Abstract interfaces for the 13 pluggable components (FR-031)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Protocol, Sequence

from raku_rag.domain.models import Chunk, ScoredChunk

# A pre-filter predicate: given a candidate chunk, may it be retrieved for this principal?
# Used by VectorStore.search to enforce ACL/tenant/tombstone BEFORE scoring (FR-022, pre-filter).
VisibilityPredicate = Callable[[Chunk], bool]

Vector = Sequence[float]


class Connector(ABC):
    """Ingestion source (upload / object storage / future SaaS)."""

    @abstractmethod
    def fetch(self, ref: str) -> bytes: ...


class Parser(ABC):
    @abstractmethod
    def supports(self, content_type: str) -> bool: ...

    @abstractmethod
    def parse(self, raw: bytes, content_type: str) -> str:
        """Return normalized text (NFKC etc.)."""


class Chunker(ABC):
    @abstractmethod
    def chunk(self, text: str) -> list[tuple[str, tuple[str, ...], int, tuple[int, int]]]:
        """Return list of (chunk_text, heading_path, position, (orig_start, orig_end))."""


class EmbeddingProvider(ABC):
    model_version: str

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[Vector]: ...


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, chunks: Sequence[tuple[Chunk, Vector]]) -> None: ...

    @abstractmethod
    def search(
        self,
        tenant_id: str,
        query_vec: Vector,
        *,
        visible: VisibilityPredicate,
        top_k: int,
    ) -> list[ScoredChunk]:
        """MUST apply tenant_id, tombstone exclusion and ``visible`` as a PRE-filter."""

    @abstractmethod
    def set_tombstone(self, tenant_id: str, document_id: str, value: bool) -> int: ...

    @abstractmethod
    def purge(self, tenant_id: str, document_id: str) -> int: ...


class Reranker(ABC):
    @abstractmethod
    def rerank(self, query: str, scored: Sequence[ScoredChunk], top_n: int) -> list[ScoredChunk]: ...


class LLMProvider(ABC):
    model: str

    @abstractmethod
    def generate(self, query: str, context: Sequence[Chunk]) -> str:
        """Generate grounded answer text from authorized context chunks only (FR-040 analog)."""


class TaskQueue(ABC):
    @abstractmethod
    def enqueue(self, fn: Callable[..., object], *args, **kwargs) -> object: ...


# --- US6 (out of MVP scope): declared for interface completeness, not implemented here ---


class OcrEngine(Protocol):
    def extract(self, image: bytes) -> object: ...


class LayoutExtractor(Protocol):
    def extract(self, image: bytes) -> object: ...


class CaptioningProvider(Protocol):
    """optional enrichment; search aid only, never primary evidence (FR-048)."""

    def caption(self, image: bytes) -> object: ...


class VisualEmbeddingProvider(Protocol):
    def embed(self, regions: Sequence[bytes]) -> list[Vector]: ...


class VLMProvider(Protocol):
    def generate(self, query: str, *, visual_regions: Sequence[object]) -> str: ...
