"""T046 — Knowledge-ops Dashboard / Safety-Telemetry / KPI SHAPE contract (US5; §E).

Response-shape contract for the THREE NEW US5 admin endpoints exposed by the in-memory
``ManufacturingSystem`` (contracts/mfg-openapi.md §E, FR-MFG-012/028/030, US5-1/US5-2):

  - GET /v1/manufacturing/dashboard        -> knowledge_ops_dashboard(...)
  - GET /v1/manufacturing/safety-telemetry -> safety_telemetry(...)
  - GET /v1/manufacturing/kpi              -> kpi(..., format=...)

This is the SHAPE axis only. The load-bearing TELEMETRY CORRECTNESS (audit-derived, mutually
exclusive breakdown, idempotent, factory/department axes — SC-MFG-013, FR-MFG-030) is mechanism-pinned
by T047 (test_safety_telemetry.py). Assertion style mirrors tests/manufacturing/
test_governance_contract.py + test_trouble_cases_contract.py.

Entrypoint contract the stage-2 ``ManufacturingSystem`` must satisfy (admin endpoints; the dashboard
computes SYNCHRONOUSLY from the in-memory audit log / manufacturing metadata — NO Dagster, per §8 C5;
T047a/T051a materialization assets are DEFERRED to the production track):

  knowledge_ops_dashboard(principal, *, collection_id=None, factory_id=None, department_id=None,
                          time_range=None) -> object | dict
      GET /v1/manufacturing/dashboard. Surfaces (FR-MFG-012, US5-1; 001 feedback/observability +
      audit aggregation):
        .unanswered_question_count          : int   (answers that did not assert — insufficient_evidence/blocked)
        .low_rating_answers                 : tuple  (answers a reviewer/user rated low)
        .frequent_questions                 : tuple
        .frequently_referenced_documents    : tuple  (documents most cited — from citation-access audit)
        .obsolete_document_candidates       : tuple  (obsolete/expired docs — from approval metadata)
        .knowledge_gap_areas                : tuple  (topics with repeated unanswered / no approved evidence)
        .correlation_id                     : str
      Tenant-scoped; the breakdown is DERIVED from the shared audit log (single source of truth).

  safety_telemetry(principal, *, collection_id=None, factory_id=None, department_id=None,
                   time_range=None, axis=None, granularity="daily") -> object | dict
      GET /v1/manufacturing/safety-telemetry (FR-MFG-030, SC-MFG-013). Returns a
      ``SafetyTelemetryResult``-shaped view (data-model §I):
        .high_risk_query_count     : int
        .safety_gate_block_count   : int
        .block_breakdown / .safety_gate_block_breakdown : dict mutually-exclusive over
            {approved_citation_missing, insufficient_evidence, other_block}
        .source == "audit_log"     (audit log is the single source of truth, FR-MFG-030)
        .correlation_id            : str

  kpi(principal, *, collection_id=None, time_range=None, format="json") -> dict | str
      GET /v1/manufacturing/kpi (FR-MFG-028, SC-MFG-012). Computes the FULL FR-MFG-028 KPI set and
      EXPORTS it as json (dict) or csv (str). KPI keys (data-model §I):
        self_resolution_rate, average_time_to_answer{p50,p95}, grounded_answer_rate,
        insufficient_evidence_rate, low_rating_rate, unanswered_question_count,
        frequently_referenced_documents, obsolete_document_candidates, expert_interruption_reduction,
        high_risk_query_count, safety_gate_block_count, materialized_at.

TDD: RED now because ``ManufacturingSystem`` has no dashboard / safety_telemetry / kpi entrypoints
yet (missing-impl: AttributeError), NOT an unrelated import error.

stdlib only. Authoritative: spec FR-MFG-012/028/030, SC-MFG-012/013; quickstart S10;
contracts/mfg-openapi.md §E; contracts/mfg-interfaces.md §8; data-model §I.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.domain.safety import SafetyBlockReason
from tests.manufacturing.helpers import T, mfg_meta

# The three (and only three) mutually-exclusive block reason codes (FR-MFG-030, contracts §E).
BLOCK_CODES = frozenset(
    {
        SafetyBlockReason.APPROVED_CITATION_MISSING.value,
        SafetyBlockReason.INSUFFICIENT_EVIDENCE.value,
        SafetyBlockReason.OTHER_BLOCK.value,
    }
)

# FR-MFG-028 KPI set (data-model §I; contracts §E res 200). Every key MUST be computable + exportable.
KPI_KEYS = (
    "self_resolution_rate",
    "average_time_to_answer",
    "grounded_answer_rate",
    "insufficient_evidence_rate",
    "low_rating_rate",
    "unanswered_question_count",
    "frequently_referenced_documents",
    "obsolete_document_candidates",
    "expert_interruption_reduction",
    "high_risk_query_count",
    "safety_gate_block_count",
)

# Dashboard surfaces (FR-MFG-012, US5-1; contracts §E res 200).
DASHBOARD_SURFACES = (
    "unanswered_question_count",
    "low_rating_answers",
    "frequent_questions",
    "frequently_referenced_documents",
    "obsolete_document_candidates",
    "knowledge_gap_areas",
)


def _admin(tenant: str = T, user: str = "admin-1") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user, roles=("admin",))


def _op(tenant: str = T, user: str = "op", groups=("dept_press",)) -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user, groups=tuple(groups))


def _attr_or_key(obj, name):
    """Read ``name`` from an object attribute or a mapping key (the entrypoint may return either)."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _has(obj, name) -> bool:
    if isinstance(obj, dict):
        return name in obj
    return hasattr(obj, name)


