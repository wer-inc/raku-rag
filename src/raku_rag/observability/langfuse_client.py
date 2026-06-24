"""P1-5 (live edge) — build a Langfuse trace client for the self-hosted sink.

This is the *composition edge* that the deterministic Tier-A stack never imports: the ``langfuse``
SDK is a ``prod`` optional dependency, imported lazily here so ``import raku_rag`` stays stdlib-only.
``build_langfuse_client`` turns Settings (host + public/secret keys) into the keyword-only
``(kind, name, payload) -> None`` callable that :class:`LangfuseTelemetryExporter` injects — emitting
one Langfuse trace per sanitized telemetry event. Every failure mode (SDK absent, keys missing, host
unreachable, client raises) degrades to ``None`` / no-op so telemetry can never take down the answer
path. The payload reaching this client has already been sanitized by the exporter (PII redaction +
identity hashing); we do not log it ourselves.

Live verification (a real trace appearing in the Langfuse UI) requires a reachable self-hosted
Langfuse — boot it with ``docker compose --profile observability up`` and set LANGFUSE_HOST /
LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY. It cannot run in the stdlib gate.
"""

from __future__ import annotations

import atexit
from typing import Callable, Optional

LangfuseClient = Callable[..., None]


def build_langfuse_client(settings) -> Optional[LangfuseClient]:
    """Return a ``(kind, name, payload)`` trace callable, or ``None`` when Langfuse is not wired.

    None is returned (and the exporter stays a no-op) when: langfuse is disabled, host/keys are
    missing, or the ``langfuse`` SDK is not installed. Never raises.
    """

    if not getattr(settings, "langfuse_enabled", False):
        return None

    host = (getattr(settings, "langfuse_host", "") or "").strip()
    public_key = (getattr(settings, "langfuse_public_key", "") or "").strip()
    secret_key = (getattr(settings, "langfuse_secret_key", "") or "").strip()
    if not (host and public_key and secret_key):
        # Enabled but unconfigured -> fail safe to no-op rather than crash the production boot.
        return None

    try:
        from langfuse import Langfuse  # lazy: `prod` extra, kept off the Tier-A import path
    except Exception:
        return None

    try:
        client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    except Exception:
        return None

    # Long-running services rely on the SDK's background flush; a short-lived process (the verify
    # script) needs an explicit flush at exit so the trace actually ships before the process dies.
    atexit.register(_safe_shutdown, client)

    def emit(*, kind: str, name: str, payload) -> None:
        # One trace per telemetry event. Payload is pre-sanitized by the exporter.
        client.trace(
            name=f"{kind}.{name}",
            input=payload,
            metadata={"raku.kind": kind, "raku.name": name},
        )

    return emit


def _safe_shutdown(client) -> None:
    try:
        client.flush()
        client.shutdown()
    except Exception:
        return
