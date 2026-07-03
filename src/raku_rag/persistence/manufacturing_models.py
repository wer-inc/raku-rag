"""Manufacturing production-table model declarations.

The local MVP keeps runtime state in stdlib repositories, while the production dependency group
enables SQLAlchemy/Alembic. This module therefore exposes stable table metadata in all environments
and only builds SQLAlchemy declarative classes when SQLAlchemy is installed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ManufacturingTableSpec:
    table_name: str
    primary_key: str
    tenant_scoped: bool = True
    depends_on_document_metadata: bool = False


MANUFACTURING_TABLES: tuple[ManufacturingTableSpec, ...] = (
    ManufacturingTableSpec("manufacturing_factories", "factory_id"),
    ManufacturingTableSpec("manufacturing_production_lines", "production_line_id"),
    ManufacturingTableSpec("manufacturing_processes", "process_id"),
    ManufacturingTableSpec("manufacturing_equipment", "equipment_id"),
    ManufacturingTableSpec("manufacturing_products", "product_id"),
    ManufacturingTableSpec("manufacturing_parts", "part_id"),
    ManufacturingTableSpec("manufacturing_customers", "customer_id"),
    ManufacturingTableSpec("manufacturing_defect_types", "defect_type_id"),
    ManufacturingTableSpec("manufacturing_failure_modes", "failure_mode_id"),
    ManufacturingTableSpec("manufacturing_trouble_cases", "trouble_case_id"),
    ManufacturingTableSpec("manufacturing_countermeasures", "countermeasure_id"),
    ManufacturingTableSpec(
        "manufacturing_trouble_case_countermeasures",
        "trouble_case_countermeasure_id",
    ),
    ManufacturingTableSpec("manufacturing_work_instructions", "work_instruction_id"),
    ManufacturingTableSpec("manufacturing_inspection_checklists", "inspection_checklist_id"),
    ManufacturingTableSpec("manufacturing_quality_issues", "quality_issue_id"),
    ManufacturingTableSpec("manufacturing_training_materials", "training_material_id"),
    ManufacturingTableSpec(
        "manufacturing_document_metadata",
        "metadata_id",
        depends_on_document_metadata=True,
    ),
    ManufacturingTableSpec("manufacturing_draft_artifacts", "artifact_id"),
    ManufacturingTableSpec("manufacturing_audit_events", "audit_event_id"),
    ManufacturingTableSpec("manufacturing_safety_decisions", "safety_decision_id"),
    ManufacturingTableSpec("manufacturing_kpi_values", "kpi_value_id"),
    ManufacturingTableSpec(
        "manufacturing_dashboard_metric_snapshots",
        "snapshot_id",
    ),
)

MANUFACTURING_TABLE_NAMES: tuple[str, ...] = tuple(spec.table_name for spec in MANUFACTURING_TABLES)


try:  # pragma: no cover - production optional dependency path
    from sqlalchemy import Boolean, Date, DateTime, Integer, JSON, Numeric, String, Text
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
except ModuleNotFoundError:  # pragma: no cover - exercised by stdlib-only MVP gate
    Base = object
else:  # pragma: no cover - SQLAlchemy is optional in the local test environment

    class Base(DeclarativeBase):
        pass

    class ManufacturingDocumentMetadataModel(Base):
        __tablename__ = "manufacturing_document_metadata"

        metadata_id: Mapped[str] = mapped_column(String, primary_key=True)
        tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
        document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
        collection_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        factory_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        department_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        process_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        equipment_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        alarm_code: Mapped[str] = mapped_column(String, nullable=False, default="")
        defect_type: Mapped[str] = mapped_column(String, nullable=False, default="")
        part_no: Mapped[str] = mapped_column(String, nullable=False, default="")
        customer_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        document_kind: Mapped[str] = mapped_column(String, nullable=False)
        safety_category: Mapped[str] = mapped_column(String, nullable=False, default="")
        quality_category: Mapped[str] = mapped_column(String, nullable=False, default="")
        approval_status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
        effective_date: Mapped[object | None] = mapped_column(Date, nullable=True)
        # ★G4 document freshness (0024): owner / review cycle / last human verification.
        owner: Mapped[str] = mapped_column(String, nullable=False, default="")
        review_cycle_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        last_verified_at: Mapped[object | None] = mapped_column(Date, nullable=True)
        approval_metadata_checksum: Mapped[str] = mapped_column(String, nullable=False, default="")
        document_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
        is_tombstoned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    class ManufacturingTroubleCaseModel(Base):
        __tablename__ = "manufacturing_trouble_cases"

        trouble_case_id: Mapped[str] = mapped_column(String, primary_key=True)
        tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
        factory_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        process_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        equipment_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        failure_mode_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        defect_type_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        source_document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
        occurred_at: Mapped[object | None] = mapped_column(DateTime, nullable=True)
        summary_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")

    class ManufacturingDraftArtifactModel(Base):
        __tablename__ = "manufacturing_draft_artifacts"

        artifact_id: Mapped[str] = mapped_column(String, primary_key=True)
        tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
        artifact_type: Mapped[str] = mapped_column(String, nullable=False)
        status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
        created_by: Mapped[str] = mapped_column(String, nullable=False, default="ai")
        reviewer_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        source_document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
        payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    class ManufacturingSafetyDecisionModel(Base):
        __tablename__ = "manufacturing_safety_decisions"

        safety_decision_id: Mapped[str] = mapped_column(String, primary_key=True)
        tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
        query_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        high_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
        safety_block_reason: Mapped[str] = mapped_column(String, nullable=False, default="")
        approved_effective_citation_present: Mapped[bool] = mapped_column(
            Boolean,
            nullable=False,
            default=False,
        )
        source_citation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    class ManufacturingKpiValueModel(Base):
        __tablename__ = "manufacturing_kpi_values"

        kpi_value_id: Mapped[str] = mapped_column(String, primary_key=True)
        tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
        collection_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        metric_name: Mapped[str] = mapped_column(String, nullable=False)
        metric_value: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
        dimensions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
        source_ingestion_run_id: Mapped[str] = mapped_column(String, nullable=False, default="")
        materialized_at: Mapped[object | None] = mapped_column(DateTime, nullable=True)
        schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


__all__ = [
    "Base",
    "MANUFACTURING_TABLE_NAMES",
    "MANUFACTURING_TABLES",
    "ManufacturingTableSpec",
]
