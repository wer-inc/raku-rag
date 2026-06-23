"""P2-9 — eval run persistence: deterministic read-back, trending, and no no-op/echo loophole.

Pins that the repository genuinely persists metrics / security_checks / baseline_comparison /
gate_result / provenance and reconstructs them via the row codec (not by echoing the live object),
that results are trendable (ordered list per tenant/eval-set), and that the optional runner wiring
persists without changing eval behavior.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.eval import EvaluationRunner, EvaluationSet
from raku_rag.eval.models import EvaluationRun
from raku_rag.persistence.evaluation_runs import (
    InMemoryEvaluationRunRepository,
    evaluation_run_to_row,
    row_to_evaluation_run,
)
from tests.helpers import claims, fresh

T = "tenant_a"


def _run(
    run_id: str,
    *,
    tenant: str = T,
    eval_set_id: str = "set_1",
    created_at: str = "2026-06-21T00:00:00Z",
    **metrics,
) -> EvaluationRun:
    return EvaluationRun(
        run_id=run_id,
        eval_set_id=eval_set_id,
        tenant_id=tenant,
        status="succeeded",
        baseline=False,
        metrics={
            "recall_at_k": 1.0,
            "precision_at_k": 0.2,
            "mrr": 1.0,
            "faithfulness": 1.0,
            **metrics,
        },
        baseline_comparison={"recall_at_k": 0.0},
        security_checks={"acl_leakage": {"passed": True, "count": 0}},
        gate_result="passed",
        probe_results=(
            {
                "name": "acl_leakage",
                "executed": True,
                "leakage_count": 0,
                "status": "ok",
                "reason": "",
            },
        ),
        probes_executed=True,
        version_registry={
            "dataset_version": "dataset_test",
            "embedding_provider": "local",
            "embedding_model_version": "hashing-bow-v1",
            "embedding_dimension": 256,
            "llm_model_version": "extractive-mvp",
            "prompt_template_version": "answer-grounded-contract-v1",
            "registry_version": "eval_registry_test",
        },
        created_at=created_at,
    )


class TestRowCodec(unittest.TestCase):
    def test_round_trip_preserves_persisted_fields(self) -> None:
        run = _run("eval_1")
        back = row_to_evaluation_run(evaluation_run_to_row(run))
        self.assertEqual(back.run_id, run.run_id)
        self.assertEqual(back.tenant_id, run.tenant_id)
        self.assertEqual(back.eval_set_id, run.eval_set_id)
        self.assertEqual(back.metrics, run.metrics)
        self.assertEqual(back.security_checks, run.security_checks)
        self.assertEqual(back.baseline_comparison, run.baseline_comparison)
        self.assertEqual(back.gate_result, run.gate_result)
        self.assertEqual(back.probes_executed, run.probes_executed)
        self.assertEqual(back.probe_results, run.probe_results)
        self.assertEqual(back.version_registry, run.version_registry)


class TestInMemoryRepository(unittest.TestCase):
    def test_save_then_get_reads_back_deterministically(self) -> None:
        repo = InMemoryEvaluationRunRepository()
        run = _run("eval_1")
        repo.save(run)
        got = repo.get(T, "eval_1")
        self.assertIsNotNone(got)
        self.assertEqual(got.metrics, run.metrics)
        self.assertEqual(got.security_checks, run.security_checks)
        self.assertEqual(got.gate_result, "passed")
        self.assertTrue(got.probes_executed)
        self.assertEqual(got.version_registry["dataset_version"], "dataset_test")

    def test_persistence_is_a_copy_not_a_reference(self) -> None:
        # No-op/echo loophole guard: mutating the original after save must NOT change the stored row,
        # and get() must return a distinct reconstructed object (round-trip), not the live one.
        repo = InMemoryEvaluationRunRepository()
        run = _run("eval_1")
        repo.save(run)
        run.metrics["recall_at_k"] = 0.0  # mutate the original's dict after persisting
        got = repo.get(T, "eval_1")
        self.assertEqual(
            got.metrics["recall_at_k"], 1.0, "stored row must be a copy, not a reference"
        )
        self.assertIsNot(got, run)

    def test_missing_run_returns_none(self) -> None:
        self.assertIsNone(InMemoryEvaluationRunRepository().get(T, "nope"))

    def test_list_runs_is_trendable_in_order(self) -> None:
        repo = InMemoryEvaluationRunRepository()
        repo.save(_run("eval_a", created_at="2026-06-21T01:00:00Z", recall_at_k=1.0))
        repo.save(_run("eval_c", created_at="2026-06-21T03:00:00Z", recall_at_k=0.8))
        repo.save(_run("eval_b", created_at="2026-06-21T02:00:00Z", recall_at_k=0.9))
        runs = repo.list_runs(T, eval_set_id="set_1")
        self.assertEqual([r.run_id for r in runs], ["eval_a", "eval_b", "eval_c"])
        # distinct values preserved across releases → a downward trend is visible
        self.assertEqual([r.metrics["recall_at_k"] for r in runs], [1.0, 0.9, 0.8])

    def test_list_runs_isolates_tenant(self) -> None:
        repo = InMemoryEvaluationRunRepository()
        repo.save(_run("eval_a", tenant="tenant_a"))
        repo.save(_run("eval_b", tenant="tenant_b"))
        self.assertEqual([r.run_id for r in repo.list_runs("tenant_a")], ["eval_a"])
        self.assertEqual([r.run_id for r in repo.list_runs("tenant_b")], ["eval_b"])


class TestRunnerPersistenceWiring(unittest.TestCase):
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
                {"question": "when do backups run?", "expected_evidence": [{"document_id": "d1"}]}
            ],
        )

    def test_runner_with_repository_persists_run(self) -> None:
        repo = InMemoryEvaluationRunRepository()
        run = EvaluationRunner(self.sys, run_repository=repo).run(
            self.eval_set, principal=self.alice, collection_id="c"
        )
        stored = repo.get(T, run.run_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.gate_result, run.gate_result)
        self.assertEqual(stored.metrics["recall_at_k"], run.metrics["recall_at_k"])
        self.assertTrue(stored.probes_executed)
        self.assertEqual(stored.version_registry["dataset_version"], self.eval_set.dataset_version)
        self.assertEqual(stored.version_registry["embedding_model_version"], "hashing-bow-v1")
        self.assertEqual(stored.version_registry["llm_model_version"], "extractive-mvp")

    def test_runner_without_repository_is_unchanged(self) -> None:
        # Existing behavior: no repository → no persistence, run still produced normally.
        runner = EvaluationRunner(self.sys)
        self.assertIsNone(runner.run_repository)
        run = runner.run(self.eval_set, principal=self.alice, collection_id="c")
        self.assertEqual(run.gate_result, "passed")


if __name__ == "__main__":
    unittest.main()
