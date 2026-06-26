"""P1-4 — output guardrail seam (production profile).

The deterministic profile has NO model guardrail; the stdlib ``PromptInjectionGuard`` already runs in the
answer flow as provider-agnostic defense-in-depth. Under the production profile a real Amazon Bedrock
Guardrail is invoked post-generation to screen the answer text; the Bedrock round-trip is the injected
``invoker`` so this is unit-testable offline and credentials/boto3 stay at the edge.

This module provides the seam + the provider + a settings factory. Wiring the actual post-generation
invocation into the answer flow is part of the production live wiring (verify_live, blocked-needs-infra
without Bedrock); the deterministic profile returns ``None`` (no extra guardrail), so Tier-A is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GuardrailVerdict:
    """Outcome of an output-guardrail check. ``action`` is ALLOW or BLOCK; ``reason`` is a code."""

    action: str  # "ALLOW" | "BLOCK"
    reason: str | None = None

    @property
    def blocked(self) -> bool:
        return self.action.upper() == "BLOCK"


# Invoker seam: (text) -> {"action": "ALLOW"|"BLOCK", "reason": str}. Injected for offline testability.
GuardrailInvoker = Callable[..., dict]


class GuardrailProvider:
    """Protocol-ish base: ``check(text) -> GuardrailVerdict``."""

    def check(self, text: str) -> GuardrailVerdict:  # pragma: no cover - interface
        raise NotImplementedError


class BedrockGuardrailProvider(GuardrailProvider):
    """Production output guardrail over Amazon Bedrock Guardrails. FAILS CLOSED: if no invoker is
    configured the check raises (the production profile must not silently skip the guardrail). When the
    invoker errors mid-call the answer flow treats it as BLOCK (safe default), surfaced via ``check``.
    """

    def __init__(self, *, invoker: GuardrailInvoker | None = None) -> None:
        self._invoker = invoker

    def check(self, text: str) -> GuardrailVerdict:
        if self._invoker is None:
            raise RuntimeError(
                "bedrock_guardrail_not_configured: runtime_profile=production requires a Bedrock "
                "Guardrails invoker (no silent skip of the output guardrail)."
            )
        try:
            result = dict(self._invoker(text=text) or {})
        except Exception:
            return GuardrailVerdict(action="BLOCK", reason="guardrail_error")  # safe default
        action = str(result.get("action") or "ALLOW").upper()
        return GuardrailVerdict(action=action, reason=result.get("reason"))


def build_bedrock_guardrail_invoker(
    *,
    guardrail_id: str,
    guardrail_version: str,
    region_name: str = "us-east-1",
    client: object | None = None,
) -> GuardrailInvoker:
    state: dict[str, object | None] = {"client": client}

    def _invoke(*, text: str) -> dict:
        if state["client"] is None:
            import boto3  # type: ignore

            state["client"] = boto3.client("bedrock-runtime", region_name=region_name)
        response = state["client"].apply_guardrail(  # type: ignore[attr-defined]
            guardrailIdentifier=guardrail_id,
            guardrailVersion=guardrail_version,
            source="OUTPUT",
            content=[{"text": {"text": text}}],
        )
        action = str(response.get("action") or "").upper()
        if action == "GUARDRAIL_INTERVENED":
            return {"action": "BLOCK", "reason": "bedrock_guardrail_intervened"}
        return {"action": "ALLOW", "reason": None}

    return _invoke


def guardrail_from_settings(settings, *, invoker: GuardrailInvoker | None = None):
    """Select the output guardrail by runtime profile (P1-4). deterministic -> None (stdlib
    PromptInjectionGuard still runs in the answer flow); production -> BedrockGuardrailProvider."""
    profile = str(getattr(settings, "runtime_profile", "deterministic") or "deterministic")
    profile = profile.strip().lower()
    if profile in {"deterministic", "mvp", "offline", ""}:
        return None
    if profile == "production":
        if invoker is None:
            guardrail_id = str(getattr(settings, "bedrock_guardrail_id", "") or "")
            guardrail_version = str(getattr(settings, "bedrock_guardrail_version", "") or "")
            if guardrail_id and guardrail_version:
                region = str(getattr(settings, "aws_region", "us-east-1") or "us-east-1")
                invoker = build_bedrock_guardrail_invoker(
                    guardrail_id=guardrail_id,
                    guardrail_version=guardrail_version,
                    region_name=region,
                )
        return BedrockGuardrailProvider(invoker=invoker)
    raise ValueError(f"unsupported runtime_profile: {profile!r}")
