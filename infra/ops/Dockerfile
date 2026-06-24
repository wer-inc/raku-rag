# syntax=docker/dockerfile:1
# One-off ops runner for the deployed stack: applies Postgres schema migrations (psql + the SQL files)
# and seeds the curated demo KB (stdlib Python -> answer-service /internal/ingest). Run as an ECS
# RunTask inside the VPC (Aurora is private-isolated and the answer-service is internal-only), NOT a
# long-running service. Build with context = repo ROOT:
#   docker build -f infra/ops/Dockerfile -t raku-rag-ops .
# Invoked one command at a time by scripts/aws/migrate-seed.sh.
FROM python:3.12-slim AS runtime

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client bash ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /repo
# pg-migrate.sh reads infra/db/migrations/postgres/*.sql; demo_seed.{sh,py} + demo_docs.json live under scripts/.
COPY scripts/ ./scripts/
COPY infra/db/ ./infra/db/

# Default to a no-op help banner; the ECS task overrides command to run migrate then seed.
CMD ["bash", "-lc", "echo 'raku-rag ops runner: override command to run scripts/pg-migrate.sh up && scripts/demo/demo_seed.sh'"]
