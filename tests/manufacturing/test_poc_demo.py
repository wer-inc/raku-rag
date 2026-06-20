"""T072 — PoC demo logic gate coverage (FR-MFG-027 "minimum demo").

The PoC at ``poc-ui/server.py`` builds a SEEDED ``ManufacturingSystem`` (via ``DemoApp``) and exposes
the request logic as PURE methods (``DemoApp.answer(payload) -> dict`` ...) so it can be exercised
WITHOUT binding a socket. This test loads that module by file path (the ``poc-ui`` directory has a
hyphen and is intentionally outside the package / test-discovery path) and asserts the demo actually
DEMONSTRATES the safety behaviours through the real entrypoints:

  * a high-risk query whose only evidence is a DRAFT doc is BLOCKED with safety_block_reason and
    asserts nothing;
  * a high-risk query WITH an approved+effective citation answers, cites approval_status=approved,
    and requires on-site confirmation;
  * a normal approved answer cites an approved document;
  * an obsolete-only topic raises obsolete_warning;
  * a trouble-case search returns candidate countermeasures (Hard Rule 4);
  * a generated draft is status=draft, created_by=ai (draft-only, never auto-confirmed);
  * the KPI + safety-telemetry + state snapshot compute and the telemetry counters reflect the flow;
  * the bundled ``smoke()`` self-check passes.

This makes the demo logic gate-covered (it runs under ``scripts/gate.sh``). It does NOT bind a
socket and does NOT modify any ``src/`` module.

stdlib only.
"""
from __future__ import annotations

import importlib.util
import os
import unittest

# Load poc-ui/server.py by file path (the dir name 'poc-ui' is not a valid package name).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SERVER_PATH = os.path.join(_REPO_ROOT, "poc-ui", "server.py")


