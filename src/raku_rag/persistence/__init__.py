"""Production-track persistence adapters (001). Behind the same interfaces as the MVP in-memory core."""

from raku_rag.persistence.control_plane import (
    AssetMaterializationRef,
    DocumentProcessingProjection,
    InMemoryControlPlaneStateRepository,
    SourceSyncStatusProjection,
)
from raku_rag.persistence.provider_config_audit import (
    ProviderConfigAuditEvent,
    ProviderConfigAuditRepository,
)

__all__ = [
    "AssetMaterializationRef",
    "DocumentProcessingProjection",
    "InMemoryControlPlaneStateRepository",
    "ProviderConfigAuditEvent",
    "ProviderConfigAuditRepository",
    "SourceSyncStatusProjection",
]
