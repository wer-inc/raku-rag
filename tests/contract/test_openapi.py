from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "apps/api/scripts/export-openapi.cjs"


def _load_openapi() -> dict[str, Any]:
    raw = subprocess.check_output(["node", str(EXPORTER)], cwd=ROOT, text=True)
    return json.loads(raw)


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _resolve_ref(doc: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise AssertionError(f"external OpenAPI refs are not allowed in this contract: {ref}")
    node: Any = doc
    for part in ref[2:].split("/"):
        node = node[part]
    return node


class OpenApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = _load_openapi()

    def test_document_has_openapi_top_level_shape(self) -> None:
        self.assertEqual(self.doc["openapi"], "3.0.3")
        self.assertIn("info", self.doc)
        self.assertIn("servers", self.doc)
        self.assertIn("components", self.doc)
        self.assertIn("paths", self.doc)
        self.assertEqual(self.doc["servers"][0]["url"], "/v1")
        self.assertIn("ApiVersion", self.doc["components"]["headers"])
        self.assertIn("Deprecation", self.doc["components"]["headers"])
        self.assertIn("Sunset", self.doc["components"]["headers"])

    def test_every_reference_resolves_inside_the_document(self) -> None:
        refs = [
            node["$ref"] for node in _walk(self.doc) if isinstance(node, dict) and "$ref" in node
        ]
        self.assertGreater(len(refs), 0)
        for ref in refs:
            with self.subTest(ref=ref):
                self.assertIsInstance(_resolve_ref(self.doc, ref), dict)

    def test_operations_have_ids_security_and_response_contracts(self) -> None:
        public_paths = {"/health", "/openapi.json"}
        operation_ids: set[str] = set()
        for path, path_item in self.doc["paths"].items():
            for method, operation in path_item.items():
                with self.subTest(path=path, method=method):
                    operation_id = operation.get("operationId")
                    self.assertIsInstance(operation_id, str)
                    self.assertNotIn(operation_id, operation_ids)
                    operation_ids.add(operation_id)

                    expected_security = (
                        [] if path in public_paths else [{"bearerAuth": [], "userToken": []}]
                    )
                    self.assertEqual(operation.get("security", []), expected_security)

                    responses = operation.get("responses")
                    self.assertIsInstance(responses, dict)
                    self.assertTrue(any(str(code).startswith("2") for code in responses))
                    for code, response in responses.items():
                        self.assertIn("description", response, f"{method.upper()} {path} {code}")
                        if str(code).startswith("2"):
                            headers = response.get("headers") or {}
                            self.assertEqual(
                                headers.get("api-version", {}).get("$ref"),
                                "#/components/headers/ApiVersion",
                                f"{method.upper()} {path} {code} must publish api-version",
                            )
                        json_content = (response.get("content") or {}).get("application/json")
                        if json_content and "schema" in json_content:
                            self._assert_schema_is_well_formed(json_content["schema"])

                    request_body = operation.get("requestBody")
                    if request_body:
                        schema = request_body["content"]["application/json"]["schema"]
                        self._assert_schema_is_well_formed(schema)

    def test_path_parameters_are_declared(self) -> None:
        for path, path_item in self.doc["paths"].items():
            expected = [
                part[1:-1]
                for part in path.split("/")
                if part.startswith("{") and part.endswith("}")
            ]
            if not expected:
                continue
            for method, operation in path_item.items():
                params = operation.get("parameters") or []
                declared = {
                    p.get("name")
                    for p in params
                    if p.get("in") == "path" and p.get("required") is True
                }
                with self.subTest(path=path, method=method):
                    self.assertEqual(set(expected), declared)

    def test_component_schemas_are_typed_and_internal(self) -> None:
        schemas = self.doc["components"]["schemas"]
        for name, schema in schemas.items():
            with self.subTest(schema=name):
                self._assert_schema_is_well_formed(schema)

    def test_shared_dto_shapes_match_openapi(self) -> None:
        schemas = self.doc["components"]["schemas"]
        self.assertEqual(
            schemas["AnswerResponse"]["properties"]["used_chunks"]["items"]["$ref"],
            "#/components/schemas/UsedChunk",
        )
        self.assertEqual(
            schemas["SearchResponse"]["properties"]["results"]["items"]["$ref"],
            "#/components/schemas/SearchResultItem",
        )
        self.assertIn("dead_letter", schemas["IngestResponse"]["properties"]["status"]["enum"])

    def test_admin_settings_surface_is_published(self) -> None:
        expected_paths = {
            "/admin/datasources",
            "/admin/datasources/{source_id}",
            "/admin/query-profiles",
            "/admin/query-profiles/{profile_id}",
            "/admin/provider-policies",
            "/admin/provider-policies/{provider_policy_id}",
            "/admin/provider-policies/{provider_policy_id}/validate",
            "/admin/retrieval-profiles",
            "/admin/retrieval-profiles/{retrieval_profile_id}",
            "/admin/retrieval-profiles/{retrieval_profile_id}/benchmark",
            "/admin/logging-policies",
            "/admin/logging-policies/{logging_policy_id}",
            "/admin/acl",
            "/admin/budgets",
        }
        self.assertTrue(expected_paths.issubset(set(self.doc["paths"])))

        schemas = self.doc["components"]["schemas"]
        self.assertIn("object_storage", schemas["AdminDataSource"]["properties"]["type"]["enum"])
        self.assertIn("captioning_enabled", schemas["QueryProfileSettings"]["properties"])
        self.assertIn(
            "aws_only", schemas["ProviderPolicySettings"]["properties"]["parser_mode"]["enum"]
        )
        self.assertIn(
            "vector_only_disabled",
            schemas["RetrievalProfileSettings"]["properties"]["fallback_behavior"]["enum"],
        )
        self.assertEqual(
            schemas["LoggingPolicySettings"]["properties"]["raw_retrieved_context_storage"]["enum"][
                0
            ],
            "disabled",
        )
        self.assertEqual(
            schemas["ACLSettingsResponse"]["properties"]["grants"]["items"]["$ref"],
            "#/components/schemas/AdminACLGrant",
        )
        self.assertEqual(
            schemas["BudgetSettingsResponse"]["properties"]["budgets"]["items"]["$ref"],
            "#/components/schemas/AdminBudget",
        )

    def test_schemathesis_is_declared_for_full_api_contract_gate(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text()
        self.assertIn("schemathesis", pyproject)
        try:
            import schemathesis  # type: ignore
        except ModuleNotFoundError:
            self.skipTest(
                "schemathesis is declared in dev extras but not installed in this environment"
            )
        self.assertTrue(hasattr(schemathesis, "openapi"))

    def _assert_schema_is_well_formed(self, schema: dict[str, Any]) -> None:
        if "$ref" in schema:
            self.assertIsInstance(_resolve_ref(self.doc, schema["$ref"]), dict)
            return
        self.assertTrue(
            "type" in schema or "properties" in schema or "items" in schema or "enum" in schema,
            f"schema must be typed or composed: {schema}",
        )
        if schema.get("type") == "array":
            self.assertIn("items", schema)
            self._assert_schema_is_well_formed(schema["items"])
        for prop in (schema.get("properties") or {}).values():
            if isinstance(prop, dict):
                self._assert_schema_is_well_formed(prop)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
