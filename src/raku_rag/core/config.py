"""T006 — environment configuration management."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. Performance/limit knobs are configurable (FR-029)."""

    token_signing_secret: str = "dev-secret-change-me"  # HMAC key for signed user tokens
    default_score_threshold: float = 0.10
    default_top_k: int = 5
    default_minimum_evidence_count: int = 1
    rerank_top_n: int = 50
    max_document_bytes: int = 25 * 1024 * 1024
    max_chunks_per_document: int = 10_000
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

    return Settings(
        token_signing_secret=_get("RAKU_TOKEN_SIGNING_SECRET", Settings.token_signing_secret),
        logging_raw_retrieved_context_storage=_get("RAKU_LOG_RAW_RETRIEVED_CONTEXT", "disabled"),
        logging_raw_user_query_storage=_get("RAKU_LOG_RAW_USER_QUERY", "disabled"),
    )
