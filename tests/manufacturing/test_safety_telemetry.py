"""T047 — SAFETY TELEMETRY CORRECTNESS (SC-MFG-013 Tier-B correctness gate; FR-MFG-030, US5-2).

Mechanism-pin for the safety telemetry that makes the safety control auditable to an operator. Per
loop-engineering §8 I2 this is a Tier-B *correctness* gate (not an absolute hard gate) — but it is
still mechanism-pinned so a regression that breaks the four load-bearing properties FAILS.

The four pinned properties (driven through the REAL audited answer path — NO parallel counter):

 (1) AUDIT-DERIVED — ``high_risk_query_count`` / ``safety_gate_block_count`` are computed by
     aggregating ``ManufacturingSystem.audit`` (the single source of truth, FR-MFG-030). The counts
     equal what an independent scan of the same audit log reports (no shadow counter).

 (2) MUTUAL EXCLUSIVITY — the block breakdown is keyed by the three SafetyBlockReason codes
     {approved_citation_missing, insufficient_evidence, other_block} and
     ``sum(breakdown.values()) == safety_gate_block_count``: ONE block is counted under exactly ONE
     primary reason code (FR-MFG-030; normalization priority approved_citation_missing >
     insufficient_evidence > other_block). Driven with blocks of DIFFERENT reasons.

 (3) IDEMPOTENT — recomputing telemetry over the SAME window yields IDENTICAL numbers. Aggregation is
     by GROUP/SUM over stable audit content, not COUNT-DISTINCT on volatile row ids, so a recompute
     does not double-count. Two successive calls return equal counts AND equal breakdowns.

 (4) AXES — ``high_risk_query_count`` / ``safety_gate_block_count`` are groupable by
     ``factory`` / ``department``, sourced from the US6 (T056) actor org-context snapshot on the
     immutable ``AuditLogEntry`` (department == the actor's 001 ACL group; factory == the resolved
     Factory territory supplied to the answer call). Per-axis counts sum back to the tenant total.

Entrypoint contract the stage-2 ``ManufacturingSystem`` must satisfy (additive to the existing
audit wiring; the answer path already records the high-risk + safety decision via
``record_answer_decision`` — this phase aggregates it and stamps the org-context snapshot):

  answer(principal, query, collection_id=None, intent_hint=None, manufacturing_filters=None,
         factory_id=None) -> ManufacturingAnswer
      The OPTIONAL ``factory_id`` (the actor's resolved Factory territory) is snapshotted onto the
      answer-path AuditLogEntry org-context (raku_rag.manufacturing.domain.audit.stamp_org_context,
      T056) together with the department (the actor's primary 001 ACL group). Existing answer
      behaviour is unchanged when ``factory_id`` is omitted.

  safety_telemetry(principal, *, collection_id=None, factory_id=None, department_id=None,
                   time_range=None, axis=None, granularity="daily") -> SafetyTelemetryResult-shaped
      Aggregates ``self.audit`` (single source of truth) into high_risk_query_count /
      safety_gate_block_count / block_breakdown (mutually exclusive, FR-MFG-030). When ``factory_id``
      or ``department_id`` is supplied, the counts are RESTRICTED to that org-context axis; with no
      axis filter the counts are the tenant total. ``.source == "audit_log"``.

TDD: RED now because ``ManufacturingSystem`` has no ``safety_telemetry`` entrypoint and ``answer`` does
not yet stamp the factory org-context (missing-impl: AttributeError / unsupported kwarg), NOT an
unrelated import error. Assertion style mirrors tests/manufacturing/test_audit_coverage.py.

stdlib only. Authoritative: spec FR-MFG-012/028/030, SC-MFG-013; quickstart S10;
contracts/mfg-openapi.md §E; contracts/mfg-interfaces.md §8; data-model §I.
"""
from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.domain.audit import actor_org_context
from raku_rag.manufacturing.domain.metadata import (
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)
from raku_rag.manufacturing.domain.safety import SafetyBlockReason
from tests.manufacturing.helpers import T, mfg_meta

