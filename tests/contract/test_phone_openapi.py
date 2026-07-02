"""T012 — /v1/phone/* OpenAPI contract coverage (022 contracts/phone-rag-openapi.md)."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "apps/api/scripts/export-openapi.cjs"

PHONE_PATHS = {
    "/phone/calls/simulate": {"post"},
    "/phone/calls": {"get"},
    "/phone/calls/{call_id}": {"get"},
    "/phone/calls/{call_id}/turns": {"post"},
    "/phone/calls/{call_id}/quality-evaluations": {"get", "post"},
    "/phone/metrics": {"get"},
    "/phone/retention-policy": {"get"},
    "/phone/calls/export": {"post"},
    "/phone/calls/{call_id}/delete-request": {"post"},
    "/phone/handoffs/{handoff_package_id}": {"get"},
    "/phone/handoffs/{handoff_package_id}/accept": {"post"},
    "/phone/scenarios": {"get", "post"},
    "/phone/scenarios/{scenario_id}/versions/{version_id}": {"put"},
    "/phone/scenarios/{scenario_id}/versions/{version_id}/test": {"post"},
    "/phone/scenarios/{scenario_id}/versions/{version_id}/{action}": {"post"},
    "/phone/scenarios/{scenario_id}/rollback": {"post"},
}

PHONE_SCHEMAS = (
    "PhoneCitationRef",
    "PhoneSimulateCallRequest",
    "PhoneSimulateCallResponse",
    "PhoneTurnRequest",
    "PhoneTurnResponse",
    "PhoneCallListResponse",
    "PhoneCallDetailResponse",
    "PhoneHandoffPackage",
    "PhoneHandoffAcceptResponse",
    "PhoneScenarioListResponse",
    "PhoneScenarioMutationResponse",
    "PhoneScenarioPreviewResponse",
    "PhoneQualityEvaluationRequest",
    "PhoneQualityEvaluationResponse",
    "PhoneQualityEvaluationListResponse",
    "PhoneMetricsResponse",
    "PhoneRetentionPolicyResponse",
    "PhoneExportResponse",
    "PhoneDeleteRequestResponse",
)


def _load_openapi() -> dict[str, Any]:
    raw = subprocess.check_output(["node", str(EXPORTER)], cwd=ROOT, text=True)
    return json.loads(raw)


class PhoneOpenApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = _load_openapi()

    def test_phone_paths_are_documented_with_expected_methods(self) -> None:
        for path, methods in PHONE_PATHS.items():
            with self.subTest(path=path):
                self.assertIn(path, self.doc["paths"], f"{path} missing from OpenAPI document")
                documented = set(self.doc["paths"][path]) & {"get", "post", "put", "delete"}
                self.assertEqual(documented, methods)

    def test_phone_schemas_are_defined(self) -> None:
        schemas = self.doc["components"]["schemas"]
        for name in PHONE_SCHEMAS:
            with self.subTest(schema=name):
                self.assertIn(name, schemas)

    def test_phone_routes_require_auth(self) -> None:
        for path, methods in PHONE_PATHS.items():
            for method in methods:
                with self.subTest(path=path, method=method):
                    operation = self.doc["paths"][path][method]
                    self.assertTrue(
                        operation.get("security"),
                        f"{method.upper()} {path} must require signed auth context",
                    )

    def test_citation_ref_carries_traceability_fields(self) -> None:
        schema = self.doc["components"]["schemas"]["PhoneCitationRef"]
        for field in ("source_id", "document_id", "chunk_id", "retrieval_score"):
            self.assertIn(field, schema["required"])
        self.assertIn("version", schema["properties"])
        self.assertIn("approval_status", schema["properties"])

    def test_turn_response_documents_safety_and_handoff(self) -> None:
        schema = self.doc["components"]["schemas"]["PhoneTurnResponse"]
        self.assertIn("safety", schema["required"])
        self.assertIn("handoff", schema["properties"])
        self.assertIn("citations", schema["properties"])

    def test_terminal_turn_conflict_is_documented(self) -> None:
        responses = self.doc["paths"]["/phone/calls/{call_id}/turns"]["post"]["responses"]
        self.assertIn("409", responses)

    def test_publish_before_approval_conflict_is_documented(self) -> None:
        action_path = "/phone/scenarios/{scenario_id}/versions/{version_id}/{action}"
        responses = self.doc["paths"][action_path]["post"]["responses"]
        self.assertIn("409", responses)


if __name__ == "__main__":
    unittest.main()
