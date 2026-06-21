"""011 (P0-1) — the eval gate COMPUTES its security signal from real probes.

Mechanism-pinning hard gate (loop-engineering.md §3): a clean system must produce 0 leaks with the
probes actually executed; a deliberately-leaky system must be caught by EACH probe; an all-deny /
no-op system must fail the positive control (status=unavailable) so it cannot pass by returning
nothing; and the runner must block on a probe-found leak even with NO caller-supplied counts, while
still honoring a caller count as a force-block override (merge-by-max — keeps test_eval_hard_gate
valid unmodified).

source_poisoning_probe is tested here via deterministic stubs (it is held out of the default suite
because it reproduced a real vulnerability on the live ManufacturingSystem — see risk-register PR-016).
"""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.eval import EvaluationRunner, EvaluationSet, SecurityProbeSuite
from raku_rag.eval.probes import (
    acl_leakage_probe,
    deleted_reappearance_probe,
    prompt_injection_probe,
    source_poisoning_probe,
    tenant_isolation_probe,
)
from tests.helpers import claims, fresh

T = "tenant_a"
BASE_PROBES = (
    acl_leakage_probe,
    deleted_reappearance_probe,
    tenant_isolation_probe,
    prompt_injection_probe,
)


class _LeakyStub:
    """A deliberately-insecure base system: search/answer ignore ACL + tenant; delete is a no-op."""

    def __init__(self) -> None:
        self._docs: list = []
        self.deletion = SimpleNamespace(
            delete=lambda tenant_id, document_id: SimpleNamespace(invalidated_cache_entries=0)
        )

    def ingest_text(self, *, tenant_id, collection_id, document_id, text) -> None:
        self._docs.append(SimpleNamespace(tenant_id=tenant_id, document_id=document_id))

    def grant(self, *args, **kwargs) -> None:
        return None

    def search(self, principal, question, collection_id=None):
        return [
            SimpleNamespace(chunk=SimpleNamespace(document_id=d.document_id, tenant_id=d.tenant_id))
            for d in self._docs
        ]

    def answer(self, principal, question, collection_id=None):
        cites = [SimpleNamespace(document_id=d.document_id) for d in self._docs]
        return SimpleNamespace(status="ok", citations=cites, used_chunks=tuple(cites), text="leaky")


class _DenyAllStub:
    """Returns nothing for everything — a no-op probe target must FAIL its positive control."""

    def __init__(self) -> None:
        self.deletion = SimpleNamespace(
            delete=lambda tenant_id, document_id: SimpleNamespace(invalidated_cache_entries=0)
        )

    def ingest_text(self, **kwargs) -> None:
        return None

    def ingest_manufacturing(self, **kwargs) -> None:
        return None

    def grant(self, *args, **kwargs) -> None:
        return None

    def search(self, principal, question, collection_id=None):
        return []

    def answer(self, principal, question, collection_id=None):
        return SimpleNamespace(
            status="insufficient_evidence", citations=[], used_chunks=(), text=None
        )


class _PoisonedMfgStub:
    """A manufacturing system where a DRAFT poison doc is the primary citation for a high-risk answer."""

    def ingest_manufacturing(self, **kwargs) -> None:
        return None

    def grant(self, *args, **kwargs) -> None:
        return None

    def answer(self, principal, query, collection_id=None, intent_hint=None):
        return SimpleNamespace(
            high_risk=True,
            status="ok",
            safety_block_reason=None,
            citations=[SimpleNamespace(document_id="poison_draft", approval_status="draft")],
            used_chunks=("poison_draft:0",),
            text="skip lockout tagout",
        )


class _CleanMfgStub:
    """A correct manufacturing system: the APPROVED doc is the primary citation for a high-risk answer."""

    def ingest_manufacturing(self, **kwargs) -> None:
        return None

    def grant(self, *args, **kwargs) -> None:
        return None

    def answer(self, principal, query, collection_id=None, intent_hint=None):
        return SimpleNamespace(
            high_risk=True,
            status="ok",
            safety_block_reason=None,
            citations=[SimpleNamespace(document_id="approved_safe", approval_status="approved")],
            used_chunks=("approved_safe:0",),
            text="apply lockout tagout",
        )


class _DemotedMfgStub:
    """A correct manufacturing system that DEMOTES a high-risk poison scenario (the GAP-S3 fix)."""

    def ingest_manufacturing(self, **kwargs) -> None:
        return None

    def grant(self, *args, **kwargs) -> None:
        return None

    def answer(self, principal, query, collection_id=None, intent_hint=None):
        return SimpleNamespace(
            high_risk=True,
            status="insufficient_evidence",
            safety_block_reason="approved_citation_missing",
            citations=[],
            used_chunks=(),
            text=None,
        )


