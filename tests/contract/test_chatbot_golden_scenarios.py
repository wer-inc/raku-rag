from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "demo" / "chatbot_golden_scenarios.py"
DATASET = ROOT / "scripts" / "demo" / "chatbot_golden_scenarios.json"
V2_DATASET = ROOT / "scripts" / "demo" / "chatbot_quality_v2_scenarios.json"
EXPANDED_V2_DATASET = ROOT / "scripts" / "demo" / "chatbot_quality_v2_expanded_scenarios.json"


def _load_runner():
    spec = importlib.util.spec_from_file_location("chatbot_golden_scenarios", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestChatbotGoldenScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = _load_runner()
        self.dataset = json.loads(DATASET.read_text(encoding="utf-8"))

    def test_dataset_is_valid_and_representative(self) -> None:
        self.runner.validate_dataset(self.dataset)
        scenarios = self.dataset["scenarios"]
        self.assertGreaterEqual(len(scenarios), 16)
        categories = {scenario["category"] for scenario in scenarios}
        self.assertIn("grounded_lookup", categories)
        self.assertIn("approved_high_risk_procedure", categories)
        self.assertIn("troubleshooting", categories)
        self.assertIn("safety_refusal", categories)
        self.assertIn("security_refusal", categories)

    def test_v2_dataset_is_valid_and_broader_than_smoke(self) -> None:
        dataset = json.loads(V2_DATASET.read_text(encoding="utf-8"))

        self.runner.validate_dataset(dataset)

        self.assertEqual(dataset["schema_version"], "chatbot-golden-scenarios/v2")
        self.assertEqual(dataset["dataset_id"], "chatbot_quality_v2")
        self.assertGreaterEqual(len(dataset["scenarios"]), 30)
        categories = {scenario["category"] for scenario in dataset["scenarios"]}
        self.assertIn("ambiguous_clarification", categories)
        self.assertIn("grounded_lookup", categories)
        self.assertIn("approved_high_risk_procedure", categories)
        self.assertIn("troubleshooting", categories)
        self.assertIn("safety_refusal", categories)
        self.assertIn("security_refusal", categories)

    def test_expanded_v2_dataset_is_valid_and_sme_review_pending(self) -> None:
        dataset = json.loads(EXPANDED_V2_DATASET.read_text(encoding="utf-8"))

        self.runner.validate_dataset(dataset)

        self.assertEqual(dataset["schema_version"], "chatbot-golden-scenarios/v2")
        self.assertEqual(dataset["dataset_id"], "chatbot_quality_v2_expanded")
        self.assertGreaterEqual(len(dataset["scenarios"]), 120)
        self.assertEqual(dataset["sme_review_status"], "pending")
        self.assertIs(
            dataset["generation_policy"]["generated_variants_are_acceptance_gate"],
            False,
        )
        self.assertIs(
            dataset["generation_policy"]["requires_sme_review_before_paid_pilot_gate"],
            True,
        )
        categories = {scenario["category"] for scenario in dataset["scenarios"]}
        self.assertIn("ambiguous_clarification", categories)
        self.assertIn("grounded_lookup", categories)
        self.assertIn("approved_high_risk_procedure", categories)
        self.assertIn("troubleshooting", categories)
        self.assertIn("safety_refusal", categories)
        self.assertIn("security_refusal", categories)

        generated = [
            scenario
            for scenario in dataset["scenarios"]
            if scenario.get("review_status") == "pending_sme_review"
        ]
        self.assertGreaterEqual(len(generated), 80)
        self.assertTrue(all(scenario.get("source_scenario_id") for scenario in generated))
        self.assertTrue(
            all("needs_sme_review" in (scenario.get("tags") or []) for scenario in generated)
        )

    def test_policy_payload_matches_internal_collection_policy(self) -> None:
        policy_id, payload = self.runner.policy_payload("manuals", self.dataset)

        self.assertEqual(policy_id, "chat-internal:manuals")
        self.assertEqual(payload["source_id"], "")
        self.assertEqual(payload["collection_id"], "manuals")
        self.assertEqual(payload["exposure_mode"], "internal_authenticated")
        self.assertEqual(payload["allowed_channels"], ["web_chat"])
        self.assertEqual(payload["allowed_intents"], ["rag_question"])
        self.assertIs(payload["require_approved_effective"], True)
        self.assertIs(payload["allow_obsolete_primary_evidence"], False)

    def test_policy_payload_tracks_collection_override_for_default_policy_id(self) -> None:
        policy_id, payload = self.runner.policy_payload("faq", self.dataset)

        self.assertEqual(policy_id, "chat-internal:faq")
        self.assertEqual(payload["policy_id"], "chat-internal:faq")
        self.assertEqual(payload["collection_id"], "faq")

    def test_scenarios_with_defaults_applies_dataset_thresholds(self) -> None:
        dataset = {
            "default_min_answer_chars": 123,
            "default_min_citations": 2,
            "scenarios": [
                {
                    "id": "a",
                    "category": "grounded_lookup",
                    "question": "q",
                    "expected_behavior": "answer",
                    "required_citations": ["doc"],
                },
                {
                    "id": "b",
                    "category": "safety_refusal",
                    "question": "q",
                    "expected_behavior": "handoff",
                },
            ],
        }

        scenarios = self.runner.scenarios_with_defaults(dataset)

        self.assertEqual(scenarios[0]["min_answer_chars"], 123)
        self.assertEqual(scenarios[0]["min_citations"], 2)
        self.assertNotIn("min_answer_chars", scenarios[1])

    def test_scenarios_with_defaults_applies_quick_reply_defaults(self) -> None:
        dataset = {
            "default_min_answer_chars": 123,
            "default_min_citations": 2,
            "default_required_sections": [{"label": "根拠", "terms": ["根拠"]}],
            "scenarios": [
                {
                    "id": "a",
                    "category": "grounded_lookup",
                    "question": "q",
                    "expected_behavior": "answer",
                    "expected_document_ids": ["doc-a"],
                    "quick_reply_checks": [{"value": "criteria_table", "required_terms": ["25"]}],
                }
            ],
        }

        scenarios = self.runner.scenarios_with_defaults(dataset)
        check = scenarios[0]["quick_reply_checks"][0]

        self.assertEqual(check["expected_behavior"], "answer")
        self.assertEqual(check["min_answer_chars"], 123)
        self.assertEqual(check["min_citations"], 2)
        self.assertEqual(check["expected_document_ids"], ["doc-a"])
        self.assertEqual(check["required_sections"], [{"label": "根拠", "terms": ["根拠"]}])

    def test_answer_evaluator_catches_thin_answers(self) -> None:
        scenario = {
            "id": "thin",
            "category": "grounded_lookup",
            "expected_behavior": "answer",
            "required_citations": ["doc-a"],
            "required_terms": ["25", "95"],
            "min_answer_chars": 80,
        }
        response = {
            "assistant_message": {
                "ai_action": "answer_with_citations",
                "message": "25です。",
                "citations": [{"document_id": "doc-a"}],
            },
            "rag": {"answerable": True},
        }

        result = self.runner.evaluate_response(scenario, response)

        self.assertFalse(result.passed)
        self.assertTrue(any("answer too thin" in failure for failure in result.failures))
        self.assertTrue(any("95" in failure for failure in result.failures))
        self.assertIn("answer_composition", result.failure_kinds)
        self.assertFalse(result.required_terms_hit)

    def test_answer_evaluator_accepts_grounded_complete_answer(self) -> None:
        scenario = {
            "id": "complete",
            "category": "grounded_lookup",
            "expected_behavior": "answer",
            "required_citations": ["doc-a"],
            "required_terms": ["25", "95"],
            "min_answer_chars": 20,
        }
        response = {
            "assistant_message": {
                "ai_action": "answer_with_citations",
                "message": "M8は25 N.m、M16は95 N.mです。承認済み文書に基づきます。",
                "citations": [{"document_id": "doc-a"}],
            },
            "rag": {"answerable": True},
        }

        result = self.runner.evaluate_response(scenario, response)

        self.assertTrue(result.passed, msg=result.failures)
        self.assertTrue(result.expected_citation_hit)
        self.assertTrue(result.required_terms_hit)
        self.assertTrue(result.required_sections_hit)

    def test_answer_evaluator_accepts_acceptable_alternate_citation(self) -> None:
        scenario = {
            "id": "alternate",
            "category": "grounded_lookup",
            "expected_behavior": "answer",
            "expected_document_ids": ["doc-a"],
            "acceptable_document_ids": ["doc-a-rev-b"],
            "required_terms": ["25"],
            "min_answer_chars": 10,
        }
        response = {
            "assistant_message": {
                "ai_action": "answer_with_citations",
                "message": "M8は25 N.mです。",
                "citations": [{"document_id": "doc-a-rev-b"}],
            },
            "rag": {"answerable": True},
        }

        result = self.runner.evaluate_response(scenario, response)

        self.assertTrue(result.passed, msg=result.failures)
        self.assertTrue(result.expected_citation_hit)

    def test_retrieval_diagnostic_reports_recall_mrr_without_raw_text(self) -> None:
        scenario = {
            "id": "retrieval",
            "category": "grounded_lookup",
            "expected_behavior": "answer",
            "expected_document_ids": ["doc-a"],
            "acceptable_document_ids": ["doc-a-v2"],
        }
        response = {
            "results": [
                {"document_id": "doc-x", "text": "raw private context must not be copied"},
                {"document_id": "doc-a-v2", "text": "another raw chunk"},
                {"document_id": "doc-a-v2", "text": "duplicate chunk"},
            ],
            "correlation_id": "search-1",
        }

        diagnostic = self.runner.evaluate_retrieval_diagnostic(scenario, response, top_k=10)

        self.assertTrue(diagnostic["hit"])
        self.assertEqual(diagnostic["first_hit_rank"], 2)
        self.assertEqual(diagnostic["reciprocal_rank"], 0.5)
        self.assertEqual(diagnostic["top_document_ids"], ["doc-x", "doc-a-v2"])
        self.assertNotIn("raw private context", json.dumps(diagnostic, ensure_ascii=False))

    def test_retrieval_diagnostic_summary_reports_misses(self) -> None:
        hit = self.runner.evaluate_response(
            {
                "id": "hit",
                "category": "grounded_lookup",
                "expected_behavior": "answer",
                "expected_document_ids": ["doc-a"],
                "min_answer_chars": 1,
            },
            {
                "assistant_message": {
                    "ai_action": "answer_with_citations",
                    "message": "ok",
                    "citations": [{"document_id": "doc-a"}],
                },
                "rag": {"answerable": True},
            },
            retrieval_diagnostic={
                "enabled": True,
                "top_k": 10,
                "expected_document_ids": ["doc-a"],
                "acceptable_document_ids": [],
                "hit": True,
                "reciprocal_rank": 1.0,
            },
        )
        miss = self.runner.evaluate_response(
            {
                "id": "miss",
                "category": "grounded_lookup",
                "expected_behavior": "answer",
                "expected_document_ids": ["doc-b"],
                "min_answer_chars": 1,
            },
            {
                "assistant_message": {
                    "ai_action": "answer_with_citations",
                    "message": "ok",
                    "citations": [{"document_id": "doc-x"}],
                },
                "rag": {"answerable": True},
            },
            retrieval_diagnostic={
                "enabled": True,
                "top_k": 10,
                "expected_document_ids": ["doc-b"],
                "acceptable_document_ids": [],
                "hit": False,
                "reciprocal_rank": 0.0,
                "miss_reason": "expected_document_not_in_top_k",
            },
        )

        summary = self.runner.summarize_results([hit, miss])

        self.assertEqual(summary["retrieval_diagnostics"]["checked_count"], 2)
        self.assertEqual(summary["retrieval_diagnostics"]["recall_at_k"], 0.5)
        self.assertEqual(summary["retrieval_diagnostics"]["mrr"], 0.5)
        self.assertEqual(
            summary["retrieval_diagnostics"]["miss_reasons"],
            {"expected_document_not_in_top_k": 1},
        )

    def test_answer_evaluator_catches_missing_structured_sections(self) -> None:
        scenario = {
            "id": "sections",
            "category": "approved_high_risk_procedure",
            "expected_behavior": "answer",
            "required_citations": ["doc-a"],
            "required_terms": ["25"],
            "required_sections": [
                {"label": "結論", "terms": ["結論"]},
                {"label": "注意", "terms": ["注意", "警告"]},
            ],
            "min_answer_chars": 10,
        }
        response = {
            "assistant_message": {
                "ai_action": "answer_with_citations",
                "message": "結論: M8は25 N.mです。",
                "citations": [{"document_id": "doc-a"}],
            },
            "rag": {"answerable": True},
        }

        result = self.runner.evaluate_response(scenario, response)

        self.assertFalse(result.passed)
        self.assertFalse(result.required_sections_hit)
        self.assertIn("answer_composition", result.failure_kinds)
        self.assertTrue(any("注意" in failure for failure in result.failures))

    def test_handoff_evaluator_accepts_safe_refusal(self) -> None:
        scenario = {
            "id": "refusal",
            "category": "safety_refusal",
            "expected_behavior": "handoff",
            "expected_no_answer_reasons": ["insufficient_evidence"],
        }
        response = {
            "assistant_message": {
                "ai_action": "handoff",
                "message": "承認済みの根拠だけでは回答を確定できません。",
                "citations": [],
            },
            "rag": {"answerable": False, "no_answer_reason": "insufficient_evidence"},
        }

        result = self.runner.evaluate_response(scenario, response)

        self.assertTrue(result.passed, msg=result.failures)

    def test_handoff_evaluator_rejects_missing_expected_no_answer_reason(self) -> None:
        scenario = {
            "id": "refusal-missing-reason",
            "category": "safety_refusal",
            "expected_behavior": "handoff",
            "expected_no_answer_reasons": ["insufficient_evidence"],
        }
        response = {
            "assistant_message": {
                "ai_action": "handoff",
                "message": "承認済みの根拠だけでは回答を確定できません。",
                "citations": [],
            },
            "rag": {"answerable": False},
        }

        result = self.runner.evaluate_response(scenario, response)

        self.assertFalse(result.passed)
        self.assertIn("safety_refusal", result.failure_kinds)
        self.assertTrue(any("missing no_answer_reason" in failure for failure in result.failures))

    def test_clarification_evaluator_requires_ask_clarification(self) -> None:
        scenario = {
            "id": "clarify",
            "category": "ambiguous_clarification",
            "expected_behavior": "clarification",
        }
        response = {
            "assistant_message": {
                "ai_action": "answer_with_citations",
                "message": "たぶんE-152です。",
                "citations": [{"document_id": "doc-a"}],
            },
            "rag": {"answerable": True},
        }

        result = self.runner.evaluate_response(scenario, response)

        self.assertFalse(result.passed)
        self.assertIn("clarification", result.failure_kinds)

    def test_run_payload_includes_dataset_profile_and_readiness(self) -> None:
        scenario = {
            "id": "complete",
            "category": "grounded_lookup",
            "expected_behavior": "answer",
            "required_citations": ["doc-a"],
            "required_terms": ["25"],
            "min_answer_chars": 20,
        }
        response = {
            "assistant_message": {
                "ai_action": "answer_with_citations",
                "message": "M8は25 N.mです。承認済み文書に基づきます。",
                "citations": [{"document_id": "doc-a"}],
            },
            "rag": {"answerable": True},
            "correlation_id": "corr-1",
        }
        result = self.runner.evaluate_response(scenario, response)
        dataset = {
            "schema_version": "chatbot-golden-scenarios/v2",
            "dataset_id": "unit",
            "dataset_version": "2026-06-30",
            "readiness_thresholds": {
                "expected_citation_hit_rate": 1.0,
                "completeness_hit_rate": 1.0,
            },
        }
        profile = {
            "profile_name": "unit-profile",
            "embedding_provider": "hashing",
            "answer_profile": "extractive",
            "reranker": "none",
        }

        payload = self.runner.build_run_payload(
            dataset=dataset,
            profile=profile,
            collection_id="manuals",
            results=[result],
        )

        self.assertEqual(payload["dataset"]["dataset_id"], "unit")
        self.assertEqual(payload["profile"]["profile_name"], "unit-profile")
        self.assertEqual(payload["summary"]["expected_citation_hit_rate"], 1.0)
        self.assertEqual(payload["summary"]["completeness_hit_rate"], 1.0)
        self.assertTrue(payload["readiness"]["ready"])

    def test_readiness_summary_separates_refusal_and_clarification_rates(self) -> None:
        refusal = self.runner.evaluate_response(
            {
                "id": "refusal",
                "category": "safety_refusal",
                "expected_behavior": "handoff",
                "expected_no_answer_reasons": ["insufficient_evidence"],
            },
            {
                "assistant_message": {
                    "ai_action": "handoff",
                    "message": "承認済みの根拠だけでは回答を確定できません。",
                    "citations": [],
                },
                "rag": {"answerable": False, "no_answer_reason": "insufficient_evidence"},
            },
        )
        clarification = self.runner.evaluate_response(
            {
                "id": "clarify",
                "category": "ambiguous_clarification",
                "expected_behavior": "clarification",
            },
            {
                "assistant_message": {
                    "ai_action": "answer_with_citations",
                    "message": "E-152 の手順です。",
                    "citations": [{"document_id": "doc-a"}],
                },
                "rag": {"answerable": True},
            },
        )
        dataset = {
            "readiness_thresholds": {
                "refusal_pass_rate": 1.0,
                "clarification_pass_rate": 1.0,
            }
        }

        readiness = self.runner.readiness_summary([refusal, clarification], dataset)

        self.assertEqual(readiness["measured"]["refusal_pass_rate"], 1.0)
        self.assertEqual(readiness["measured"]["clarification_pass_rate"], 0.0)
        self.assertTrue(readiness["threshold_results"]["refusal_pass_rate"])
        self.assertFalse(readiness["threshold_results"]["clarification_pass_rate"])
        self.assertFalse(readiness["ready"])

    def test_run_scenario_results_checks_quick_reply_followups(self) -> None:
        calls = []

        def fake_http_json(method, _base_url, path, **kwargs):
            calls.append((method, path, kwargs.get("body")))
            if path == "/chat/sessions":
                return {
                    "session_id": "sess_1",
                    "assistant_message": {
                        "ai_action": "answer_with_citations",
                        "message": "結論: M8 は 25 N.m です。\n\n根拠:\n- doc-a",
                        "citations": [{"document_id": "doc-a"}],
                        "quick_replies": [{"label": "判断基準を表にする", "value": "criteria_table"}],
                    },
                    "rag": {"answerable": True},
                }
            self.assertEqual(path, "/chat/sessions/sess_1/messages")
            return {
                "assistant_message": {
                    "ai_action": "answer_with_citations",
                    "message": "結論: 同じ根拠で詳しく整理します。\n\n根拠:\n- doc-a",
                    "citations": [{"document_id": "doc-a"}],
                },
                "rag": {"answerable": True},
            }

        self.runner.http_json = fake_http_json
        scenario = {
            "id": "complete",
            "category": "grounded_lookup",
            "question": "M8 のトルクは？",
            "expected_behavior": "answer",
            "expected_document_ids": ["doc-a"],
            "required_sections": [{"label": "根拠", "terms": ["根拠"]}],
            "min_answer_chars": 10,
            "quick_reply_checks": [
                {
                    "value": "criteria_table",
                    "expected_behavior": "answer",
                    "expected_document_ids": ["doc-a"],
                    "required_sections": [{"label": "根拠", "terms": ["根拠"]}],
                    "min_answer_chars": 10,
                }
            ],
        }

        results = self.runner.run_scenario_results(
            "http://api/v1",
            "token",
            "api-key",
            scenario,
            collection_id="manuals",
            timeout=1,
        )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.passed for result in results), msg=results[1].failures)
        self.assertEqual(results[1].turn_type, "quick_reply")
        self.assertEqual(results[1].parent_scenario_id, "complete")
        self.assertEqual(results[1].quick_reply_value, "criteria_table")
        self.assertEqual(calls[1][2]["message"], "criteria_table")

    def test_quick_reply_check_can_target_a_different_collection_for_scope_carry_checks(self) -> None:
        calls = []

        def fake_http_json(method, _base_url, path, **kwargs):
            calls.append((method, path, kwargs.get("body")))
            if path == "/chat/sessions":
                return {
                    "session_id": "sess_1",
                    "assistant_message": {
                        "ai_action": "answer_with_citations",
                        "message": "結論: M8 は 25 N.m です。\n\n根拠:\n- doc-a",
                        "citations": [{"document_id": "doc-a"}],
                    },
                    "rag": {"answerable": True},
                }
            self.assertEqual(path, "/chat/sessions/sess_1/messages")
            return {
                "assistant_message": {
                    "ai_action": "handoff",
                    "message": "承認済みの根拠だけでは回答を確定できません。",
                    "citations": [],
                },
                "rag": {"answerable": False, "no_answer_reason": "source_not_enabled_for_chatbot"},
            }

        self.runner.http_json = fake_http_json
        scenario = {
            "id": "coreference-scope-carry",
            "category": "grounded_lookup",
            "question": "M8 のトルクは？",
            "expected_behavior": "answer",
            "expected_document_ids": ["doc-a"],
            "min_answer_chars": 10,
            "quick_reply_checks": [
                {
                    # A free-text follow-up, not a canned quick-reply value -- require_offered=False
                    # skips the "was this value offered as a button" check accordingly.
                    "value": "その基準は？",
                    "require_offered": False,
                    "collection_id": "restricted",
                    "expected_behavior": "handoff",
                    "expected_no_answer_reasons": ["source_not_enabled_for_chatbot"],
                }
            ],
        }

        results = self.runner.run_scenario_results(
            "http://api/v1",
            "token",
            "api-key",
            scenario,
            collection_id="manuals",
            timeout=1,
        )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.passed for result in results), msg=results[1].failures)
        self.assertEqual(calls[0][2]["collection_id"], "manuals")
        self.assertEqual(calls[1][2]["collection_id"], "restricted")

    def test_run_scenario_results_can_attach_retrieval_diagnostics(self) -> None:
        calls = []

        def fake_http_json(method, _base_url, path, **kwargs):
            calls.append((method, path, kwargs.get("body")))
            if path == "/search":
                return {
                    "results": [
                        {"document_id": "doc-x", "text": "do not persist this text"},
                        {"document_id": "doc-a", "text": "do not persist this either"},
                    ],
                    "correlation_id": "search-1",
                }
            self.assertEqual(path, "/chat/sessions")
            return {
                "session_id": "sess_1",
                "assistant_message": {
                    "ai_action": "answer_with_citations",
                    "message": "結論: M8 は 25 N.m です。\n\n根拠:\n- doc-a",
                    "citations": [{"document_id": "doc-a"}],
                },
                "rag": {"answerable": True},
            }

        self.runner.http_json = fake_http_json
        scenario = {
            "id": "complete",
            "category": "grounded_lookup",
            "question": "M8 のトルクは？",
            "expected_behavior": "answer",
            "expected_document_ids": ["doc-a"],
            "required_sections": [{"label": "根拠", "terms": ["根拠"]}],
            "min_answer_chars": 10,
        }

        results = self.runner.run_scenario_results(
            "http://api/v1",
            "token",
            "api-key",
            scenario,
            collection_id="manuals",
            timeout=1,
            retrieval_diagnostics=True,
            retrieval_top_k=3,
        )

        self.assertEqual(calls[0][1], "/search")
        self.assertEqual(calls[0][2]["top_k"], 3)
        self.assertEqual(calls[1][1], "/chat/sessions")
        self.assertTrue(results[0].passed, msg=results[0].failures)
        self.assertEqual(results[0].retrieval_diagnostic["first_hit_rank"], 2)
        self.assertNotIn(
            "do not persist",
            json.dumps(results[0].retrieval_diagnostic, ensure_ascii=False),
        )

    def test_quick_reply_check_fails_when_value_was_not_offered(self) -> None:
        self.runner.http_json = lambda *_args, **_kwargs: {
            "session_id": "sess_1",
            "assistant_message": {
                "ai_action": "answer_with_citations",
                "message": "結論: M8 は 25 N.m です。\n\n根拠:\n- doc-a",
                "citations": [{"document_id": "doc-a"}],
                "quick_replies": [{"label": "根拠を確認する", "value": "evidence"}],
            },
            "rag": {"answerable": True},
        }
        scenario = {
            "id": "complete",
            "category": "grounded_lookup",
            "question": "M8 のトルクは？",
            "expected_behavior": "answer",
            "expected_document_ids": ["doc-a"],
            "min_answer_chars": 10,
            "quick_reply_checks": [
                {
                    "value": "criteria_table",
                    "expected_behavior": "answer",
                    "expected_document_ids": ["doc-a"],
                    "min_answer_chars": 10,
                }
            ],
        }

        results = self.runner.run_scenario_results(
            "http://api/v1",
            "token",
            "api-key",
            scenario,
            collection_id="manuals",
            timeout=1,
        )

        self.assertEqual(len(results), 2)
        self.assertFalse(results[1].passed)
        self.assertEqual(results[1].failure_kinds, ("followup",))
        self.assertIn("was not offered", results[1].failures[0])


if __name__ == "__main__":
    unittest.main()
