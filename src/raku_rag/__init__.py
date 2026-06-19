"""raku-rag: Generic RAG Platform (MVP core).

MVP scope (Phase 1+2, US1+US2): tenancy, ACL deny-by-default pre-filter, ingestion,
search, answer, citation, groundedness, deletion non-reappearance. stdlib-only so the
security hard-gate tests run without external services. Production adapters (FastAPI,
pgvector, Arq, real LLM/embedding providers) plug in behind ``interfaces``.
"""

__version__ = "0.1.0"