def _load_poc_module():
    spec = importlib.util.spec_from_file_location("poc_ui_server", _SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


poc = _load_poc_module()


class PocSeedTest(unittest.TestCase):
    """A freshly seeded DemoApp makes every safety behaviour reachable through the pure methods."""

    def setUp(self) -> None:
        self.demo = poc.DemoApp()

    # --- answer path: high-risk blocked (draft-only evidence) -------------------------------------
    def test_high_risk_without_approved_is_blocked(self) -> None:
        d = self.demo.answer({"query": poc.EXAMPLES["high_risk_block"]})
        self.assertTrue(d["high_risk"], "the 400V panel question must be high-risk")
        self.assertEqual(d["status"], "insufficient_evidence")
        self.assertEqual(d["safety_block_reason"], "approved_citation_missing")
        self.assertFalse(d["text"], "a blocked high-risk answer must not assert a procedure")
        self.assertEqual(d["citations"], [], "no citations are surfaced when blocked")
        self.assertEqual(d["used_chunks"], [])

    # --- answer path: high-risk OK with approved+effective evidence -------------------------------
    def test_high_risk_with_approved_effective_answers(self) -> None:
        d = self.demo.answer({"query": poc.EXAMPLES["high_risk_ok"]})
        self.assertTrue(d["high_risk"])
        self.assertEqual(d["status"], "ok")
        self.assertIsNone(d["safety_block_reason"])
        self.assertTrue(d["citations"])
        self.assertEqual(d["citations"][0]["approval_status"], "approved")
        self.assertIsNotNone(d["citations"][0]["effective_date"])
        self.assertTrue(
            d["requires_onsite_confirmation"],
            "high-risk hazardous work requires on-site confirmation",
        )

    # --- answer path: a normal approved question answers ok with an approved citation -------------
    def test_normal_approved_answer_is_cited(self) -> None:
        d = self.demo.answer({"query": poc.EXAMPLES["safe_answer"]})
        self.assertEqual(d["status"], "ok")
        self.assertTrue(d["citations"], "an approved answer must carry a citation")
        primary = d["citations"][0]
        self.assertEqual(primary["document_id"], "approved_torque")
        self.assertEqual(primary["approval_status"], "approved")
        self.assertIsNotNone(primary["effective_date"])
        self.assertIsNone(d["safety_block_reason"])

    # --- answer path: obsolete-only topic raises the warning --------------------------------------
    def test_obsolete_topic_raises_warning(self) -> None:
        d = self.demo.answer({"query": poc.EXAMPLES["obsolete_warning"]})
        self.assertTrue(
            d["obsolete_warning"], "referencing obsolete evidence must raise obsolete_warning"
        )

    def test_empty_query_is_rejected(self) -> None:
        # An empty/blank query must be rejected — either by raising or by returning an error dict
        # (tolerant of either handler style; the demo must never answer a blank query).
        try:
            result = self.demo.answer({"query": "   "})
        except (ValueError, KeyError):
            return  # rejected by raising — acceptable
        self.assertIn("error", result, "a blank query must be rejected, not answered")

    # --- search carries approval tags -------------------------------------------------------------
    def test_search_returns_approval_tagged_hits(self) -> None:
        d = self.demo.search({"query": poc.EXAMPLES["search_alarm"]})
        self.assertIn("results", d)
        self.assertTrue(
            any(r["document_id"] == "ledger_pump17" for r in d["results"]),
            "the alarm/equipment search must surface the ledger",
        )
        for r in d["results"]:
            self.assertIn("approval_status", r)

    # --- trouble cases: candidate countermeasures (Hard Rule 4) -----------------------------------
    def test_trouble_case_search_returns_candidates(self) -> None:
        d = self.demo.trouble({"query": poc.EXAMPLES["trouble"]})
        self.assertEqual(d["status"], "ok")
        match = next((m for m in d["results"] if m["trouble_case_id"] == "tc_gearbox"), None)
        self.assertIsNotNone(match, "the seeded gearbox trouble case must be found")
        self.assertIsNotNone(match["failure_mode"], "the cause must accompany the match")
        self.assertTrue(match["recurrence_prevention"])
        self.assertTrue(match["citations"], "the past case must be cited")
        all_cms = match["countermeasures"]["provisional"] + match["countermeasures"]["permanent"]
        self.assertTrue(all_cms, "the trouble case must surface countermeasures")
        for c in all_cms:
            self.assertEqual(
                c["type"], "candidate",
                "Hard Rule 4: every past-case countermeasure displays as candidate, never definitive",
            )
            self.assertTrue(c["label"], "every candidate carries a past-example label")

    # --- drafts: always draft, created_by=ai (never auto-confirmed) -------------------------------
    def test_draft_is_draft_only(self) -> None:
        d = self.demo.draft({"kind": "checklist"})
        self.assertEqual(d["status"], "draft", "AI output is always draft (Hard Rule 1)")
        self.assertEqual(d["created_by"], "ai")
        self.assertEqual(d["type"], "checklist")
        self.assertIn("approved_lockout", d["source_document_ids"])

    # --- admin views present + telemetry reflects driven flow -------------------------------------
    def test_kpi_and_telemetry_present_and_match_flow(self) -> None:
        # Drive one high-risk OK and one high-risk block so telemetry counters move.
        self.demo.answer({"query": poc.EXAMPLES["high_risk_ok"]})
        self.demo.answer({"query": poc.EXAMPLES["high_risk_block"]})

        bundle = self.demo.kpi()
        kpi = bundle["kpi"]
        tel = bundle["telemetry"]
        for key in (
            "self_resolution_rate",
            "grounded_answer_rate",
            "insufficient_evidence_rate",
            "high_risk_query_count",
            "safety_gate_block_count",
            "obsolete_document_candidates",
        ):
            self.assertIn(key, kpi, f"KPI {key!r} must be present")
        self.assertIn(
            "obsolete_coolant", kpi["obsolete_document_candidates"],
            "the seeded obsolete doc must surface as an obsolete candidate",
        )
        self.assertEqual(tel["source"], "audit_log")
        self.assertGreater(tel["high_risk_query_count"], 0)
        self.assertGreater(tel["safety_gate_block_count"], 0)
        # KPI safety counters agree with the telemetry (single source of truth).
        self.assertEqual(kpi["high_risk_query_count"], tel["high_risk_query_count"])
        self.assertEqual(kpi["safety_gate_block_count"], tel["safety_gate_block_count"])

    # --- state snapshot lists the seeded docs + governance ----------------------------------------
    def test_state_snapshot_lists_seeded_documents(self) -> None:
        s = self.demo.snapshot()
        for key in ("tenant", "collection", "documents", "kpi", "governance", "examples"):
            self.assertIn(key, s)
        doc_ids = {doc["document_id"] for doc in s["documents"]}
        self.assertIn("approved_lockout", doc_ids)
        self.assertIn("obsolete_coolant", doc_ids)
        self.assertIn("draft_panel", doc_ids)


class PocSmokeAndHtmlTest(unittest.TestCase):
    """The bundled smoke self-check passes and the inline page is self-contained."""

    def test_smoke_self_check_passes(self) -> None:
        result = poc.smoke()
        self.assertEqual(result["status"], "ok")
        self.assertIn("safety_block", result["checks"])

    def test_index_is_self_contained(self) -> None:
        html = poc.INDEX_HTML
        self.assertIn("<!doctype html>", html.lower())
        self.assertIn("/api/answer", html)
        self.assertIn("/api/trouble", html)
        self.assertIn("/api/draft", html)
        # No external network assets (the demo must run with no internet).
        self.assertNotIn('src="http', html)
        self.assertNotIn('href="http', html)


if __name__ == "__main__":
    unittest.main()
