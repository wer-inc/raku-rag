"""Provider policy enforcement for ingest/runtime provider selection.

The worker must fail closed before sending content to a parser/OCR/LLM/embedding/rerank provider.
This module is intentionally stdlib-only so queue workers can enforce policy even in smoke/local
tests without cloud SDKs installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

Operation = str


@dataclass(frozen=True)
class ProviderCapability:
    provider: str
    provider_family: str
    region: str = ""
    zero_retention: bool = False
    no_train: bool = False
    customer_managed: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ProviderCapability":
        return cls(
            provider=str(value.get("provider") or ""),
            provider_family=str(value.get("provider_family") or value.get("family") or ""),
            region=str(value.get("region") or ""),
            zero_retention=bool(value.get("zero_retention") or False),
            no_train=bool(value.get("no_train") or False),
            customer_managed=bool(value.get("customer_managed") or False),
        )


@dataclass(frozen=True)
class ProviderPolicy:
    provider_policy_id: str = "default"
    tenant_id: str = ""
    parser_mode: str = "aws_only"
    allowed_parser_providers: tuple[str, ...] = ("aws_textract", "tesseract", "customer_managed")
    allowed_ocr_providers: tuple[str, ...] = ("aws_textract", "tesseract", "customer_managed")
    allowed_layout_providers: tuple[str, ...] = ("aws_textract", "tesseract", "customer_managed")
    allowed_structured_providers: tuple[str, ...] = ("aws_textract", "customer_managed")
    allowed_llm_providers: tuple[str, ...] = ("bedrock", "customer_managed")
    allowed_embedding_providers: tuple[str, ...] = ("bedrock", "customer_managed")
    allowed_visual_embedding_providers: tuple[str, ...] = ("bedrock", "customer_managed")
    allowed_vlm_providers: tuple[str, ...] = ("bedrock", "customer_managed")
    allowed_caption_providers: tuple[str, ...] = ("bedrock", "customer_managed")
    allowed_rerank_providers: tuple[str, ...] = ("bedrock", "customer_managed")
    allowed_regions: tuple[str, ...] = ()
    data_residency_requirement: str = "single_region"
    cross_cloud_processing_allowed: bool = False
    zero_retention_required: bool = True
    no_train_required: bool = True
    customer_opt_in_required: bool = True
    customer_opt_in_status: str = "pending"
    opt_in_status_by_family: Mapping[str, str] = field(default_factory=dict)
    fallback_policy: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ProviderPolicy":
        def tuple_field(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
            raw = value.get(name)
            if isinstance(raw, (list, tuple)):
                return tuple(str(item) for item in raw)
            return default

        regions = value.get("allowed_regions")
        provider_regions = value.get("provider_regions")
        allowed_regions: tuple[str, ...]
        if isinstance(regions, (list, tuple)):
            allowed_regions = tuple(str(item) for item in regions)
        elif isinstance(provider_regions, Mapping):
            allowed_regions = tuple(str(item) for item in provider_regions.values() if item)
        else:
            allowed_regions = ()

        fallback_policy_raw = value.get("fallback_policy")
        fallback_policy = fallback_policy_raw if isinstance(fallback_policy_raw, Mapping) else {}

        return cls(
            provider_policy_id=str(value.get("provider_policy_id") or "default"),
            tenant_id=str(value.get("tenant_id") or ""),
            parser_mode=str(value.get("parser_mode") or "aws_only"),
            allowed_parser_providers=tuple_field(
                "allowed_parser_providers", cls.allowed_parser_providers
            ),
            allowed_ocr_providers=tuple_field("allowed_ocr_providers", cls.allowed_ocr_providers),
            allowed_layout_providers=tuple_field(
                "allowed_layout_providers", cls.allowed_layout_providers
            ),
            allowed_structured_providers=tuple_field(
                "allowed_structured_providers", cls.allowed_structured_providers
            ),
            allowed_llm_providers=tuple_field("allowed_llm_providers", cls.allowed_llm_providers),
            allowed_embedding_providers=tuple_field(
                "allowed_embedding_providers", cls.allowed_embedding_providers
            ),
            allowed_visual_embedding_providers=tuple_field(
                "allowed_visual_embedding_providers",
                cls.allowed_visual_embedding_providers,
            ),
            allowed_vlm_providers=tuple_field("allowed_vlm_providers", cls.allowed_vlm_providers),
            allowed_caption_providers=tuple_field(
                "allowed_caption_providers", cls.allowed_caption_providers
            ),
            allowed_rerank_providers=tuple_field(
                "allowed_rerank_providers", cls.allowed_rerank_providers
            ),
            allowed_regions=allowed_regions,
            data_residency_requirement=str(
                value.get("data_residency_requirement") or "single_region"
            ),
            cross_cloud_processing_allowed=bool(
                value.get("cross_cloud_processing_allowed") or False
            ),
            zero_retention_required=bool(value.get("zero_retention_required", True)),
            no_train_required=bool(value.get("no_train_required", True)),
            customer_opt_in_required=bool(value.get("customer_opt_in_required", True)),
            customer_opt_in_status=str(value.get("customer_opt_in_status") or "pending"),
            opt_in_status_by_family=(
                {
                    str(key): str(status)
                    for key, status in dict(value.get("opt_in_status_by_family") or {}).items()
                }
                if isinstance(value.get("opt_in_status_by_family"), Mapping)
                else {}
            ),
            fallback_policy=fallback_policy,
        )


@dataclass(frozen=True)
class ProviderRequest:
    operation: Operation
    provider: str
    capability: ProviderCapability


@dataclass(frozen=True)
class ProviderPolicyDecision:
    allowed: bool
    reasons: tuple[str, ...]
    required_opt_in: bool = False
    effective_provider: str = ""
    fallback_provider: str = ""

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "required_opt_in": self.required_opt_in,
            "effective_provider": self.effective_provider,
            "fallback_provider": self.fallback_provider,
        }


class ProviderPolicyViolation(RuntimeError):
    def __init__(self, decision: ProviderPolicyDecision) -> None:
        super().__init__("; ".join(decision.reasons))
        self.decision = decision


class ProviderPolicyEnforcer:
    _operation_allowlist_field = {
        "parse": "allowed_parser_providers",
        "ocr": "allowed_ocr_providers",
        "layout": "allowed_layout_providers",
        "structured": "allowed_structured_providers",
        "llm": "allowed_llm_providers",
        "embed": "allowed_embedding_providers",
        "embedding": "allowed_embedding_providers",
        "visual_embedding": "allowed_visual_embedding_providers",
        "vlm": "allowed_vlm_providers",
        "caption": "allowed_caption_providers",
        "rerank": "allowed_rerank_providers",
    }

    def evaluate(self, policy: ProviderPolicy, request: ProviderRequest) -> ProviderPolicyDecision:
        reasons: list[str] = []
        operation = request.operation
        provider = request.provider
        capability = request.capability

        allowlist_field = self._operation_allowlist_field.get(operation)
        if not allowlist_field:
            reasons.append(f"unsupported provider operation: {operation}")
        else:
            allowlist = getattr(policy, allowlist_field)
            if provider not in allowlist:
                reasons.append(f"{provider} is not allowed for {operation}")

        if operation in {"parse", "ocr", "layout", "structured"}:
            if policy.parser_mode == "aws_only" and capability.provider_family not in {
                "aws",
                "oss",
                "customer_managed",
            }:
                reasons.append("aws_only parser policy forbids external parser/OCR providers")
            if provider == "azure_document_intelligence" and "azure" not in policy.parser_mode:
                reasons.append("Azure Document Intelligence requires explicit parser_mode opt-in")
            if (
                provider in {"google_document_ai", "google_docai"}
                and "google" not in policy.parser_mode
            ):
                reasons.append("Google Document AI requires explicit parser_mode opt-in")

        if (
            capability.provider_family not in {"aws", "oss", "customer_managed"}
            and not capability.customer_managed
            and not policy.cross_cloud_processing_allowed
        ):
            reasons.append("cross-cloud processing is disabled")

        if (
            policy.allowed_regions
            and capability.region
            and capability.region not in policy.allowed_regions
        ):
            reasons.append(f"{capability.region} is outside allowed provider regions")

        if policy.zero_retention_required and not capability.zero_retention:
            reasons.append("provider lacks required zero-retention capability")

        if policy.no_train_required and not capability.no_train:
            reasons.append("provider lacks required no-train capability")

        if (
            policy.customer_opt_in_required
            and not capability.customer_managed
            and self._opt_in_status(policy, capability.provider_family) != "granted"
        ):
            reasons.append("customer opt-in is required before this provider can process content")

        fallback_provider = self._fallback_provider(policy, operation)
        return ProviderPolicyDecision(
            allowed=not reasons,
            reasons=tuple(reasons),
            required_opt_in=policy.customer_opt_in_required,
            effective_provider=provider,
            fallback_provider="" if not reasons else fallback_provider,
        )

    def assert_allowed(self, policy: ProviderPolicy, request: ProviderRequest) -> None:
        decision = self.evaluate(policy, request)
        if not decision.allowed:
            raise ProviderPolicyViolation(decision)

    def _fallback_provider(self, policy: ProviderPolicy, operation: Operation) -> str:
        raw = policy.fallback_policy.get(operation)
        if isinstance(raw, str):
            return raw
        if isinstance(raw, Mapping):
            provider = raw.get("provider")
            if provider:
                return str(provider)
        if operation in {"parse", "ocr"}:
            return (
                "aws_textract"
                if "aws_textract" in policy.allowed_parser_providers
                else "customer_managed"
            )
        if operation in {"layout", "structured"}:
            return (
                "aws_textract"
                if "aws_textract" in getattr(policy, f"allowed_{operation}_providers")
                else "customer_managed"
            )
        if operation in {
            "embed",
            "embedding",
            "visual_embedding",
            "rerank",
            "llm",
            "vlm",
            "caption",
        }:
            return "bedrock"
        return "customer_managed"

    def _opt_in_status(self, policy: ProviderPolicy, provider_family: str) -> str:
        if provider_family in policy.opt_in_status_by_family:
            return str(policy.opt_in_status_by_family[provider_family])
        return policy.customer_opt_in_status


DEFAULT_PROVIDER_CAPABILITIES: dict[str, ProviderCapability] = {
    "aws_textract": ProviderCapability(
        provider="aws_textract",
        provider_family="aws",
        region="ap-northeast-1",
        zero_retention=True,
        no_train=True,
    ),
    "bedrock": ProviderCapability(
        provider="bedrock",
        provider_family="aws",
        region="ap-northeast-1",
        zero_retention=True,
        no_train=True,
    ),
    "tesseract": ProviderCapability(
        provider="tesseract",
        provider_family="oss",
        region="local",
        zero_retention=True,
        no_train=True,
    ),
    "customer_managed": ProviderCapability(
        provider="customer_managed",
        provider_family="customer_managed",
        region="customer",
        zero_retention=True,
        no_train=True,
        customer_managed=True,
    ),
    "azure_document_intelligence": ProviderCapability(
        provider="azure_document_intelligence",
        provider_family="azure",
        region="japaneast",
        zero_retention=False,
        no_train=False,
    ),
    "google_document_ai": ProviderCapability(
        provider="google_document_ai",
        provider_family="google",
        region="asia-northeast1",
        zero_retention=False,
        no_train=False,
    ),
    "google_docai": ProviderCapability(
        provider="google_docai",
        provider_family="google",
        region="asia-northeast1",
        zero_retention=False,
        no_train=False,
    ),
    "google_gemini": ProviderCapability(
        provider="google_gemini",
        provider_family="google",
        region="asia-northeast1",
        zero_retention=False,
        no_train=False,
    ),
    "vertex_gemini": ProviderCapability(
        provider="vertex_gemini",
        provider_family="google",
        region="asia-northeast1",
        zero_retention=False,
        no_train=False,
    ),
    "vertex_embeddings": ProviderCapability(
        provider="vertex_embeddings",
        provider_family="google",
        region="asia-northeast1",
        zero_retention=False,
        no_train=False,
    ),
}


def capability_for(
    provider: str, override: Mapping[str, object] | None = None
) -> ProviderCapability:
    base = DEFAULT_PROVIDER_CAPABILITIES.get(provider)
    if override:
        data = {
            "provider": provider,
            "provider_family": base.provider_family if base else "",
            "region": base.region if base else "",
            "zero_retention": base.zero_retention if base else False,
            "no_train": base.no_train if base else False,
            "customer_managed": base.customer_managed if base else False,
            **override,
        }
        return ProviderCapability.from_mapping(data)
    if base:
        return base
    return ProviderCapability(provider=provider, provider_family="unknown")