# The three (and only three) mutually-exclusive block reason codes (FR-MFG-030).
BLOCK_CODES = (
    SafetyBlockReason.APPROVED_CITATION_MISSING.value,
    SafetyBlockReason.INSUFFICIENT_EVIDENCE.value,
    SafetyBlockReason.OTHER_BLOCK.value,
)


def _admin(tenant: str = T, user: str = "admin-1") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user, roles=("admin",))


def _op(user: str, *, dept: str) -> IdentityClaims:
    """An operator whose primary ACL group is ``dept`` (department == ACL group, FR-MFG-013)."""
    return IdentityClaims(tenant_id=T, user_id=user, groups=(dept,))


def _get(obj, name):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _breakdown(tel) -> dict:
    bd = _get(tel, "block_breakdown")
    if bd is None:
        bd = _get(tel, "safety_gate_block_breakdown")
    return dict(bd or {})


# --- audit-side ground truth (the INDEPENDENT recomputation telemetry is checked against) ---------
def _audit_high_risk_count(entries) -> int:
    return sum(1 for e in entries if getattr(e, "high_risk_classification_result", None) is True)


def _audit_block_count(entries) -> int:
    return sum(1 for e in entries if getattr(e, "safety_block_reason", None) is not None)


def _audit_block_breakdown(entries) -> dict:
    out: dict[str, int] = {c: 0 for c in BLOCK_CODES}
    for e in entries:
        r = getattr(e, "safety_block_reason", None)
        if r is not None:
            out[getattr(r, "value", r)] += 1
    return out


def _seed_docs(sys) -> None:
    """Approved+effective doc (assertable), a draft doc + an obsolete doc (both block, DIFFERENT reasons)."""
    # Approved + effective lockout/tagout work instruction -> a high-risk answer CAN assert (no block).
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
    # Draft-only high-risk topic (electrical) -> high-risk answer BLOCKED: approved_citation_missing.
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
    # Obsolete-only NON-high-risk topic -> answer BLOCKED: insufficient_evidence (different reason).
    sys.ingest_manufacturing(
        tenant_id=T,
        collection_id="c",
        document_id="old1",
        text="Old torque spec note for the bracket assembly fastener.",
        metadata=mfg_meta(
            tenant_id=T,
            document_id="old1",
            approval_status=ApprovalStatus.OBSOLETE,
            effective_date="2024-01-01",
            obsolete_at="2025-06-01",
        ),
    )
    sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op_press")
    sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "op_weld")


# High-risk + asserts (approved citation present) — counts as high-risk, NOT a block.
Q_HIGH_RISK_OK = "How do I disassemble the press safely after lockout/tagout?"
# High-risk + only draft evidence — blocked with approved_citation_missing.
Q_HIGH_RISK_BLOCK = "How do I work on the 400V panel without getting electrocuted?"
# Non-high-risk + only obsolete evidence — blocked with insufficient_evidence.
Q_NON_HR_BLOCK = "what is the torque spec for the bracket assembly fastener?"


def _drive_flow(sys, *, factory_id: str | None, op: IdentityClaims) -> None:
    """Drive several high-risk queries and several blocks of DIFFERENT reasons via the audited path."""
    sys.answer(op, Q_HIGH_RISK_OK, collection_id="c", factory_id=factory_id)
    sys.answer(op, Q_HIGH_RISK_BLOCK, collection_id="c", factory_id=factory_id)
    sys.answer(op, Q_NON_HR_BLOCK, collection_id="c", factory_id=factory_id)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.manufacturing.app import ManufacturingSystem

        self.sys = ManufacturingSystem()
        _seed_docs(self.sys)
        self.admin = _admin()


