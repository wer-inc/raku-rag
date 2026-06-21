"""T006 — environment configuration management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. Performance/limit knobs are configurable (FR-029)."""

    token_signing_secret: str = "dev-secret-change-me"  # HMAC key for signed user tokens
    default_score_threshold: float = 0.10
    default_top_k: int = 5
    default_minimum_evidence_count: int = 1
    rerank_top_n: int = 20
    max_document_bytes: int = 25 * 1024 * 1024
    max_context_tokens: int = 8_000
    max_context_chunks: int = 8
    max_synchronous_llm_calls: int = 1
    max_chunks_per_document: int = 10_000
    max_chunk_chars: int = 400
    max_concurrent_queries: int = 32
    target_p95_latency_ms: float = 2_000.0
    target_visual_p95_latency_ms: float = 5_000.0
    min_throughput_qps: float = 5.0
    # cost defaults (None = unlimited)
    default_query_budget: float | None = None
    embedding_dim: int = 256
    # Observability defaults (OD-008 / ADR-010 / ADR-015): raw retrieved context and raw user
    # query are NOT stored by default. Allowed: "disabled" | "redacted" | "full_opt_in".
    logging_raw_retrieved_context_storage: str = "disabled"
    logging_raw_user_query_storage: str = "disabled"
    extra: dict = field(default_factory=dict)

    def should_store_raw(self, kind: str) -> bool:
        """Whether raw content of ``kind`` is stored. Default: never (disabled)."""
        mapping = {
            "raw_retrieved_context": self.logging_raw_retrieved_context_storage,
            "raw_user_query": self.logging_raw_user_query_storage,
        }
        return mapping.get(kind, "disabled") == "full_opt_in"


DEFAULT_SETTINGS = Settings()


def settings_from_env(env: dict | None = None) -> Settings:
    """Build Settings from environment (``.env``-style), keeping raw-context storage disabled
    unless an explicit opt-in is configured. Used by P0 local wiring.
    """
    import os

    src = os.environ if env is None else env

    def _get(name: str, default: str) -> str:
        return str(src.get(name, default))

    def _parse(name: str, default, cast: Callable[[str], object]):
        raw = src.get(name)
        if raw in (None, ""):
            return default
        return cast(str(raw))

    return Settings(
        token_signing_secret=_get("RAKU_TOKEN_SIGNING_SECRET", Settings.token_signing_secret),
        default_score_threshold=float(
            _parse("RAKU_DEFAULT_SCORE_THRESHOLD", Settings.default_score_threshold, float)
        ),
        default_top_k=int(_parse("RAKU_DEFAULT_TOP_K", Settings.default_top_k, int)),
        default_minimum_evidence_count=int(
            _parse(
                "RAKU_DEFAULT_MINIMUM_EVIDENCE_COUNT", Settings.default_minimum_evidence_count, int
            )
        ),
        rerank_top_n=int(_parse("RAKU_RERANK_TOP_N", Settings.rerank_top_n, int)),
        max_context_tokens=int(_parse("RAKU_MAX_CONTEXT_TOKENS", Settings.max_context_tokens, int)),
        max_context_chunks=int(_parse("RAKU_MAX_CONTEXT_CHUNKS", Settings.max_context_chunks, int)),
        max_synchronous_llm_calls=int(
            _parse(
                "RAKU_MAX_SYNCHRONOUS_LLM_CALLS",
                Settings.max_synchronous_llm_calls,
                int,
            )
        ),
        max_document_bytes=int(_parse("RAKU_MAX_DOCUMENT_BYTES", Settings.max_document_bytes, int)),
        max_chunks_per_document=int(
            _parse("RAKU_MAX_CHUNKS_PER_DOCUMENT", Settings.max_chunks_per_document, int)
        ),
        max_chunk_chars=int(_parse("RAKU_MAX_CHUNK_CHARS", Settings.max_chunk_chars, int)),
        max_concurrent_queries=int(
            _parse("RAKU_MAX_CONCURRENT_QUERIES", Settings.max_concurrent_queries, int)
        ),
        target_p95_latency_ms=float(
            _parse("RAKU_TARGET_P95_LATENCY_MS", Settings.target_p95_latency_ms, float)
        ),
        target_visual_p95_latency_ms=float(
            _parse(
                "RAKU_TARGET_VISUAL_P95_LATENCY_MS", Settings.target_visual_p95_latency_ms, float
            )
        ),
        min_throughput_qps=float(
            _parse("RAKU_MIN_THROUGHPUT_QPS", Settings.min_throughput_qps, float)
        ),
        logging_raw_retrieved_context_storage=_get("RAKU_LOG_RAW_RETRIEVED_CONTEXT", "disabled"),
        logging_raw_user_query_storage=_get("RAKU_LOG_RAW_USER_QUERY", "disabled"),
    )