def _breakdown(telemetry) -> dict:
    """The mutually-exclusive block breakdown under either the data-model or the API field name."""
    bd = _attr_or_key(telemetry, "block_breakdown")
    if bd is None:
        bd = _attr_or_key(telemetry, "safety_gate_block_breakdown")
    return bd or {}


def _seed_and_drive(sys) -> None:
    """Ingest an approved doc + an obsolete doc, then drive answers that populate the audit log.

    Produces, through the REAL audited answer path:
      - a high-risk answer that ASSERTS (approved+effective citation) — high_risk + citation access,
      - a high-risk answer BLOCKED for approved_citation_missing (draft-only evidence),
      - a non-high-risk answer that did not assert (insufficient_evidence) — an unanswered question,
      - an obsolete document on file — an obsolete_document_candidate.
    """
    op = _op()
    # Approved + effective doc (lockout/tagout work instruction) the high-risk answer can cite.
    sys.ingest_manufacturing(
        tenant_id=T,
        collection_id="c",
        document_id="appr1",
        text="Approved lockout/tagout procedure: isolate, lock, tag, verify zero energy before disassembly.",
        metadata=mfg_meta(
            tenant_id=T,
            document_id="appr1",
            approval_status=ApprovalStatus.APPROVED,
            effective_date="2026-01-10",
            document_kind=DocumentKind.WORK_INSTRUCTION,
            safety_category="lockout_tagout",
            hazard_tags=("設備停止", "分解"),
        ),
    )
    # Draft-only doc for a different high-risk topic -> high-risk answer blocked (approved_citation_missing).
    sys.ingest_manufacturing(
        tenant_id=T,
        collection_id="c",
        document_id="draft1",
        text="Draft note about working on the 400V panel — not yet approved.",
        metadata=ManufacturingDocumentMetadata(
            tenant_id=T,
            document_id="draft1",
            approval_status=ApprovalStatus.DRAFT,
            effective_date=None,
            document_kind=DocumentKind.WORK_INSTRUCTION,
            safety_category="electrical",
            hazard_tags=("感電", "高圧"),
        ),
    )
    # Obsolete doc -> an obsolete_document_candidate (and obsolete-only evidence cannot back an answer).
    sys.ingest_manufacturing(
        tenant_id=T,
        collection_id="c",
        document_id="old1",
        text="Old torque spec note for the bracket assembly.",
        metadata=mfg_meta(
            tenant_id=T,
            document_id="old1",
            approval_status=ApprovalStatus.OBSOLETE,
            effective_date="2024-01-01",
            obsolete_at="2025-06-01",
        ),
    )
    sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op")

    # high-risk + asserts (approved citation) — produces high_risk + citation access in audit.
    sys.answer(op, "How do I disassemble the press safely after lockout/tagout?", collection_id="c")
    # high-risk + blocked (only draft evidence) — approved_citation_missing.
    sys.answer(
        op, "How do I work on the 400V panel without getting electrocuted?", collection_id="c"
    )
    # non-high-risk question whose only evidence is obsolete — does not assert (insufficient_evidence).
    sys.answer(op, "what is the torque spec for the bracket assembly?", collection_id="c")


