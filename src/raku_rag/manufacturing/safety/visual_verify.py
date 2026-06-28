"""Visual evidence promotion verifiers.

Visual citations can satisfy the manufacturing high-risk approved/effective rule only after an
answer-time verifier stack passes. The deterministic OCR subset verifier is mandatory and never
counts toward the pixel-reading VLM quorum.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol, Sequence

from raku_rag.core.config import Settings
from raku_rag.core.text import content_terms
from raku_rag.domain.models import LayoutRegion
from raku_rag.providers.connectors import S3Connector


@dataclass(frozen=True)
class VerifierVerdict:
    verifier_id: str
    passed: bool
    reason_code: str
    confidence: float = 0.0
    provider_family: str = ""
    model_id: str = ""
    verifier_kind: str = "vlm"

    def to_mapping(self) -> dict:
        return {
            "verifier_id": self.verifier_id,
            "verifier_kind": self.verifier_kind,
            "provider_family": self.provider_family,
            "model_id": self.model_id,
            "passed": self.passed,
            "reason_code": self.reason_code,
            "confidence": self.confidence,
        }


class VisualEvidenceVerifier(Protocol):
    verifier_id: str
    provider_family: str
    model_id: str

    def verify(self, assertion: str, region: LayoutRegion) -> VerifierVerdict:
        """Return a reference-only pass/fail verdict for ``assertion`` against ``region``."""


_IDENTIFIER = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9._/-]*\b")


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").lower().split())


def _identifier_anchors(text: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in _IDENTIFIER.finditer(text or "")
        if any(ch.isdigit() for ch in match.group(0))
    }


class LexicalOcrSubsetVerifier:
    verifier_id = "lexical_ocr_subset"
    provider_family = "deterministic"
    model_id = "ocr-subset-v1"

    def verify(self, assertion: str, region: LayoutRegion) -> VerifierVerdict:
        asserted = _normalize(assertion)
        ocr = _normalize(region.ocr_text)
        if not asserted:
            return self._verdict(False, "assertion_empty")
        if not ocr:
            return self._verdict(False, "ocr_empty")
        if asserted in ocr:
            return self._verdict(True, "substring_match", confidence=1.0)

        assertion_terms = content_terms(assertion)
        ocr_terms = content_terms(region.ocr_text)
        if not assertion_terms:
            return self._verdict(False, "assertion_terms_empty")
        if not assertion_terms.issubset(ocr_terms):
            return self._verdict(False, "ocr_subset_missing_terms")

        anchors = _identifier_anchors(assertion)
        ocr_normalized = _normalize(region.ocr_text)
        if anchors and not all(anchor in ocr_normalized for anchor in anchors):
            return self._verdict(False, "identifier_anchor_missing")
        return self._verdict(True, "term_subset_match", confidence=0.95)

    def _verdict(
        self, passed: bool, reason_code: str, *, confidence: float = 0.0
    ) -> VerifierVerdict:
        return VerifierVerdict(
            verifier_id=self.verifier_id,
            verifier_kind="lexical",
            provider_family=self.provider_family,
            model_id=self.model_id,
            passed=passed,
            reason_code=reason_code,
            confidence=confidence,
        )


@dataclass(frozen=True)
class StaticVisualEvidenceVerifier:
    """Test/deterministic injected verifier; real pixel verifiers live behind this protocol seam."""

    verifier_id: str
    provider_family: str
    model_id: str
    passed: bool = True
    reason_code: str = "match"
    confidence: float = 1.0

    def verify(self, assertion: str, region: LayoutRegion) -> VerifierVerdict:
        return VerifierVerdict(
            verifier_id=self.verifier_id,
            verifier_kind="vlm",
            provider_family=self.provider_family,
            model_id=self.model_id,
            passed=self.passed,
            reason_code=self.reason_code,
            confidence=self.confidence,
        )


@dataclass
class BedrockVisualEvidenceVerifier:
    """AWS Bedrock vision verifier used only when explicitly enabled by settings."""

    model_id: str
    region: str = "ap-northeast-1"
    verifier_id: str = ""
    provider_family: str = "aws"
    connector: object | None = None
    invoker: object | None = None
    max_tokens: int = 128

    def __post_init__(self) -> None:
        if not self.verifier_id:
            self.verifier_id = f"bedrock_visual:{self.model_id}"

    def verify(self, assertion: str, region: LayoutRegion) -> VerifierVerdict:
        crop_uri = str(region.crop_uri or "")
        if not crop_uri.startswith("s3://"):
            return self._verdict(False, "real_crop_required")
        connector = self.connector or S3Connector()
        try:
            raw = connector.fetch(crop_uri)  # type: ignore[attr-defined]
        except Exception:
            return self._verdict(False, "crop_fetch_failed")
        invoker = self.invoker
        if invoker is None:
            from raku_rag.providers.aws_visual import build_bedrock_vision_invoker

            invoker = build_bedrock_vision_invoker(region_name=self.region)
        prompt = (
            "You are verifying a manufacturing visual citation. Return only JSON with keys "
            "passed, reason_code, confidence. passed must be true only when the assertion is "
            "directly supported by the visible image region and OCR text. Do not infer hidden state.\n\n"
            f"Assertion: {assertion}\n"
            f"OCR text: {region.ocr_text}\n"
        )
        try:
            response = invoker(  # type: ignore[misc]
                model_id=self.model_id,
                prompt=prompt,
                max_tokens=self.max_tokens,
                image=raw,
                media_type=str(region.metadata.get("crop_content_type") or "image/png"),
            )
        except Exception:
            return self._verdict(False, "verifier_error")
        payload = _parse_verifier_json(str(response or ""))
        passed = bool(payload.get("passed"))
        reason_code = str(payload.get("reason_code") or ("match" if passed else "no_match"))
        confidence = _bounded_confidence(payload.get("confidence"), default=1.0 if passed else 0.0)
        return self._verdict(passed, reason_code, confidence=confidence)

    def _verdict(
        self, passed: bool, reason_code: str, *, confidence: float = 0.0
    ) -> VerifierVerdict:
        return VerifierVerdict(
            verifier_id=self.verifier_id,
            verifier_kind="vlm",
            provider_family=self.provider_family,
            model_id=self.model_id,
            passed=passed,
            reason_code=reason_code,
            confidence=confidence,
        )


def visual_verifiers_from_settings(settings: Settings) -> tuple[VisualEvidenceVerifier, ...]:
    verifiers: list[VisualEvidenceVerifier] = []
    for raw_entry in settings.visual_evidence_verifier_providers:
        entry = raw_entry.strip()
        if not entry:
            continue
        family, sep, model = entry.partition(":")
        if family.lower() != "bedrock":
            continue
        model_id = model if sep else (settings.vlm_model_id or settings.bedrock_claude_model_id)
        if not model_id:
            continue
        verifiers.append(
            BedrockVisualEvidenceVerifier(
                model_id=model_id,
                region=settings.vlm_region or settings.aws_region,
            )
        )
    return tuple(verifiers)


def verify_visual_primary_evidence(
    *,
    assertion: str,
    region: LayoutRegion,
    verifiers: Sequence[VisualEvidenceVerifier],
    settings: Settings,
) -> tuple[bool, tuple[VerifierVerdict, ...]]:
    """Fail-closed promotion decision for one visual citation.

    Passing requires:
    - visual promotion flag enabled,
    - OCR subset verifier pass,
    - real crop URI present,
    - at least ``visual_evidence_verifier_quorum`` VLM verifier passes,
    - distinct provider families by default.
    """

    verdicts: list[VerifierVerdict] = []
    if not settings.visual_evidence_promotion:
        return False, (
            VerifierVerdict(
                verifier_id="visual_promotion",
                verifier_kind="policy",
                passed=False,
                reason_code="promotion_disabled",
            ),
        )

    lexical = LexicalOcrSubsetVerifier().verify(assertion, region)
    verdicts.append(lexical)
    if not lexical.passed:
        return False, tuple(verdicts)

    if not str(region.crop_uri or "").startswith("s3://"):
        verdicts.append(
            VerifierVerdict(
                verifier_id="crop_resolver",
                verifier_kind="policy",
                passed=False,
                reason_code="real_crop_required",
            )
        )
        return False, tuple(verdicts)

    quorum = max(1, int(settings.visual_evidence_verifier_quorum))
    vlm_verdicts: list[VerifierVerdict] = []
    seen_models: set[tuple[str, str]] = set()
    for verifier in verifiers:
        try:
            verdict = verifier.verify(assertion, region)
        except Exception:
            verdict = VerifierVerdict(
                verifier_id=str(getattr(verifier, "verifier_id", "unknown")),
                verifier_kind="vlm",
                provider_family=str(getattr(verifier, "provider_family", "")),
                model_id=str(getattr(verifier, "model_id", "")),
                passed=False,
                reason_code="verifier_error",
            )
        if not verdict.provider_family:
            verdict = _with_provider(
                verdict, provider_family=getattr(verifier, "provider_family", "")
            )
        if not verdict.model_id:
            verdict = _with_provider(verdict, model_id=getattr(verifier, "model_id", ""))
        key = (verdict.provider_family, verdict.model_id)
        if key in seen_models:
            verdicts.append(
                VerifierVerdict(
                    verifier_id=verdict.verifier_id,
                    verifier_kind="policy",
                    provider_family=verdict.provider_family,
                    model_id=verdict.model_id,
                    passed=False,
                    reason_code="duplicate_verifier_model",
                )
            )
            continue
        seen_models.add(key)
        vlm_verdicts.append(verdict)
        verdicts.append(verdict)

    passed_vlm = [v for v in vlm_verdicts if v.passed]
    if len(passed_vlm) < quorum:
        verdicts.append(
            VerifierVerdict(
                verifier_id="visual_verifier_quorum",
                verifier_kind="policy",
                passed=False,
                reason_code="verifier_quorum_not_met",
                confidence=float(len(passed_vlm)),
            )
        )
        return False, tuple(verdicts)

    families = {v.provider_family or v.verifier_id for v in passed_vlm}
    if not settings.visual_verifier_allow_same_family_distinct_models and len(families) < quorum:
        verdicts.append(
            VerifierVerdict(
                verifier_id="visual_verifier_quorum",
                verifier_kind="policy",
                passed=False,
                reason_code="distinct_provider_quorum_not_met",
                confidence=float(len(families)),
            )
        )
        return False, tuple(verdicts)

    if any(not verdict.passed for verdict in vlm_verdicts):
        return False, tuple(verdicts)
    return True, tuple(verdicts)


def _with_provider(
    verdict: VerifierVerdict, *, provider_family: object = None, model_id: object = None
) -> VerifierVerdict:
    return VerifierVerdict(
        verifier_id=verdict.verifier_id,
        verifier_kind=verdict.verifier_kind,
        provider_family=verdict.provider_family or str(provider_family or ""),
        model_id=verdict.model_id or str(model_id or ""),
        passed=verdict.passed,
        reason_code=verdict.reason_code,
        confidence=verdict.confidence,
    )


def _parse_verifier_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        payload = json.loads(text[start : end + 1])
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _bounded_confidence(value: object, *, default: float) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


__all__ = [
    "BedrockVisualEvidenceVerifier",
    "LexicalOcrSubsetVerifier",
    "StaticVisualEvidenceVerifier",
    "VerifierVerdict",
    "VisualEvidenceVerifier",
    "verify_visual_primary_evidence",
    "visual_verifiers_from_settings",
]
