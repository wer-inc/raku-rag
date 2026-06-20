# Manufacturing PoC UI

Stdlib-only local demo for the 002 manufacturing vertical slice.

```bash
PYTHONPATH=src python3 poc-ui/server.py --smoke
PYTHONPATH=src python3 poc-ui/server.py
```

Open http://127.0.0.1:8765.

The demo seeds an in-memory `ManufacturingSystem` with approved, obsolete, draft, quality, ledger,
and trouble-case documents. It exercises answer, search, safety blocking, trouble-case retrieval,
draft generation, KPI, telemetry, governance, audit, and the reused 001 ACL/groundedness path.
