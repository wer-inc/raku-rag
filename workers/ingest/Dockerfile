# syntax=docker/dockerfile:1
# Python ingestion worker (parser/OCR/embedding host). Build with context = repo ROOT:
#   docker build -f workers/ingest/Dockerfile -t raku-rag-worker .
# It needs both src/ (the raku_rag package) and workers/ (the worker runtime host).
FROM python:3.12-slim AS runtime

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

# 002 manufacturing parsers (pyproject [manufacturing] extra); CSV/text use the stdlib.
RUN pip install --no-cache-dir python-docx==1.1.2 openpyxl==3.1.5

COPY pyproject.toml ./
COPY src/ ./src/
COPY workers/ ./workers/

# Boots the worker and wires the mock providers; --smoke needs no external services.
ENTRYPOINT ["python", "-m", "workers.ingest.worker"]
CMD ["--smoke"]
