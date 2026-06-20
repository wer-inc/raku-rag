"""Parser provider adapters gated by ProviderPolicy.

Adapters are intentionally SDK-light. Production code can inject an Azure/Google/Textract client,
while tests use tiny fakes to prove policy enforcement happens before raw bytes leave the worker.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

from workers.ingest.provider_policy import (
    ProviderCapability,
    ProviderPolicy,
    ProviderPolicyDecision,
    ProviderPolicyEnforcer,
    ProviderPolicyViolation,
    ProviderRequest,
)

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
TEXT = "text/plain"
MARKDOWN = "text/markdown"
HTML = "text/html"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV = "text/csv"

_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{16})\b")


class ParserClient(Protocol):
    def parse(self, raw: bytes, content_type: str) -> str | Mapping[str, object]: ...


@dataclass(frozen=True)
class ParserProviderAuditEvent:
    event_type: str
    provider_policy_id: str
    requested_provider: str
    effective_provider: str
    allowed: bool
    reasons: tuple[str, ...] = ()
    fallback_provider: str = ""
    raw_content_sent: bool = False
    redacted_before: Mapping[str, object] = field(default_factory=dict)
    redacted_after: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "provider_policy_id": self.provider_policy_id,
            "requested_provider": self.requested_provider,
            "effective_provider": self.effective_provider,
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "fallback_provider": self.fallback_provider,
            "raw_content_sent": self.raw_content_sent,
            "redacted_before": dict(self.redacted_before),
            "redacted_after": dict(self.redacted_after),
        }


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    provider: str
    parser_version: str
    content_type: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ParserRouteResult:
    parsed: ParsedDocument
    requested_provider: str
    effective_provider: str
    decision: ProviderPolicyDecision
    fallback_used: bool
    audit_events: tuple[ParserProviderAuditEvent, ...]


class ParserProviderAdapter:
    provider: str = ""
    provider_family: str = ""
    parser_version: str = ""
    supported_content_types: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        client: ParserClient | None = None,
        region: str = "",
        zero_retention: bool = True,
        no_train: bool = True,
        customer_managed: bool = False,
    ) -> None:
        self.client = client
        self.region = region
        self.zero_retention = zero_retention
        self.no_train = no_train
        self.customer_managed = customer_managed

    def supports(self, content_type: str) -> bool:
        return not self.supported_content_types or content_type in self.supported_content_types

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider=self.provider,
            provider_family=self.provider_family,
            region=self.region,
            zero_retention=self.zero_retention,
            no_train=self.no_train,
            customer_managed=self.customer_managed,
        )

    def parse(self, raw: bytes, content_type: str) -> ParsedDocument:
        if not self.supports(content_type):
            raise ValueError(f"{self.provider} does not support {content_type}")
        text = self._parse_text(raw, content_type)
        return ParsedDocument(
            text=_normalize(text),
            provider=self.provider,
            parser_version=self.parser_version,
            content_type=content_type,
            metadata={"provider_family": self.provider_family, "region": self.region},
        )

    def _parse_text(self, raw: bytes, content_type: str) -> str:
        if not self.client:
            raise RuntimeError(f"{self.provider} parser client is not configured")
        result = self.client.parse(raw, content_type)
        if isinstance(result, Mapping):
            text = result.get("text") or result.get("content") or result.get("normalized_text")
            return str(text or "")
        return str(result)


class CustomerManagedParserAdapter(ParserProviderAdapter):
    provider = "customer_managed"
    provider_family = "customer_managed"
    parser_version = "customer-managed-parser-v1"
    supported_content_types = (TEXT, MARKDOWN, HTML, CSV)

    def __init__(self, *, client: ParserClient | None = None) -> None:
        super().__init__(
            client=client,
            region="customer",
            zero_retention=True,
            no_train=True,
            customer_managed=True,
        )

    def _parse_text(self, raw: bytes, content_type: str) -> str:
        if self.client:
            return super()._parse_text(raw, content_type)
        return raw.decode("utf-8", errors="replace")


class OssParserAdapter(CustomerManagedParserAdapter):
    provider = "tesseract"
    provider_family = "oss"
    parser_version = "oss-tesseract-parser-v1"
    supported_content_types = (TEXT, MARKDOWN, HTML, PNG, JPEG)

    def __init__(self, *, client: ParserClient | None = None) -> None:
        ParserProviderAdapter.__init__(
            self,
            client=client,
            region="local",
            zero_retention=True,
            no_train=True,
            customer_managed=False,
        )


class TextractParserAdapter(ParserProviderAdapter):
    provider = "aws_textract"
    provider_family = "aws"
    parser_version = "aws-textract-parser-v1"
    supported_content_types = (PDF, PNG, JPEG)

    def __init__(
        self,
        *,
        client: ParserClient | None = None,
        region: str = "us-east-1",
        zero_retention: bool = True,
        no_train: bool = True,
    ) -> None:
        super().__init__(
            client=client,
            region=region,
            zero_retention=zero_retention,
            no_train=no_train,
        )


class AzureDocumentIntelligenceParserAdapter(ParserProviderAdapter):
    provider = "azure_document_intelligence"
    provider_family = "azure"
    parser_version = "azure-document-intelligence-layout-v1"
    supported_content_types = (PDF, PNG, JPEG, DOCX)

    def __init__(
        self,
        *,
        client: ParserClient | None = None,
        region: str = "eastus",
        zero_retention: bool = False,
        no_train: bool = False,
    ) -> None:
        super().__init__(
            client=client,
            region=region,
            zero_retention=zero_retention,
            no_train=no_train,
        )


class GoogleDocumentAIParserAdapter(ParserProviderAdapter):
    provider = "google_document_ai"
    provider_family = "google"
    parser_version = "google-document-ai-parser-v1"
    supported_content_types = (PDF, PNG, JPEG, DOCX)

    def __init__(
        self,
        *,
        client: ParserClient | None = None,
        region: str = "us",
        zero_retention: bool = False,
        no_train: bool = False,
    ) -> None:
        super().__init__(
            client=client,
            region=region,
            zero_retention=zero_retention,
            no_train=no_train,
        )


class ProviderPolicyParserRouter:
    def __init__(
        self,
        adapters: Sequence[ParserProviderAdapter] | None = None,
        *,
        enforcer: ProviderPolicyEnforcer | None = None,
    ) -> None:
        default_adapters: tuple[ParserProviderAdapter, ...] = (
            CustomerManagedParserAdapter(),
            OssParserAdapter(),
            TextractParserAdapter(),
            AzureDocumentIntelligenceParserAdapter(),
            GoogleDocumentAIParserAdapter(),
        )
        self.adapters = {adapter.provider: adapter for adapter in (adapters or default_adapters)}
        self.enforcer = enforcer or ProviderPolicyEnforcer()

    def parse(
        self,
        raw: bytes,
        content_type: str,
        *,
        requested_provider: str,
        policy: ProviderPolicy,
    ) -> ParserRouteResult:
        decision = self._evaluate(policy, requested_provider)
        audit_events: list[ParserProviderAuditEvent] = [
            self._audit_event(policy, requested_provider, requested_provider, decision)
        ]
        if decision.allowed:
            parsed = self._parse_with(requested_provider, raw, content_type)
            audit_events.append(
                self._audit_event(
                    policy,
                    requested_provider,
                    requested_provider,
                    decision,
                    raw_content_sent=True,
                    event_type="parser_provider_selected",
                )
            )
            return ParserRouteResult(
                parsed=parsed,
                requested_provider=requested_provider,
                effective_provider=requested_provider,
                decision=decision,
                fallback_used=False,
                audit_events=tuple(audit_events),
            )

        for fallback_provider in self._fallback_candidates(decision):
            if fallback_provider == requested_provider or fallback_provider not in self.adapters:
                continue
            fallback_decision = self._evaluate(policy, fallback_provider)
            audit_events.append(
                self._audit_event(
                    policy,
                    requested_provider,
                    fallback_provider,
                    fallback_decision,
                    event_type="parser_provider_fallback_evaluated",
                )
            )
            if fallback_decision.allowed:
                parsed = self._parse_with(fallback_provider, raw, content_type)
                audit_events.append(
                    self._audit_event(
                        policy,
                        requested_provider,
                        fallback_provider,
                        fallback_decision,
                        raw_content_sent=True,
                        event_type="parser_provider_fallback_selected",
                    )
                )
                return ParserRouteResult(
                    parsed=parsed,
                    requested_provider=requested_provider,
                    effective_provider=fallback_provider,
                    decision=decision,
                    fallback_used=True,
                    audit_events=tuple(audit_events),
                )

        raise ProviderPolicyViolation(decision)

    def _evaluate(self, policy: ProviderPolicy, provider: str) -> ProviderPolicyDecision:
        adapter = self.adapters.get(provider)
        capability = (
            adapter.capability()
            if adapter
            else ProviderCapability(provider=provider, provider_family="unknown")
        )
        return self.enforcer.evaluate(
            policy,
            ProviderRequest(operation="parse", provider=provider, capability=capability),
        )

    def _parse_with(self, provider: str, raw: bytes, content_type: str) -> ParsedDocument:
        adapter = self.adapters[provider]
        return adapter.parse(raw, content_type)

    def _fallback_candidates(self, decision: ProviderPolicyDecision) -> tuple[str, ...]:
        candidates = [decision.fallback_provider, "customer_managed", "tesseract"]
        return tuple(dict.fromkeys(provider for provider in candidates if provider))

    def _audit_event(
        self,
        policy: ProviderPolicy,
        requested_provider: str,
        effective_provider: str,
        decision: ProviderPolicyDecision,
        *,
        raw_content_sent: bool = False,
        event_type: str = "parser_provider_policy_evaluated",
    ) -> ParserProviderAuditEvent:
        return ParserProviderAuditEvent(
            event_type=event_type,
            provider_policy_id=policy.provider_policy_id,
            requested_provider=requested_provider,
            effective_provider=effective_provider,
            allowed=decision.allowed,
            reasons=tuple(_redact(reason) for reason in decision.reasons),
            fallback_provider=decision.fallback_provider,
            raw_content_sent=raw_content_sent,
            redacted_before={"provider": requested_provider, "parser_mode": policy.parser_mode},
            redacted_after={"provider": effective_provider, "allowed": decision.allowed},
        )


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _redact(text: str) -> str:
    return _SECRET.sub("[REDACTED:secret]", _EMAIL.sub("[REDACTED:email]", text))


__all__ = [
    "ParsedDocument",
    "ParserProviderAdapter",
    "ParserProviderAuditEvent",
    "ParserRouteResult",
    "ProviderPolicyParserRouter",
    "CustomerManagedParserAdapter",
    "OssParserAdapter",
    "TextractParserAdapter",
    "AzureDocumentIntelligenceParserAdapter",
    "GoogleDocumentAIParserAdapter",
]