class TestTelemetryAuditDerived(_Base):
    """(1) Telemetry is derived from the audit log (single source of truth), not a shadow counter."""

    def test_counts_match_independent_audit_scan(self) -> None:
        # f1/dept_press operator drives the flow; f2/dept_weld operator drives it again.
        _drive_flow(self.sys, factory_id="f1", op=_op("op_press", dept="dept_press"))
        _drive_flow(self.sys, factory_id="f2", op=_op("op_weld", dept="dept_weld"))

        tel = self.sys.safety_telemetry(self.admin)
        entries = self.sys.audit.read_all(self.admin)

        self.assertEqual(
            _get(tel, "high_risk_query_count"),
            _audit_high_risk_count(entries),
            "high_risk_query_count MUST equal an independent scan of the audit log (single source)",
        )
        self.assertEqual(
            _get(tel, "safety_gate_block_count"),
            _audit_block_count(entries),
            "safety_gate_block_count MUST equal an independent scan of the audit log (single source)",
        )
        self.assertEqual(
            _get(tel, "source"), "audit_log", "telemetry must declare audit_log as its source"
        )

    def test_counts_are_nonzero_for_the_driven_flow(self) -> None:
        # The flow really exercised high-risk queries AND blocks of different reasons (non-vacuous).
        _drive_flow(self.sys, factory_id="f1", op=_op("op_press", dept="dept_press"))
        tel = self.sys.safety_telemetry(self.admin)
        self.assertGreater(_get(tel, "high_risk_query_count"), 0, "the flow must produce high-risk queries")
        self.assertGreater(_get(tel, "safety_gate_block_count"), 0, "the flow must produce safety blocks")


class TestTelemetryMutualExclusivity(_Base):
    """(2) The block breakdown is mutually exclusive: one block = exactly one primary reason code."""

    def test_breakdown_sums_to_total_block_count(self) -> None:
        _drive_flow(self.sys, factory_id="f1", op=_op("op_press", dept="dept_press"))
        _drive_flow(self.sys, factory_id="f2", op=_op("op_weld", dept="dept_weld"))

        tel = self.sys.safety_telemetry(self.admin)
        bd = _breakdown(tel)
        # only the three codes may appear
        self.assertTrue(set(bd.keys()) <= set(BLOCK_CODES), f"unexpected breakdown keys: {set(bd.keys())}")
        # MUTUAL EXCLUSIVITY: every block counted under exactly ONE reason => the parts sum to the total.
        self.assertEqual(
            sum(bd.values()),
            _get(tel, "safety_gate_block_count"),
            "sum(breakdown) MUST equal safety_gate_block_count (1 block = 1 primary reason, FR-MFG-030)",
        )

    def test_different_reasons_are_both_present(self) -> None:
        # The flow produces approved_citation_missing (high-risk, draft-only) AND insufficient_evidence
        # (non-high-risk, obsolete-only) — DIFFERENT reasons, each counted under its own code.
        _drive_flow(self.sys, factory_id="f1", op=_op("op_press", dept="dept_press"))
        bd = _breakdown(self.sys.safety_telemetry(self.admin))
        self.assertGreater(
            bd.get(SafetyBlockReason.APPROVED_CITATION_MISSING.value, 0),
            0,
            "the high-risk draft-only query must be blocked as approved_citation_missing",
        )
        self.assertGreater(
            bd.get(SafetyBlockReason.INSUFFICIENT_EVIDENCE.value, 0),
            0,
            "the non-high-risk obsolete-only query must be blocked as insufficient_evidence",
        )

    def test_breakdown_matches_independent_audit_scan(self) -> None:
        _drive_flow(self.sys, factory_id="f1", op=_op("op_press", dept="dept_press"))
        tel = self.sys.safety_telemetry(self.admin)
        entries = self.sys.audit.read_all(self.admin)
        observed = {k: v for k, v in _breakdown(tel).items() if v}
        expected = {k: v for k, v in _audit_block_breakdown(entries).items() if v}
        self.assertEqual(observed, expected, "breakdown MUST equal an independent audit-log scan")