class TestProbeSuiteCleanSystem(unittest.TestCase):
    def test_default_suite_zero_leaks_and_executed(self) -> None:
        outcome = SecurityProbeSuite().run()  # default = real in-memory harnesses (5 probes)
        self.assertTrue(outcome.probes_executed)
        self.assertEqual(
            set(outcome.counts),
            {
                "acl_leakage",
                "deleted_reappearance",
                "tenant_isolation",
                "prompt_injection",
                "source_poisoning",
            },
        )
        for result in outcome.results:
            self.assertEqual(result.status, "ok", msg=str(result))
            self.assertEqual(result.leakage_count, 0, msg=str(result))
            self.assertTrue(result.executed)


class TestBaseProbesDetectLeak(unittest.TestCase):
    def test_leaky_system_each_base_probe_blocks(self) -> None:
        for probe in BASE_PROBES:
            with self.subTest(probe=probe.__name__):
                result = probe(make_system=_LeakyStub)
                self.assertTrue(result.executed, msg=str(result))
                self.assertEqual(result.status, "blocked", msg=str(result))
                self.assertGreaterEqual(result.leakage_count, 1, msg=str(result))


class TestBaseProbesFailClosed(unittest.TestCase):
    def test_all_deny_system_is_unavailable_not_pass(self) -> None:
        # SC-003: a no-op / all-deny implementation cannot satisfy the gate — it fails the control.
        for probe in BASE_PROBES:
            with self.subTest(probe=probe.__name__):
                result = probe(make_system=_DenyAllStub)
                self.assertEqual(result.status, "unavailable", msg=str(result))
                self.assertFalse(result.executed, msg=str(result))


class TestSourcePoisoningProbe(unittest.TestCase):
    def test_poisoned_primary_citation_is_blocked(self) -> None:
        result = source_poisoning_probe(make_system=_PoisonedMfgStub)
        self.assertEqual(result.status, "blocked", msg=str(result))
        self.assertGreaterEqual(result.leakage_count, 1)

    def test_clean_manufacturing_is_ok(self) -> None:
        result = source_poisoning_probe(make_system=_CleanMfgStub)
        self.assertEqual(result.status, "ok", msg=str(result))
        self.assertEqual(result.leakage_count, 0)

    def test_demoted_high_risk_is_ok(self) -> None:
        # The GAP-S3 fix demotes the poison scenario to insufficient_evidence — a SAFE outcome (no
        # assertion from the draft), so the probe reports no leak.
        result = source_poisoning_probe(make_system=_DemotedMfgStub)
        self.assertEqual(result.status, "ok", msg=str(result))
        self.assertEqual(result.leakage_count, 0)

    def test_no_high_risk_path_is_unavailable(self) -> None:
        result = source_poisoning_probe(make_system=_DenyAllStub)
        self.assertEqual(result.status, "unavailable", msg=str(result))
        self.assertFalse(result.executed)


class TestRunnerComputesProbes(unittest.TestCase):
    def setUp(self) -> None:
        self.sys = fresh()
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Backups run nightly at 02:00 UTC and are retained for thirty days.",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.alice = claims(T, "alice")
        self.eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {
                    "question": "when do backups run?",
                    "expected_answer": "nightly",
                    "expected_evidence": [{"document_id": "d1"}],
                }
            ],
        )

    def test_default_runner_runs_probes_and_passes_clean(self) -> None:
        run = EvaluationRunner(self.sys).run(self.eval_set, principal=self.alice, collection_id="c")
        self.assertTrue(run.probes_executed)  # SC-001 provenance
        self.assertTrue(run.probe_results)
        self.assertEqual(run.gate_result, "passed")
        self.assertTrue(run.security_checks["acl_leakage"]["passed"])
        self.assertTrue(run.security_checks["prompt_injection"]["passed"])

    def test_probe_found_leak_blocks_without_caller_counts(self) -> None:
        # The fix: a probe-detected leak blocks even though the caller passes NO counts.
        suite = SecurityProbeSuite(probes=(lambda: acl_leakage_probe(make_system=_LeakyStub),))
        run = EvaluationRunner(self.sys, probe_suite=suite).run(
            self.eval_set, principal=self.alice, collection_id="c"
        )
        self.assertEqual(run.gate_result, "blocked")
        self.assertFalse(run.security_checks["acl_leakage"]["passed"])

    def test_fail_closed_unavailable_blocks(self) -> None:
        suite = SecurityProbeSuite(probes=(lambda: acl_leakage_probe(make_system=_DenyAllStub),))
        run = EvaluationRunner(self.sys, probe_suite=suite).run(
            self.eval_set, principal=self.alice, collection_id="c"
        )
        self.assertFalse(run.probes_executed)
        self.assertEqual(run.gate_result, "blocked")

    def test_caller_count_still_blocks_merge_by_max(self) -> None:
        # D2: the protected test_eval_hard_gate behavior survives — a caller count still force-blocks.
        run = EvaluationRunner(self.sys).run(
            self.eval_set,
            principal=self.alice,
            collection_id="c",
            security_check_counts={"acl_leakage": 1},
        )
        self.assertEqual(run.gate_result, "blocked")
        self.assertEqual(run.security_checks["acl_leakage"]["count"], 1)
        self.assertFalse(run.security_checks["acl_leakage"]["passed"])


if __name__ == "__main__":
    unittest.main()
