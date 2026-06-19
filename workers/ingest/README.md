# workers/ingest — Python worker runtime (Phase 0 skeleton)

Per **ADR-016**, the canonical Python package `raku_rag` lives at `src/raku_rag`. This directory is
the worker **runtime host** (entrypoint + future SQS consume loop), not a second copy of the package.

## Boot smoke (no services required)
```bash
PYTHONPATH=src python3 workers/ingest/worker.py --smoke
# -> worker boot OK — providers=[...] raw_context_storage=disabled
```

Phase 1 (P1-T36/T42) adds the LocalStack SQS consume loop and the ingestion pipeline. Phase 0 only
proves the worker boots and wires the deterministic mock providers + config.
