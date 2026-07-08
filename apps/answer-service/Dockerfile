# Python answer-service — the internal HTTP boundary (/internal/*) over the Postgres-backed
# ProductionSystem (retrieval / ACL / ranking / manufacturing safety overlay). Build with context = repo
# ROOT (needs src/ = the raku_rag package, workers/ = provider_policy, and apps/answer-service):
#   docker build -f apps/answer-service/Dockerfile -t raku-rag-answer .
#
# Production serves only (no --reset-demo-db / --seed; the reset guard refuses non-local DBs anyway).
# Apply schema migrations and seed via one-off tasks, not here.
ARG PYTHON_BASE_IMAGE=public.ecr.aws/docker/library/python:3.12-slim
FROM ${PYTHON_BASE_IMAGE} AS runtime

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

# psycopg drives the Postgres adapters; boto3 is needed only when RAKU_RUNTIME_PROFILE=production wires
# the real Bedrock providers; python-docx/openpyxl back the manufacturing metadata path.
RUN pip install --no-cache-dir \
      "psycopg[binary]>=3" boto3 "Pillow>=10" "pypdfium2>=4" python-docx==1.1.2 openpyxl==3.1.5

# ADR-018 opt-in (CDK passes INSTALL_DOCLING=1 only with `--context structuredIngest=true`): bake
# Docling (torch CPU wheels — the +cpu local tag outranks the CUDA wheel on PyPI, keeping the image
# CPU-only) plus the layout/TableFormer weights into the image, so the structured pipeline never
# downloads models at runtime. DOCLING_ARTIFACTS_PATH is read by docling's settings; with it set,
# docling loads models from the baked directory and never reaches for Hugging Face.
ARG INSTALL_DOCLING=0
ENV DOCLING_ARTIFACTS_PATH=/opt/docling-models
RUN if [ "${INSTALL_DOCLING}" = "1" ]; then \
      pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu "docling>=2,<3" \
      && docling-tools models download -o "${DOCLING_ARTIFACTS_PATH}" layout tableformer tableformerv2; \
    fi

COPY pyproject.toml ./
COPY src/ ./src/
COPY workers/ ./workers/
COPY apps/answer-service/ ./apps/answer-service/

EXPOSE 8088
# Serve the internal boundary. Migrations/seed are separate one-off tasks.
CMD ["python", "apps/answer-service/server.py", "--port", "8088"]