class TestSafetyTelemetryResponseShape(unittest.TestCase):
    """GET /v1/manufacturing/safety-telemetry response shape (contracts §E)."""

    def setUp(self) -> None:
        from raku_rag.manufacturing.app import ManufacturingSystem

        self.sys = ManufacturingSystem()
        _seed_and_drive(self.sys)
        self.admin = _admin()

    def test_telemetry_has_counts_breakdown_and_source(self) -> None:
        tel = self.sys.safety_telemetry(self.admin)
        # high-risk + block counts present and integral.
        self.assertIsInstance(_attr_or_key(tel, "high_risk_query_count"), int)
        self.assertIsInstance(_attr_or_key(tel, "safety_gate_block_count"), int)
        # breakdown present.
        self.assertTrue(_breakdown(tel) != {} or _attr_or_key(tel, "safety_gate_block_count") == 0)

    def test_breakdown_keys_are_exactly_the_three_block_codes(self) -> None:
        # The breakdown is keyed ONLY by the three mutually-exclusive SafetyBlockReason codes (§E).
        tel = self.sys.safety_telemetry(self.admin)
        bd = _breakdown(tel)
        self.assertTrue(
            set(bd.keys()) <= BLOCK_CODES, f"unexpected breakdown keys: {set(bd.keys())}"
        )

    def test_source_is_audit_log(self) -> None:
        # FR-MFG-030: audit log is the single source of truth. The view declares its provenance.
        tel = self.sys.safety_telemetry(self.admin)
        self.assertEqual(
            _attr_or_key(tel, "source"),
            "audit_log",
            "safety telemetry MUST declare source=='audit_log' (single source of truth, FR-MFG-030)",
        )

    def test_telemetry_is_tenant_scoped(self) -> None:
        # Another tenant's admin sees none of this tenant's high-risk / block activity.
        other = _admin(tenant="tenant_other", user="admin-other")
        tel = self.sys.safety_telemetry(other)
        self.assertEqual(_attr_or_key(tel, "high_risk_query_count"), 0)
        self.assertEqual(_attr_or_key(tel, "safety_gate_block_count"), 0)


