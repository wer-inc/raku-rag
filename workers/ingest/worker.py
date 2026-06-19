"""P0-T03 — Python worker runtime skeleton (entrypoint).

Phase 0 deliverable: the worker boots and wires the local-first foundation (config + deterministic
mock providers + the MVP system) WITHOUT requiring external services. Real SQS consumption, the
ingestion pipeline, and Dagster are Phase 1+ (out of Phase 0 scope).

Run a boot smoke (no services needed):
    PYTHONPATH=src python3 workers/ingest/worker.py --smoke

The worker imports the canonical ``raku_rag`` package (ADR-016: host, do not move).
"""
from __future__ import annotations

import argparse
import os
import sys

# Allow running directly (PYTHONPATH=src) or from repo root.
_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC))

from raku_rag.core.config import settings_from_env  # noqa: E402
from raku_rag.providers.mock import (  # noqa: E402
    MockAuthProvider,
    MockEmbeddingProvider,
    MockGuardrailProvider,
    MockLLMProvider,
    MockRerankProvider,
)


def wire():
    """Construct the Phase-0 local wiring (config + mock providers). Returns a dict for inspection."""
    settings = settings_from_env()
    return {
        "settings": settings,
        "providers": {
            "llm": MockLLMProvider(),
            "embedding": MockEmbeddingProvider(),
            "rerank": MockRerankProvider(),
            "guardrail": MockGuardrailProvider(),
            "auth": MockAuthProvider(secret=settings.token_signing_secret),
        },
    }


def smoke() -> int:
    wiring = wire()
    providers = sorted(wiring["providers"])
    # raw retrieved context storage MUST be off by default (OD-008)
    assert not wiring["settings"].should_store_raw("raw_retrieved_context")
    print(f"worker boot OK — providers={providers} raw_context_storage=disabled")
    return 0


def serve() -> int:  # pragma: no cover - Phase 1 wires the real SQS consume loop
    wire()
    print("worker started (Phase 0 skeleton: no SQS consume loop yet — see P1-T36/T42)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="raku-rag ingest worker (Phase 0 skeleton)")
    ap.add_argument("--smoke", action="store_true", help="boot smoke check, then exit 0")
    args = ap.parse_args(argv)
    return smoke() if args.smoke else serve()


if __name__ == "__main__":
    raise SystemExit(main())
