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
    embedding_provider: str = "hashing"
    embedding_dim: int = 256
    # OpenAI text-embedding-3 API key (empty unless the provider is selected). Read from OPENAI_API_KEY;
    # never logged. Only used when embedding_provider is an openai_text_embedding_3_* variant.
    openai_api_key: str = ""
    # Staging/demo escape hatch: production profile normally upgrades hashing embeddings to a real
    # provider. This explicit opt-in keeps hashing for non-paid staging stacks without weakening prod.
    allow_hashing_embeddings_in_production: bool = False
    aws_region: str = "ap-northeast-1"
    # Google Drive connector OAuth (021-gdrive-oauth). client_id is public (also read by the API to
    # build the consent URL); client_secret is read ONLY by the answer-service for code/refresh
    # exchange and is never sent to the browser or logged. Empty unless the connector is configured.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # KMS CMK for envelope-encrypting per-tenant connector secrets in AWS Secrets Manager (prod).
    secrets_manager_kms_key_id: str = ""
    # P1 production profile: "deterministic" (default — Tier-A fast loop, in-memory/extractive stack)
    # vs "production" (settings-selected real adapters; fails closed when a real adapter is unconfigured).
    runtime_profile: str = "deterministic"
    # Visual/PDF understanding providers. Empty/``deterministic`` keeps the offline stack selected.
    # Production still requires explicit provider settings; runtime_profile alone never upgrades these.
    ocr_provider: str = "deterministic"
    layout_provider: str = "deterministic"
    structured_provider: str = "deterministic"
    vlm_provider: str = "deterministic"
    captioning_provider: str = "deterministic"
    visual_embedding_provider: str = "deterministic"
    vlm_model_id: str = ""
    caption_model_id: str = ""
    textract_region: str = "ap-northeast-1"
    ocr_region: str = ""
    vlm_region: str = ""
    gcp_project_id: str = ""
    gcp_location: str = "asia-northeast1"
    gcp_workload_identity_provider: str = ""
    gcp_workload_identity_sa_email: str = ""
    crop_storage_uri: str = ""
    visual_evidence_promotion: bool = False
    visual_evidence_verifier_quorum: int = 2
    visual_evidence_verifier_providers: tuple[str, ...] = ()
    visual_verifier_allow_same_family_distinct_models: bool = False
    max_inline_ocr_bytes: int = 5_000_000
    max_regions_verified_per_answer: int = 3
    force_deterministic: bool = False
    # Answer-generation LLM override, independent of runtime_profile. "" = use the profile default
    # (deterministic→extractive). "bedrock_claude" = real Bedrock Claude (needs Bedrock model access +
    # IAM). Lets the answer text come from Claude without flipping guardrail/reranker to production.
    llm_provider: str = ""
    bedrock_claude_model_id: str = "jp.anthropic.claude-sonnet-4-5-20250929-v1:0"
    bedrock_guardrail_id: str = ""
    bedrock_guardrail_version: str = ""
    langfuse_enabled: bool = False
    # P1-5 Langfuse self-host edge (host/keys live at the composition edge; the SDK is a `prod` extra).
    # Empty host/keys -> build_langfuse_client returns None -> LangfuseTelemetryExporter is a fail-safe no-op.
    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # Observability defaults (OD-008 / ADR-010 / ADR-015): raw retrieved context and raw user
    # query are NOT stored by default. Allowed: "disabled" | "redacted" | "full_opt_in".
    logging_raw_retrieved_context_storage: str = "disabled"
    logging_raw_user_query_storage: str = "disabled"
    telemetry_export_enabled: bool = False
    pii_redaction_mode: str = "pre_index_redact"
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

    def _bool(name: str, default: bool) -> bool:
        raw = src.get(name)
        if raw in (None, ""):
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
        raw = src.get(name)
        if raw in (None, ""):
            return default
        return tuple(part.strip() for part in str(raw).split(",") if part.strip())

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
        embedding_provider=_get("RAKU_EMBEDDING_PROVIDER", Settings.embedding_provider),
        embedding_dim=int(_parse("RAKU_EMBEDDING_DIM", Settings.embedding_dim, int)),
        openai_api_key=_get("OPENAI_API_KEY", Settings.openai_api_key),
        allow_hashing_embeddings_in_production=_bool(
            "RAKU_ALLOW_HASHING_EMBEDDINGS_IN_PRODUCTION",
            Settings.allow_hashing_embeddings_in_production,
        ),
        aws_region=_get("RAKU_AWS_REGION", _get("AWS_DEFAULT_REGION", Settings.aws_region)),
        google_oauth_client_id=_get("GOOGLE_OAUTH_CLIENT_ID", Settings.google_oauth_client_id),
        google_oauth_client_secret=_get(
            "GOOGLE_OAUTH_CLIENT_SECRET", Settings.google_oauth_client_secret
        ),
        secrets_manager_kms_key_id=_get(
            "AWS_SECRETS_MANAGER_KMS_KEY_ID", Settings.secrets_manager_kms_key_id
        ),
        runtime_profile=_get("RAKU_RUNTIME_PROFILE", Settings.runtime_profile),
        ocr_provider=_get("RAKU_OCR_PROVIDER", Settings.ocr_provider),
        layout_provider=_get("RAKU_LAYOUT_PROVIDER", Settings.layout_provider),
        structured_provider=_get("RAKU_STRUCTURED_PROVIDER", Settings.structured_provider),
        vlm_provider=_get("RAKU_VLM_PROVIDER", Settings.vlm_provider),
        captioning_provider=_get("RAKU_CAPTIONING_PROVIDER", Settings.captioning_provider),
        visual_embedding_provider=_get(
            "RAKU_VISUAL_EMBEDDING_PROVIDER", Settings.visual_embedding_provider
        ),
        vlm_model_id=_get("RAKU_VLM_MODEL_ID", Settings.vlm_model_id),
        caption_model_id=_get("RAKU_CAPTION_MODEL_ID", Settings.caption_model_id),
        textract_region=_get("RAKU_TEXTRACT_REGION", Settings.textract_region),
        ocr_region=_get("RAKU_OCR_REGION", Settings.ocr_region),
        vlm_region=_get("RAKU_VLM_REGION", Settings.vlm_region),
        gcp_project_id=_get("RAKU_GCP_PROJECT_ID", Settings.gcp_project_id),
        gcp_location=_get("RAKU_GCP_LOCATION", Settings.gcp_location),
        gcp_workload_identity_provider=_get(
            "RAKU_GCP_WORKLOAD_IDENTITY_PROVIDER",
            Settings.gcp_workload_identity_provider,
        ),
        gcp_workload_identity_sa_email=_get(
            "RAKU_GCP_WORKLOAD_IDENTITY_SA_EMAIL",
            Settings.gcp_workload_identity_sa_email,
        ),
        crop_storage_uri=_get("RAKU_CROP_STORAGE_URI", Settings.crop_storage_uri),
        visual_evidence_promotion=_bool(
            "RAKU_VISUAL_EVIDENCE_PROMOTION", Settings.visual_evidence_promotion
        ),
        visual_evidence_verifier_quorum=int(
            _parse(
                "RAKU_VISUAL_EVIDENCE_VERIFIER_QUORUM",
                Settings.visual_evidence_verifier_quorum,
                int,
            )
        ),
        visual_evidence_verifier_providers=_csv(
            "RAKU_VISUAL_EVIDENCE_VERIFIERS",
            _csv(
                "RAKU_VISUAL_EVIDENCE_VERIFIER_PROVIDERS",
                Settings.visual_evidence_verifier_providers,
            ),
        ),
        visual_verifier_allow_same_family_distinct_models=_bool(
            "RAKU_VISUAL_VERIFIER_ALLOW_SAME_FAMILY_DISTINCT_MODELS",
            Settings.visual_verifier_allow_same_family_distinct_models,
        ),
        max_inline_ocr_bytes=int(
            _parse("RAKU_MAX_INLINE_OCR_BYTES", Settings.max_inline_ocr_bytes, int)
        ),
        max_regions_verified_per_answer=int(
            _parse(
                "RAKU_MAX_REGIONS_VERIFIED_PER_ANSWER",
                Settings.max_regions_verified_per_answer,
                int,
            )
        ),
        force_deterministic=_bool("RAKU_FORCE_DETERMINISTIC", Settings.force_deterministic),
        llm_provider=_get("RAKU_LLM_PROVIDER", Settings.llm_provider),
        bedrock_claude_model_id=_get(
            "RAKU_BEDROCK_CLAUDE_MODEL_ID", Settings.bedrock_claude_model_id
        ),
        bedrock_guardrail_id=_get("RAKU_BEDROCK_GUARDRAIL_ID", Settings.bedrock_guardrail_id),
        bedrock_guardrail_version=_get(
            "RAKU_BEDROCK_GUARDRAIL_VERSION", Settings.bedrock_guardrail_version
        ),
        langfuse_enabled=_bool("LANGFUSE_ENABLED", Settings.langfuse_enabled),
        langfuse_host=_get("LANGFUSE_HOST", Settings.langfuse_host),
        langfuse_public_key=_get("LANGFUSE_PUBLIC_KEY", Settings.langfuse_public_key),
        langfuse_secret_key=_get("LANGFUSE_SECRET_KEY", Settings.langfuse_secret_key),
        logging_raw_retrieved_context_storage=_get("RAKU_LOG_RAW_RETRIEVED_CONTEXT", "disabled"),
        logging_raw_user_query_storage=_get("RAKU_LOG_RAW_USER_QUERY", "disabled"),
        telemetry_export_enabled=_bool(
            "RAKU_TELEMETRY_EXPORT_ENABLED", Settings.telemetry_export_enabled
        ),
        pii_redaction_mode=_get("RAKU_PII_REDACTION_MODE", Settings.pii_redaction_mode),
    )
