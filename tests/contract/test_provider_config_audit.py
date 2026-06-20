from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ProviderConfigAuditContractTest(unittest.TestCase):
    def test_api_and_shared_contract_expose_redacted_audit_events(self) -> None:
        shared = (ROOT / "packages/shared/src/dto/admin-settings.ts").read_text(encoding="utf-8")
        controller = (ROOT / "apps/api/src/admin/settings.controller.ts").read_text(
            encoding="utf-8"
        )
        openapi = (ROOT / "apps/api/src/openapi/openapi.controller.ts").read_text(encoding="utf-8")

        for token in (
            "ProviderConfigAuditEvent",
            "redacted_before",
            "redacted_after",
            "model_changed",
            "parser_provider_changed",
            "residency_override",
            "opt_in_changed",
        ):
            with self.subTest(token=token):
                self.assertIn(token, shared)
                self.assertIn(token, openapi)

        self.assertIn('@Get("provider-config-audit-events")', controller)
        self.assertIn("/internal/admin/provider-config-audit-events", controller)
        self.assertIn("listProviderConfigAuditEvents", openapi)

    def test_answer_service_uses_provider_config_audit_repository(self) -> None:
        server = (ROOT / "apps/answer-service/server.py").read_text(encoding="utf-8")
        repository = (ROOT / "src/raku_rag/persistence/provider_config_audit.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("ProviderConfigAuditRepository", server)
        self.assertIn("record_change", server)
        self.assertIn("list_audit_events", server)
        self.assertIn("redact_snapshot", repository)
        self.assertIn("[REDACTED:secret]", repository)


if __name__ == "__main__":
    unittest.main()
