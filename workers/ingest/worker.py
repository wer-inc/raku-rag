"""Python ingest worker runtime entrypoint.

The default smoke path still needs no services. When ``SQS_QUEUE_URL`` is set, ``--once``/``--drain``
consume SQS messages via ``SqsTaskQueue`` and run the 001 ingestion pipeline. Set
``RAKU_WORKER_BACKEND=postgres`` plus ``POSTGRES_URL`` to project IngestionRun /
DocumentProcessingState into Postgres.

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

from raku_rag.app import MvpSystem  # noqa: E402
from raku_rag.core.config import settings_from_env  # noqa: E402
from raku_rag.providers.connectors import FileConnector  # noqa: E402
from raku_rag.providers.mock import (  # noqa: E402
    MockAuthProvider,
    MockEmbeddingProvider,
    MockGuardrailProvider,
    MockLLMProvider,
    MockRerankProvider,
)
from raku_rag.providers.task_queue import InMemoryMessageQueue  # noqa: E402
from raku_rag.workers.ingestion import IngestionRunStore, IngestionWorker  # noqa: E402
from raku_rag.workers.queue.sqs import SqsTaskQueue  # noqa: E402


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


def build_worker_from_env() -> IngestionWorker:
    backend = os.environ.get("RAKU_WORKER_BACKEND", "memory")
    if backend == "postgres":
        from raku_rag.persistence.postgres import PostgresIngestionRunStore
        from raku_rag.production import DEFAULT_DSN, ProductionSystem

        system = ProductionSystem(os.environ.get("POSTGRES_URL", DEFAULT_DSN))
        runs = PostgresIngestionRunStore(system._conn)
    else:
        system = MvpSystem()
        runs = IngestionRunStore()

    queue_url = os.environ.get("SQS_QUEUE_URL")
    queue = SqsTaskQueue(queue_url) if queue_url else InMemoryMessageQueue()
    return IngestionWorker(
        queue=queue,
        connector=FileConnector(),
        ingestion=system.ingestion,
        runs=runs,
    )


def serve(*, once: bool = False, drain: bool = False, max_messages: int = 100) -> int:
    worker = build_worker_from_env()
    if once:
        processed = worker.process_once()
        print(f"worker once complete processed={processed}")
        return 0
    if drain:
        stats = worker.drain(max_messages=max_messages)
        print(
            "worker drain complete "
            f"processed={stats.processed} skipped_duplicates={stats.skipped_duplicates} "
            f"failed={stats.failed} dead_lettered={stats.dead_lettered}"
        )
        return 0
    print("worker booted — use --once or --drain to consume ingestion messages")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="raku-rag ingest worker")
    ap.add_argument("--smoke", action="store_true", help="boot smoke check, then exit 0")
    ap.add_argument("--once", action="store_true", help="process at most one queue message")
    ap.add_argument("--drain", action="store_true", help="process queue messages until empty")
    ap.add_argument("--max-messages", type=int, default=100, help="max messages for --drain")
    args = ap.parse_args(argv)
    if args.smoke:
        return smoke()
    return serve(once=args.once, drain=args.drain, max_messages=args.max_messages)


if __name__ == "__main__":
    raise SystemExit(main())
