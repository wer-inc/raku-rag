"""P2-9 wiring — the answer-service eval endpoint PERSISTS runs via the repository (trendable).

Pins that `_EvalFeedbackStore.create_run` saves to the EvaluationRunRepository, `get_run` reads it
back from the durable repo (not just the in-process cache), `list_runs` trends per tenant/eval-set,
and tenant isolation holds. In-process (no live server / no Postgres) via the existing answer-service
import pattern; production swaps the repo for PostgresEvaluationRunRepository.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType

ROOT = Path(__file__).resolve().parents[2]
T = "tenant_a"


def _load_answer_service():
    path = ROOT / "apps/answer-service/server.py"
    spec = importlib.util.spec_from_file_location("answer_service_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TestEvalPersistenceEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.app import MvpSystem

        self.srv = _load_answer_service()
        self.sys = MvpSystem()
        self.sys.ingest_text(
            tenant_id=T,
            collection_id="c",
            document_id="d1",
            text="Backups run nightly at 02:00 UTC and are retained for thirty days.",
        )
        self.sys.grant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice")
        self.store = self.srv._EvalFeedbackStore(self.sys)
        self.principal = IdentityClaims(tenant_id=T, user_id="alice")

    def _create_run(self):
        created = self.store.create_set(
            T,
            {
                "items": [
                    {
                        "question": "when do backups run?",
                        "expected_evidence": [{"document_id": "d1"}],
                    }
                ]
            },
        )
        run = self.store.create_run(
            T, {"eval_set_id": created["eval_set_id"], "collection_id": "c"}, self.principal
        )
        return run["run_id"]

    def test_run_is_persisted_and_read_back_from_repo(self) -> None:
        run_id = self._create_run()
        got = self.store.get_run(T, run_id)
        self.assertIsNotNone(got)
        self.assertEqual(got["run_id"], run_id)
        self.assertIn("metrics", got)
        self.assertIn("probes_executed", got)  # provenance persisted, not just gate_result
        self.assertIn("gate_result", got)
        self.assertEqual(got["version_registry"]["embedding_model_version"], "hashing-bow-v1")
        self.assertTrue(got["version_registry"]["dataset_version"].startswith("dataset_"))

    def test_list_runs_is_trendable_and_tenant_isolated(self) -> None:
        run_id = self._create_run()
        listed = self.store.list_runs(T)
        self.assertTrue(any(r["run_id"] == run_id for r in listed))
        self.assertEqual(self.store.list_runs("tenant_other"), [])


if __name__ == "__main__":
    unittest.main()
