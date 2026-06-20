"""T017 — error model and API status values."""

from __future__ import annotations

from enum import Enum


class AnswerStatus(str, Enum):
    OK = "ok"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BUDGET_EXCEEDED = "budget_exceeded"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


class RagError(Exception):
    """Base error. Messages must never leak out-of-tenant resource existence (FR-022/021a)."""


class AuthError(RagError):
    """Token/claims invalid, or tenant_id mismatch (FR-025)."""


class TenantIsolationError(RagError):
    """Cross-tenant access attempt (FR-021a). Error must not reveal the other tenant's data."""


class ProviderUnavailable(RagError):
    """A provider (LLM/embedding/vector store) failed unrecoverably; fail-closed (FR-030)."""
