from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "pilot_readiness_status.py"
    spec = importlib.util.spec_from_file_location("pilot_readiness_status", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestPilotReadinessStatus(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    def test_report_blocks_missing_or_unsigned_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specs/prod-readiness").mkdir(parents=True)
            (root / "docs/production-readiness/evidence").mkdir(parents=True)
            (root / "specs/prod-readiness/ledger.json").write_text(
                json.dumps({"units": [{"id": "P1-2", "status": "blocked-needs-infra"}]}),
                encoding="utf-8",
            )
            (root / "specs/prod-readiness/paid-pilot-gate.json").write_text(
                json.dumps(
                    {
                        "readiness_label": "paid-pilot-ready",
                        "requirements": [
                            {
                                "id": "LIVE",
                                "kind": "ledger_unit",
                                "ledger_unit": "P1-2",
                                "accepted_statuses": ["verified"],
                            },
                            {
                                "id": "SIGN",
                                "kind": "evidence_file",
                                "evidence_file": "docs/production-readiness/evidence/sign.md",
                                "accepted_statuses": ["signed"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = self.mod.build_report(repo_root=root)

            self.assertFalse(report["ready"])
            self.assertEqual(report["summary"]["blocked-needs-infra"], 1)
            self.assertEqual(report["summary"]["missing"], 1)

    def test_report_passes_when_ledger_and_evidence_statuses_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specs/prod-readiness").mkdir(parents=True)
            (root / "docs/production-readiness/evidence").mkdir(parents=True)
            (root / "specs/prod-readiness/ledger.json").write_text(
                json.dumps({"units": [{"id": "P1-2", "status": "verified"}]}),
                encoding="utf-8",
            )
            (root / "docs/production-readiness/evidence/sign.md").write_text(
                "# Signoff\n\nStatus: signed\n",
                encoding="utf-8",
            )
            (root / "specs/prod-readiness/paid-pilot-gate.json").write_text(
                json.dumps(
                    {
                        "readiness_label": "paid-pilot-ready",
                        "requirements": [
                            {
                                "id": "LIVE",
                                "kind": "ledger_unit",
                                "ledger_unit": "P1-2",
                                "accepted_statuses": ["verified"],
                            },
                            {
                                "id": "SIGN",
                                "kind": "evidence_file",
                                "evidence_file": "docs/production-readiness/evidence/sign.md",
                                "accepted_statuses": ["signed"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = self.mod.build_report(repo_root=root)
            rendered = self.mod.render_markdown(report)

            self.assertTrue(report["ready"])
            self.assertIn("paid-pilot-ready: READY", rendered)


if __name__ == "__main__":
    unittest.main()
