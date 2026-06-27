"""Visual provider adapters gated by ProviderPolicy.

The wrappers in this module sit directly in front of OCR/layout/caption/VLM providers. They evaluate
tenant policy before forwarding image bytes, S3 refs, or visual context to an external provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from raku_rag.domain.models import LayoutRegion
from raku_rag.interfaces.visual import AsyncSubmitRequest, DocumentAnalysis, JobHandle
from workers.ingest.provider_policy import (
    ProviderCapability,
    ProviderPolicy,
    ProviderPolicyDecision,
    ProviderPolicyEnforcer,
    ProviderPolicyViolation,
    ProviderRequest,
    capability_for,
)


@dataclass(frozen=True)
class VisualProviderAuditEvent:
    event_type: str
    provider_policy_id: str
    operation: str
    requested_provider: str
    effective_provider: str
    allowed: bool
    tenant_id: str = ""
    collection_id: str = ""
    document_id: str = ""
    reasons: tuple[str, ...] = ()
    fallback_provider: str = ""
    raw_content_sent: bool = False
    redacted_before: Mapping[str, object] = field(default_factory=dict)
    redacted_after: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "provider_policy_id": self.provider_policy_id,
            "operation": self.operation,
            "requested_provider": self.requested_provider,
            "effective_provider": self.effective_provider,
            "allowed": self.allowed,
            "tenant_id": self.tenant_id,
            "collection_id": self.collection_id,
            "document_id": self.document_id,
            "reasons": list(self.reasons),
            "fallback_provider": self.fallback_provider,
            "raw_content_sent": self.raw_content_sent,
            "redacted_before": dict(self.redacted_before),
            "redacted_after": dict(self.redacted_after),
        }


class StaticProviderPolicyResolver:
    def __init__(self, policy: ProviderPolicy) -> None:
        self.policy = policy

    def get(
        self,
        tenant_id: str,
        collection_id: str = "",
        provider_policy_id: str = "default",
    ) -> ProviderPolicy:
        if self.policy.tenant_id and self.policy.tenant_id != tenant_id:
            return ProviderPolicy(tenant_id=tenant_id, provider_policy_id=provider_policy_id)
        return self.policy


class _ProviderPolicyRouter:
    def __init__(
        self,
        inner: object,
        *,
        operation: str,
        provider_id: str = "",
        policy_resolver: object | None = None,
        enforcer: ProviderPolicyEnforcer | None = None,
        capability: ProviderCapability | None = None,
    ) -> None:
        self.inner = inner
        self.operation = operation
        self.provider_id = provider_id or str(getattr(inner, "provider_id", "") or "")
        self.policy_resolver = policy_resolver
        self.enforcer = enforcer or ProviderPolicyEnforcer()
        self._capability = capability
        self.audit_events: list[VisualProviderAuditEvent] = []

    def _check(
        self,
        *,
        tenant_id: str = "",
        collection_id: str = "",
        document_id: str = "",
        provider_policy_id: str = "default",
    ) -> ProviderPolicyDecision:
        policy = self._policy(
            tenant_id=tenant_id,
            collection_id=collection_id,
            provider_policy_id=provider_policy_id,
        )
        request = ProviderRequest(
            operation=self.operation,
            provider=self.provider_id,
            capability=self._effective_capability(),
        )
        decision = self.enforcer.evaluate(policy, request)
        self.audit_events.append(
            self._audit_event(
                policy,
                decision,
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
            )
        )
        if not decision.allowed:
            raise ProviderPolicyViolation(decision)
        self.audit_events.append(
            self._audit_event(
                policy,
                decision,
                tenant_id=tenant_id,
                collection_id=collection_id,
                document_id=document_id,
                event_type="visual_provider_selected",
                raw_content_sent=True,
            )
        )
        return decision

    def _policy(
        self,
        *,
        tenant_id: str,
        collection_id: str,
        provider_policy_id: str,
    ) -> ProviderPolicy:
        resolver = self.policy_resolver
        if resolver is None:
            return ProviderPolicy(tenant_id=tenant_id, provider_policy_id=provider_policy_id)
        if hasattr(resolver, "get"):
            return resolver.get(tenant_id, collection_id, provider_policy_id)  # type: ignore[attr-defined]
        if callable(resolver):
            return resolver(tenant_id, collection_id, provider_policy_id)
        return ProviderPolicy(tenant_id=tenant_id, provider_policy_id=provider_policy_id)

    def _effective_capability(self) -> ProviderCapability:
        if self._capability is not None:
            return self._capability
        override: dict[str, object] = {}
        for attr in ("region", "provider_family", "zero_retention", "no_train", "customer_managed"):
            if hasattr(self.inner, attr):
                override[attr] = getattr(self.inner, attr)
        return capability_for(self.provider_id, override or None)

    def _audit_event(
        self,
        policy: ProviderPolicy,
        decision: ProviderPolicyDecision,
        *,
        tenant_id: str,
        collection_id: str,
        document_id: str,
        event_type: str = "visual_provider_policy_evaluated",
        raw_content_sent: bool = False,
    ) -> VisualProviderAuditEvent:
        return VisualProviderAuditEvent(
            event_type=event_type,
            provider_policy_id=policy.provider_policy_id,
            operation=self.operation,
            requested_provider=self.provider_id,
            effective_provider=decision.effective_provider or self.provider_id,
            allowed=decision.allowed,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            reasons=decision.reasons,
            fallback_provider=decision.fallback_provider,
            raw_content_sent=raw_content_sent,
            redacted_before={"provider": self.provider_id, "operation": self.operation},
            redacted_after={
                "provider": decision.effective_provider or self.provider_id,
                "allowed": decision.allowed,
            },
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


class OcrPolicyRouter(_ProviderPolicyRouter):
    def __init__(self, inner: object, **kwargs: Any) -> None:
        super().__init__(inner, operation="ocr", **kwargs)

    def extract(self, image: bytes, *args: Any, **kwargs: Any):
        self._check(
            tenant_id=str(kwargs.get("tenant_id") or ""),
            collection_id=str(kwargs.get("collection_id") or ""),
            document_id=str(kwargs.get("document_id") or ""),
            provider_policy_id=str(kwargs.get("provider_policy_id") or "default"),
        )
        return self.inner.extract(image, *args, **kwargs)  # type: ignore[attr-defined]


class LayoutPolicyRouter(_ProviderPolicyRouter):
    def __init__(self, inner: object, **kwargs: Any) -> None:
        super().__init__(inner, operation="layout", **kwargs)

    def extract(self, image: bytes, *args: Any, **kwargs: Any):
        self._check(
            tenant_id=str(kwargs.get("tenant_id") or ""),
            collection_id=str(kwargs.get("collection_id") or ""),
            document_id=str(kwargs.get("document_id") or ""),
            provider_policy_id=str(kwargs.get("provider_policy_id") or "default"),
        )
        return self.inner.extract(image, *args, **kwargs)  # type: ignore[attr-defined]


class CaptionPolicyRouter(_ProviderPolicyRouter):
    def __init__(self, inner: object, **kwargs: Any) -> None:
        super().__init__(inner, operation="caption", **kwargs)

    def caption(self, image: bytes, *args: Any, **kwargs: Any):
        self._check(
            tenant_id=str(kwargs.get("tenant_id") or ""),
            collection_id=str(kwargs.get("collection_id") or ""),
            document_id=str(kwargs.get("document_id") or ""),
            provider_policy_id=str(kwargs.get("provider_policy_id") or "default"),
        )
        return self.inner.caption(image, *args, **kwargs)  # type: ignore[attr-defined]


class VlmPolicyRouter(_ProviderPolicyRouter):
    def __init__(self, inner: object, **kwargs: Any) -> None:
        super().__init__(inner, operation="vlm", **kwargs)

    def generate(
        self,
        query: str,
        *,
        visual_regions: Sequence[LayoutRegion],
        tenant_id: str = "",
        collection_id: str = "",
        document_id: str = "",
        provider_policy_id: str = "default",
    ) -> str:
        self._check(
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            provider_policy_id=provider_policy_id,
        )
        return self.inner.generate(query, visual_regions=visual_regions)  # type: ignore[attr-defined]


class VisualEmbeddingPolicyRouter(_ProviderPolicyRouter):
    def __init__(self, inner: object, **kwargs: Any) -> None:
        super().__init__(inner, operation="visual_embedding", **kwargs)

    def embed(
        self,
        regions: Sequence[bytes],
        *,
        tenant_id: str = "",
        collection_id: str = "",
        document_id: str = "",
        provider_policy_id: str = "default",
    ):
        self._check(
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            provider_policy_id=provider_policy_id,
        )
        return self.inner.embed(regions)  # type: ignore[attr-defined]


class AsyncDocumentAnalyzerPolicyRouter(_ProviderPolicyRouter):
    def __init__(self, inner: object, **kwargs: Any) -> None:
        super().__init__(inner, operation="structured", **kwargs)

    def submit(self, request: AsyncSubmitRequest) -> JobHandle:
        self._check(
            tenant_id=request.context.tenant_id,
            collection_id=request.context.collection_id,
            document_id=request.context.document_id,
        )
        return self.inner.submit(request)  # type: ignore[attr-defined]

    def poll(self, handle: JobHandle) -> DocumentAnalysis:
        return self.inner.poll(handle)  # type: ignore[attr-defined]


__all__ = [
    "AsyncDocumentAnalyzerPolicyRouter",
    "CaptionPolicyRouter",
    "LayoutPolicyRouter",
    "OcrPolicyRouter",
    "StaticProviderPolicyResolver",
    "VisualProviderAuditEvent",
    "VisualEmbeddingPolicyRouter",
    "VlmPolicyRouter",
]
