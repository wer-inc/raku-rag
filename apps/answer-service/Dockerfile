# syntax=docker/dockerfile:1
# Python answer-service — the internal HTTP boundary (/internal/*) over the Postgres-backed
# ProductionSystem (retrieval / ACL / ranking / manufacturing safety overlay). Build with context = repo
# ROOT (needs src/ = the raku_rag package, workers/ = provider_policy, and apps/answer-service):
#   docker build -f apps/answer-service/Dockerfile -t raku-rag-answer .
#
# Production serves only (no --reset-demo-db / --seed; the reset guard refuses non-local DBs anyway).
# Apply schema migrations and seed via one-off tasks, not here.
FROM python:3.12-slim AS runtime

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

# psycopg drives the Postgres adapters; boto3 is needed only when RAKU_RUNTIME_PROFILE=production wires
# the real Bedrock providers; python-docx/openpyxl back the manufacturing metadata path.
RUN pip install --no-cache-dir \
      "psycopg[binary]>=3" boto3 python-docx==1.1.2 openpyxl==3.1.5

COPY pyproject.toml ./
COPY src/ ./src/
COPY workers/ ./workers/
COPY apps/answer-service/ ./apps/answer-service/

EXPOSE 8088
# Serve the internal boundary. Migrations/seed are separate one-off tasks.
CMD ["python", "apps/answer-service/server.py", "--port", "8088"]
