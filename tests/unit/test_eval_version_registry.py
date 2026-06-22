"""P2-10 — model/prompt/dataset version registry for eval reproducibility."""

from __future__ import annotations

from dataclasses import replace
import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.eval import (
    EvaluationBaseline,
    EvaluationRunner,
    EvaluationSet,
    evaluate_baseline_gate,
)
from tests.helpers import claims, fresh

T = "tenant_a"


class TestEvalVersionRegistry(unittest.TestCase):
    def test_dataset_version_changes_when_dataset_content_changes(self) -> None:
        first = EvaluationSet.register(
            tenant_id=T,
            items=[{"question": "when?", "expected_evidence": [{"document_id": "d1"}]}],
        )
        second = EvaluationSet.register(
            tenant_id=T,
            items=[{"question": "where?", "expected_evidence": [{"document_id": "d1"}]}],
        )
        self.assertNotEqual(first.dataset_version, second.dataset_version)
        self.assertTrue(first.dataset_version.startswith("dataset_"))

    def test_runner_records_model_prompt_dataset_versions(self) -> None:
        sys = fresh()
        sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Backups run nightly at 02:00 UTC.",
        )
        sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {"question": "when do backups run?", "expected_evidence": [{"document_id": "d1"}]}
            ],
        )
        run = EvaluationRunner(sys).run(eval_set, principal=claims(T, "alice"), collection_id="c")

        self.assertEqual(run.version_registry["dataset_version"], eval_set.dataset_version)
        self.assertEqual(run.version_registry["embedding_provider"], "local")
        self.assertEqual(run.version_registry["embedding_model_version"], "hashing-bow-v1")
        self.assertEqual(run.version_registry["embedding_dimension"], 256)
        self.assertEqual(run.version_registry["llm_model_version"], "extractive-mvp")
        self.assertEqual(
            run.version_registry["prompt_template_version"], "answer-grounded-contract-v1"
        )
        self.assertTrue(str(run.version_registry["registry_version"]).startswith("eval_registry_"))

    def test_baseline_gate_blocks_version_registry_mismatch(self) -> None:
        sys = fresh()
        sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Backups run nightly at 02:00 UTC.",
        )
        sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        eval_set = EvaluationSet.register(
            tenant_id=T,
            items=[
                {"question": "when do backups run?", "expected_evidence": [{"document_id": "d1"}]}
            ],
        )
        run = EvaluationRunner(sys).run(eval_set, principal=claims(T, "alice"), collection_id="c")
        baseline = EvaluationBaseline(
            metrics=run.metrics,
            version_registry=dict(run.version_registry),
        )

        self.assertTrue(evaluate_baseline_gate(run, baseline).passed)
        drifted = replace(
            baseline,
            version_registry={**baseline.version_registry, "prompt_template_version": "old"},
        )
        result = evaluate_baseline_gate(run, drifted)
        self.assertFalse(result.passed)
        self.assertTrue(
            any(
                "version_registry.prompt_template_version" in failure for failure in result.failures
            ),
            msg=str(result.failures),
        )


if __name__ == "__main__":
    unittest.main()
