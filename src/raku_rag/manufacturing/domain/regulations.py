"""Manufacturing regulation / standard anchors for metadata and review.

The catalog is intentionally small and explicit. It is a routing aid for RAG evidence and SME review,
not a legal-compliance engine. Tenant-specific applicability and latest local editions must still be
reviewed by the customer / SME before a document is treated as compliant.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from raku_rag.manufacturing.domain.metadata import DocumentKind, ManufacturingDocumentMetadata


class RegulationJurisdiction(str, Enum):
    INTERNATIONAL = "international"
    JAPAN = "japan"
    TENANT_INTERNAL = "tenant_internal"


class RegulationCategory(str, Enum):
    OCCUPATIONAL_SAFETY = "occupational_safety"
    MACHINE_SAFETY = "machine_safety"
    ELECTRICAL_SAFETY = "electrical_safety"
    QUALITY_MANAGEMENT = "quality_management"
    INTERNAL_PROCEDURE = "internal_procedure"


@dataclass(frozen=True)
class RegulationDefinition:
    ref_id: str
    title: str
    jurisdiction: RegulationJurisdiction
    category: RegulationCategory
    edition: str
    source_url: str
    tags: tuple[str, ...] = ()
    related_refs: tuple[str, ...] = ()
    review_note: str = ""

    def to_mapping(self) -> dict:
        return {
            "ref_id": self.ref_id,
            "title": self.title,
            "jurisdiction": self.jurisdiction.value,
            "category": self.category.value,
            "edition": self.edition,
            "source_url": self.source_url,
            "tags": list(self.tags),
            "related_refs": list(self.related_refs),
            "review_note": self.review_note,
        }


REGULATION_CATALOG: dict[str, RegulationDefinition] = {
    "ISO_45001_2018": RegulationDefinition(
        ref_id="ISO_45001_2018",
        title="ISO 45001:2018 Occupational health and safety management systems",
        jurisdiction=RegulationJurisdiction.INTERNATIONAL,
        category=RegulationCategory.OCCUPATIONAL_SAFETY,
        edition="2018",
        source_url="https://www.iso.org/standard/63787.html",
        tags=("ohs", "risk_assessment", "incident", "worker_safety"),
        review_note="Confirmed by ISO as reviewed/current in 2024; a DIS revision is under development.",
    ),
    "ISO_12100_2010": RegulationDefinition(
        ref_id="ISO_12100_2010",
        title="ISO 12100:2010 Safety of machinery - risk assessment and risk reduction",
        jurisdiction=RegulationJurisdiction.INTERNATIONAL,
        category=RegulationCategory.MACHINE_SAFETY,
        edition="2010",
        source_url="https://www.iso.org/standard/51528.html",
        tags=("machine_safety", "risk_assessment", "risk_reduction", "guard", "hazard"),
        related_refs=("JIS_B_9700_2013",),
        review_note="Confirmed by ISO as reviewed/current in 2022; a DIS revision is under development.",
    ),
    "ISO_13849_1_2023": RegulationDefinition(
        ref_id="ISO_13849_1_2023",
        title="ISO 13849-1:2023 Safety-related parts of control systems",
        jurisdiction=RegulationJurisdiction.INTERNATIONAL,
        category=RegulationCategory.MACHINE_SAFETY,
        edition="2023",
        source_url="https://www.iso.org/standard/73481.html",
        tags=("control_system", "safety_function", "performance_level", "interlock"),
    ),
    "ISO_9001_2015": RegulationDefinition(
        ref_id="ISO_9001_2015",
        title="ISO 9001:2015 Quality management systems",
        jurisdiction=RegulationJurisdiction.INTERNATIONAL,
        category=RegulationCategory.QUALITY_MANAGEMENT,
        edition="2015",
        source_url="https://www.iso.org/standard/62085.html",
        tags=("quality", "qms", "customer_requirement", "corrective_action"),
        review_note="ISO reports the 2015 edition as current while a next edition is expected.",
    ),
    "JIS_B_9700_2013": RegulationDefinition(
        ref_id="JIS_B_9700_2013",
        title="JIS B 9700:2013 Machinery safety - general principles for design",
        jurisdiction=RegulationJurisdiction.JAPAN,
        category=RegulationCategory.MACHINE_SAFETY,
        edition="2013",
        source_url="https://www.jisc.go.jp/",
        tags=("machine_safety", "risk_assessment", "risk_reduction", "jis"),
        related_refs=("ISO_12100_2010",),
        review_note="Use JISC/JSA to confirm tenant-required edition before compliance use.",
    ),
    "JIS_B_9960_1_2019": RegulationDefinition(
        ref_id="JIS_B_9960_1_2019",
        title="JIS B 9960-1:2019 Safety of machinery - electrical equipment of machines",
        jurisdiction=RegulationJurisdiction.JAPAN,
        category=RegulationCategory.ELECTRICAL_SAFETY,
        edition="2019",
        source_url="https://www.jisc.go.jp/",
        tags=("electrical", "control_panel", "protective_bonding", "jis"),
        review_note="Use JISC/JSA to confirm tenant-required edition before compliance use.",
    ),
    "JP_ISHA": RegulationDefinition(
        ref_id="JP_ISHA",
        title="Japan Industrial Safety and Health Act",
        jurisdiction=RegulationJurisdiction.JAPAN,
        category=RegulationCategory.OCCUPATIONAL_SAFETY,
        edition="current_e-gov",
        source_url="https://elaws.e-gov.go.jp/document?lawid=347AC0000000057",
        tags=("law", "ohs", "worker_safety", "risk_assessment"),
        related_refs=("JP_ISH_RULES",),
    ),
    "JP_ISH_RULES": RegulationDefinition(
        ref_id="JP_ISH_RULES",
        title="Japan Ordinance on Industrial Safety and Health",
        jurisdiction=RegulationJurisdiction.JAPAN,
        category=RegulationCategory.OCCUPATIONAL_SAFETY,
        edition="current_e-gov",
        source_url="https://elaws.e-gov.go.jp/document?lawid=347M50002000032",
        tags=("ordinance", "ohs", "worker_safety"),
        related_refs=("JP_ISHA",),
    ),
}


_CATALOG_ORDER = tuple(REGULATION_CATALOG)

_ELECTRICAL_TAGS = {
    "electrical",
    "electricity",
    "electric_shock",
    "energized",
    "live_wire",
    "control_panel",
    "感電",
    "高圧",
    "通電",
    "制御盤",
}
_MACHINE_SAFETY_TAGS = {
    "guard",
    "machine_guard",
    "safety_device",
    "lockout_tagout",
    "disassembly",
    "maintenance",
    "設備停止",
    "分解",
    "安全装置",
    "安全カバー",
    "非常停止",
}


def get_regulation(ref_id: str) -> RegulationDefinition:
    try:
        return REGULATION_CATALOG[ref_id]
    except KeyError as exc:
        raise ValueError(f"unknown regulation ref: {ref_id}") from exc


def validate_regulation_refs(refs: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for ref in refs:
        ref_id = str(ref)
        get_regulation(ref_id)
        if ref_id not in normalized:
            normalized.append(ref_id)
    return tuple(normalized)


def infer_regulation_refs(meta: ManufacturingDocumentMetadata) -> tuple[str, ...]:
    """Return explicit + inferred regulation anchors for a document.

    The output is deterministic and follows catalog order. It errs on the side of adding review
    anchors for safety/quality documents, but it does not claim legal applicability.
    """
    refs = set(validate_regulation_refs(meta.regulation_refs))
    normalized_tags = {str(tag).strip().lower() for tag in meta.hazard_tags if str(tag).strip()}
    raw_tags = {str(tag).strip() for tag in meta.hazard_tags if str(tag).strip()}

    has_safety = bool(meta.safety_category or meta.equipment_operation_category or raw_tags)
    has_quality = bool(meta.quality_category)
    is_quality_doc = meta.document_kind in {
        DocumentKind.INSPECTION,
        DocumentKind.QUALITY_REPORT,
    }

    if has_safety:
        refs.update({"JP_ISHA", "JP_ISH_RULES", "ISO_45001_2018"})
    if has_quality or is_quality_doc:
        refs.add("ISO_9001_2015")
    if raw_tags & _MACHINE_SAFETY_TAGS or normalized_tags & _MACHINE_SAFETY_TAGS:
        refs.update({"ISO_12100_2010", "JIS_B_9700_2013"})
    if raw_tags & _ELECTRICAL_TAGS or normalized_tags & _ELECTRICAL_TAGS:
        refs.add("JIS_B_9960_1_2019")
    if "safety_device" in normalized_tags or "interlock" in normalized_tags:
        refs.add("ISO_13849_1_2023")

    return tuple(ref for ref in _CATALOG_ORDER if ref in refs)