class TestDashboardResponseShape(unittest.TestCase):
    """GET /v1/manufacturing/dashboard response shape (contracts §E, FR-MFG-012, US5-1)."""

    def setUp(self) -> None:
        from raku_rag.manufacturing.app import ManufacturingSystem

        self.sys = ManufacturingSystem()
        _seed_and_drive(self.sys)
        self.admin = _admin()

    def test_dashboard_surfaces_all_required_views(self) -> None:
        dash = self.sys.knowledge_ops_dashboard(self.admin)
        for surface in DASHBOARD_SURFACES:
            self.assertTrue(
                _has(dash, surface),
                f"knowledge-ops dashboard MUST surface {surface!r} (FR-MFG-012, US5-1)",
            )
        self.assertTrue(_has(dash, "correlation_id"))

    def test_dashboard_surfaces_obsolete_document_candidates(self) -> None:
        # An obsolete document on file is surfaced as an obsolete_document_candidate (stale, US5-1).
        dash = self.sys.knowledge_ops_dashboard(self.admin)
        cands = _attr_or_key(dash, "obsolete_document_candidates") or ()
        joined = " ".join(str(c) for c in cands)
        self.assertIn("old1", joined, "the obsolete document must appear as an obsolete candidate")

    def test_dashboard_unanswered_count_is_nonzero(self) -> None:
        # The blocked / insufficient-evidence answers in the audited flow are surfaced as unanswered.
        dash = self.sys.knowledge_ops_dashboard(self.admin)
        unanswered = _attr_or_key(dash, "unanswered_question_count")
        self.assertIsInstance(unanswered, int)
        self.assertGreater(
            unanswered, 0, "answers that did not assert must be surfaced as unanswered questions"
        )

    def test_dashboard_frequently_referenced_documents_from_citation_audit(self) -> None:
        # The doc cited by the asserted high-risk answer is surfaced as a frequently-referenced doc
        # (derived from the citation-access audit — single source of truth, not a parallel counter).
        dash = self.sys.knowledge_ops_dashboard(self.admin)
        freq = _attr_or_key(dash, "frequently_referenced_documents") or ()
        joined = " ".join(str(d) for d in freq)
        self.assertIn("appr1", joined, "the cited approved doc must be a frequently-referenced doc")

    def test_dashboard_is_tenant_scoped(self) -> None:
        other = _admin(tenant="tenant_other", user="admin-other")
        dash = self.sys.knowledge_ops_dashboard(other)
        self.assertEqual(_attr_or_key(dash, "unanswered_question_count"), 0)
        self.assertEqual(tuple(_attr_or_key(dash, "obsolete_document_candidates") or ()), ())


class TestKpiResponseShapeAndExport(unittest.TestCase):
    """GET /v1/manufacturing/kpi — full FR-MFG-028 KPI set, computable + exportable (SC-MFG-012)."""

    def setUp(self) -> None:
        from raku_rag.manufacturing.app import ManufacturingSystem

        self.sys = ManufacturingSystem()
        _seed_and_drive(self.sys)
        self.admin = _admin()

    def test_kpi_json_has_full_fr_mfg_028_set(self) -> None:
        kpi = self.sys.kpi(self.admin, format="json")
        self.assertIsInstance(kpi, dict)
        for key in KPI_KEYS:
            self.assertIn(key, kpi, f"FR-MFG-028 KPI {key!r} must be computable (SC-MFG-012)")
        # average_time_to_answer carries p50/p95 (data-model §I).
        att = kpi["average_time_to_answer"]
        self.assertTrue(
            (isinstance(att, dict) and "p50" in att and "p95" in att),
            "average_time_to_answer must carry {p50, p95}",
        )
        # safety-telemetry counters are part of the KPI snapshot (FR-MFG-028 specializes FR-MFG-030).
        self.assertIsInstance(kpi["high_risk_query_count"], int)
        self.assertIsInstance(kpi["safety_gate_block_count"], int)
        self.assertIn(
            "materialized_at", kpi, "KPI snapshot must record materialized_at (data-model §I)"
        )

    def test_kpi_csv_export_is_text_and_contains_every_kpi(self) -> None:
        # SC-MFG-012: the FR-MFG-028 KPI set must be EXPORTABLE (json/csv).
        csv = self.sys.kpi(self.admin, format="csv")
        self.assertIsInstance(csv, str)
        for key in KPI_KEYS:
            self.assertIn(key, csv, f"csv export must include KPI {key!r} (FR-MFG-028 export)")

    def test_kpi_safety_counts_match_safety_telemetry(self) -> None:
        # The KPI safety counters are derived from the SAME audit log as safety-telemetry (consistency).
        kpi = self.sys.kpi(self.admin, format="json")
        tel = self.sys.safety_telemetry(self.admin)
        self.assertEqual(kpi["high_risk_query_count"], _attr_or_key(tel, "high_risk_query_count"))
        self.assertEqual(
            kpi["safety_gate_block_count"], _attr_or_key(tel, "safety_gate_block_count")
        )


if __name__ == "__main__":
    unittest.main()
