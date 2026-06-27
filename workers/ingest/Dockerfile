# Python ingestion worker (parser/OCR/embedding host). Build with context = repo ROOT:
#   docker build -f workers/ingest/Dockerfile -t raku-rag-worker .
# It needs both src/ (the raku_rag package) and workers/ (the worker runtime host).
ARG PYTHON_BASE_IMAGE=public.ecr.aws/docker/library/python:3.12-slim
FROM ${PYTHON_BASE_IMAGE} AS runtime

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

# psycopg drives the Postgres adapters (ProductionSystem connects on boot); boto3 is needed when
# RAKU_RUNTIME_PROFILE=production wires the real Bedrock providers; python-docx/openpyxl back the
# 002 manufacturing parsers (pyproject [manufacturing] extra). CSV/text use the stdlib.
RUN pip install --no-cache-dir \
      "psycopg[binary]>=3" boto3 python-docx==1.1.2 openpyxl==3.1.5

COPY pyproject.toml ./
COPY src/ ./src/
COPY workers/ ./workers/

# Boots the worker and wires the mock providers; --smoke needs no external services.
ENTRYPOINT ["python", "-m", "workers.ingest.worker"]
CMD ["--smoke"]
