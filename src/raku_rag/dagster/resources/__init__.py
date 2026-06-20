"""Dagster-compatible resource descriptors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DagsterResourceSpec:
    name: str
    description: str
    request_path_allowed: bool = False


INGESTION_RESOURCES: tuple[DagsterResourceSpec, ...] = (
    DagsterResourceSpec("source_manifest_store", "SourceDocumentManifest repository"),
    DagsterResourceSpec(
        "ingestion_run_store", "IngestionRun and DocumentProcessingState repository"
    ),
    DagsterResourceSpec("connector_registry", "Source connector lookup"),
    DagsterResourceSpec("ingestion_executor", "Shared parse/chunk/embed/upsert executor"),
)
