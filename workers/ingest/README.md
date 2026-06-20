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
```

Set `RAKU_WORKER_BACKEND=postgres` plus `POSTGRES_URL` to use the Postgres-backed
`IngestionRun` / `DocumentProcessingState` projection. Without `SQS_QUEUE_URL`, the process uses an
empty in-memory queue, which keeps boot checks deterministic.
