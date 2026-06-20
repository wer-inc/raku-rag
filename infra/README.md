# infra — local-first dependency stack (Phase 0)

```bash
docker compose -f infra/docker-compose.yml up -d        # core: postgres+pgvector, minio, localstack
docker compose -f infra/docker-compose.yml --profile observability up -d   # + langfuse trace sink
```

- **postgres** (`pgvector/pgvector:pg16`) — pgvector enabled at first boot via `db/init/01-extensions.sql` (RT3).
- **minio** — S3-compatible object storage (console at :9001).
- **localstack** — SQS; `localstack/init/01-create-queues.sh` creates `raku-ingest` + DLQ on ready.
- **langfuse** (profile `observability`) — optional local trace sink. The app is disabled-safe:
  with `LANGFUSE_ENABLED=false` it runs against a mock sink and never crashes (RT13 default keeps
  raw retrieved context off regardless).
- **redis** (profile `cache`) — only if an adapter needs it.

Phase 0 ships this config; Phase 1 wires the services into the runtime (RLS, ingestion, etc.).

## Tier B bootstrap

The 001 production track starts with the Postgres-only schema/RLS gate:

```bash
bash scripts/gate.sh b
```

This starts only `postgres`, creates a throwaway gate database, applies
`infra/db/migrations/postgres/0001_core_rls.sql`, verifies that an application role scoped with
`app.current_tenant_id` cannot read another tenant's document, runs the down migration, then applies
the up migration again. The SQL lives under `infra/db/migrations/postgres/` so the default sqlite
migration smoke remains Docker-free.
