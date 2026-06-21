# workers/ingest — Python ingest worker runtime

Per **ADR-016**, the canonical Python package `raku_rag` lives at `src/raku_rag`. This directory is
the worker **runtime host** (entrypoint + SQS consume loop), not a second copy of the package.

## Boot smoke (no services required)
```bash
PYTHONPATH=src python3 workers/ingest/worker.py --smoke
# -> worker boot OK — providers=[...] raw_context_storage=disabled
```

## Queue consumption

```bash
PYTHONPATH=src python3 workers/ingest/worker.py --once
PYTHONPATH=src SQS_QUEUE_URL=http://localhost:4566/000000000000/raku-ingest \
  python3 workers/ingest/worker.py --drain
PYTHONPATH=src SQS_QUEUE_URL=http://localhost:4566/000000000000/raku-ingest \
  SQS_DLQ_URL=http://localhost:4566/000000000000/raku-ingest-dlq \
  python3 workers/ingest/worker.py --serve
```

Set `RAKU_WORKER_BACKEND=postgres` plus `POSTGRES_URL` to use the Postgres-backed
`IngestionRun` / `DocumentProcessingState` projection. Without `SQS_QUEUE_URL`, the process uses an
empty in-memory queue, which keeps boot checks deterministic.

Use `--drain` for local smoke runs and one-off maintenance. ECS services should use `--serve` so the
worker keeps polling instead of exiting when the queue is temporarily empty. On the final receive
(`SQS_MAX_RECEIVE_COUNT`, default 5), `SQS_DLQ_URL` lets the worker project the app run to
`dead_letter` and explicitly copy the original message to the DLQ. Dagster remains the offline
control plane for reindex, backfill, evaluation, and KPI materialization; it is not called from the
request-time answer/search path.
