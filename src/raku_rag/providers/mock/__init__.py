"""P0-T19/T20 — deterministic mock providers for the local-first foundation (ADR-013).

The five Phase-0 mock providers are deterministic and interface-conformant. LLM/Embedding/Rerank
reuse the existing stdlib MVP implementations (already deterministic); Guardrail and Auth are added
here. Every mock advertises a no-train / zero-retention capability so the no-train default is
auditable (RT11/RT12). Real Bedrock/Cohere/Cognito adapters are deferred to later phases.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from raku_rag.core.security.token import TokenVerifier, sign_token
from raku_rag.domain.models import Chunk, IdentityClaims, ScoredChunk
from raku_rag.interfaces.base import EmbeddingProvider, LLMProvider, Reranker
from raku_rag.providers.embeddings import HashingEmbeddingProvider
from raku_rag.providers.llms import ExtractiveLLMProvider
from raku_rag.providers.rerankers import ScoreOrderReranker

# Advertised, auditable provider capability — no external training / zero retention (RT11/RT12).
NO_TRAIN_CAPABILITY = {"no_train": True, "zero_retention": True, "provider": "mock"}


class MockEmbeddingProvider(HashingEmbeddingProvider):
    """Deterministic, stable bag-of-words vectors (same text → identical vector)."""

    capabilities = dict(NO_TRAIN_CAPABILITY)


class MockLLMProvider(ExtractiveLLMProvider):
    """Deterministic extractive answer composed only from authorized context (no external call)."""

    capabilities = dict(NO_TRAIN_CAPABILITY)


class MockRerankProvider(Reranker):
    """Deterministic score-order rerank with an explicit skip-on-failure fallback (FR-030).

    When ``fail`` is set (or the inner rerank raises), returns the unmodified candidate order
    truncated to ``top_n`` so the caller can proceed on the un-reranked results.
    """

    capabilities = dict(NO_TRAIN_CAPABILITY)

    def __init__(self, *, fail: bool = False) -> None:
        self._inner = ScoreOrderReranker()
        self.fail = fail

    def rerank(self, query: str, scored: Sequence[ScoredChunk], top_n: int) -> list[ScoredChunk]:
        if self.fail:
            return list(scored)[:top_n]  # skip fallback: preserve candidate order
        try:
            return self._inner.rerank(query, scored, top_n)
        except Exception:
            return list(scored)[:top_n]


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    reason: str = ""


class MockGuardrailProvider:
    """Defense-in-depth content filter only (ADR-009). It is supplemental and MUST NOT be relied on
    to enforce ACL, tenant isolation, RequiredEvidencePolicy, GroundednessGate, or RiskGate — those
    remain the deterministic primary controls. Deterministic denylist-based allow/block.
    """

    capabilities = dict(NO_TRAIN_CAPABILITY)
    #: deterministic, illustrative denylist (case-insensitive substring match)
    DEFAULT_DENYLIST = ("__blocked__", "ignore previous instructions")

    def __init__(self, denylist: Sequence[str] | None = None) -> None:
        self._deny = tuple((denylist if denylist is not None else self.DEFAULT_DENYLIST))

    def check(self, text: str) -> GuardrailDecision:
        low = text.lower()
        for term in self._deny:
            if term.lower() in low:
                return GuardrailDecision(allowed=False, reason=f"blocked: matched {term!r}")
        return GuardrailDecision(allowed=True)

    # Explicit contract marker: guardrails never widen authorization.
    def bypasses_acl(self) -> bool:  # pragma: no cover - documentation contract
        return False


class MockAuthProvider:
    """Deterministic signed-claim generator + verifier (Cognito mock).

    Uses the same HMAC scheme as the production TokenVerifier so issued tokens are accepted by the
    real verifier and enforce tenant binding (FR-025).
    """

    capabilities = dict(NO_TRAIN_CAPABILITY)

    def __init__(self, secret: str = "dev-secret-change-me") -> None:
        self._secret = secret
        self._verifier = TokenVerifier(secret)

    def issue(
        self,
        tenant_id: str,
        user_id: str,
        *,
        groups: Sequence[str] = (),
        roles: Sequence[str] = (),
    ) -> str:
        claims = IdentityClaims(
            tenant_id=tenant_id, user_id=user_id, groups=tuple(groups), roles=tuple(roles)
        )
        return sign_token(claims, self._secret)

    def verify(self, token: str, *, expected_tenant_id: str) -> IdentityClaims:
        return self._verifier.verify(token, expected_tenant_id=expected_tenant_id)


#: registry used by the conformance test and the local default wiring (P0-T22)
MOCK_PROVIDERS = {
    "llm": MockLLMProvider,
    "embedding": MockEmbeddingProvider,
    "rerank": MockRerankProvider,
    "guardrail": MockGuardrailProvider,
    "auth": MockAuthProvider,
}

__all__ = [
    "MockEmbeddingProvider",
    "MockLLMProvider",
    "MockRerankProvider",
    "MockGuardrailProvider",
    "MockAuthProvider",
    "GuardrailDecision",
    "NO_TRAIN_CAPABILITY",
    "MOCK_PROVIDERS",
]