class TestTelemetryIdempotent(_Base):
    """(3) Recomputing over the same window yields IDENTICAL numbers (no double-count)."""

    def test_recompute_is_identical(self) -> None:
        _drive_flow(self.sys, factory_id="f1", op=_op("op_press", dept="dept_press"))
        _drive_flow(self.sys, factory_id="f2", op=_op("op_weld", dept="dept_weld"))

        a = self.sys.safety_telemetry(self.admin)
        b = self.sys.safety_telemetry(self.admin)
        self.assertEqual(_get(a, "high_risk_query_count"), _get(b, "high_risk_query_count"))
        self.assertEqual(_get(a, "safety_gate_block_count"), _get(b, "safety_gate_block_count"))
        self.assertEqual(
            _breakdown(a), _breakdown(b), "two computations over the same window MUST be identical"
        )

    def test_recompute_does_not_double_count_against_audit(self) -> None:
        # The recomputed counts still match the audit-log ground truth (aggregation by GROUP/SUM, not
        # a stateful COUNT-DISTINCT that could drift on a second pass).
        _drive_flow(self.sys, factory_id="f1", op=_op("op_press", dept="dept_press"))
        self.sys.safety_telemetry(self.admin)  # first pass
        tel2 = self.sys.safety_telemetry(self.admin)  # second pass
        entries = self.sys.audit.read_all(self.admin)
        self.assertEqual(_get(tel2, "high_risk_query_count"), _audit_high_risk_count(entries))
        self.assertEqual(_get(tel2, "safety_gate_block_count"), _audit_block_count(entries))


class TestTelemetryAxes(_Base):
    """(4) Counts are groupable by factory / department (US6 actor org-context snapshot)."""

    def setUp(self) -> None:
        super().setUp()
        # Same flow from TWO org-contexts: factory f1/dept_press and factory f2/dept_weld.
        self.op1 = _op("op_press", dept="dept_press")
        self.op2 = _op("op_weld", dept="dept_weld")
        _drive_flow(self.sys, factory_id="f1", op=self.op1)
        _drive_flow(self.sys, factory_id="f2", op=self.op2)

    def test_org_context_is_derived_from_acl_group_and_factory(self) -> None:
        # Sanity-pin the FR-MFG-013 derivation used as the axis source (department == ACL group).
        self.assertEqual(actor_org_context(self.op1, factory_id="f1"), ("f1", "dept_press"))
        self.assertEqual(actor_org_context(self.op2, factory_id="f2"), ("f2", "dept_weld"))

    def test_factory_axis_partitions_the_total(self) -> None:
        total = self.sys.safety_telemetry(self.admin)
        f1 = self.sys.safety_telemetry(self.admin, factory_id="f1")
        f2 = self.sys.safety_telemetry(self.admin, factory_id="f2")
        # each factory saw the same flow -> non-zero, and the two factories partition the tenant total.
        self.assertGreater(_get(f1, "safety_gate_block_count"), 0)
        self.assertGreater(_get(f2, "safety_gate_block_count"), 0)
        self.assertEqual(
            _get(f1, "high_risk_query_count") + _get(f2, "high_risk_query_count"),
            _get(total, "high_risk_query_count"),
            "per-factory high_risk_query_count MUST sum to the tenant total (axis partition)",
        )
        self.assertEqual(
            _get(f1, "safety_gate_block_count") + _get(f2, "safety_gate_block_count"),
            _get(total, "safety_gate_block_count"),
            "per-factory safety_gate_block_count MUST sum to the tenant total (axis partition)",
        )

    def test_department_axis_partitions_the_total(self) -> None:
        total = self.sys.safety_telemetry(self.admin)
        d1 = self.sys.safety_telemetry(self.admin, department_id="dept_press")
        d2 = self.sys.safety_telemetry(self.admin, department_id="dept_weld")
        self.assertGreater(_get(d1, "high_risk_query_count"), 0)
        self.assertGreater(_get(d2, "high_risk_query_count"), 0)
        self.assertEqual(
            _get(d1, "safety_gate_block_count") + _get(d2, "safety_gate_block_count"),
            _get(total, "safety_gate_block_count"),
            "per-department safety_gate_block_count MUST sum to the tenant total (axis partition)",
        )

    def test_axis_breakdown_is_also_mutually_exclusive(self) -> None:
        # Mutual exclusivity holds within an axis slice too.
        f1 = self.sys.safety_telemetry(self.admin, factory_id="f1")
        bd = _breakdown(f1)
        self.assertEqual(sum(bd.values()), _get(f1, "safety_gate_block_count"))


if __name__ == "__main__":
    unittest.main()
