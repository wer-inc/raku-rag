"""P1-5 (offline) — runtime-profile selection of the Langfuse telemetry exporter.

The answer flow already emits one span per answer through the tracer/exporter seam (services/answer.py).
Under the production profile with LANGFUSE_ENABLED, exporter_from_settings selects the
LangfuseTelemetryExporter, which ships each event to an INJECTED client (network dependency at the edge).
The real network export to a Langfuse host is verify_live (blocked-needs-infra). deterministic stays a
no-op exporter so Tier-A is untouched.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from raku_rag.core.config import Settings
from raku_rag.observability.exporters import (
    LangfuseTelemetryExporter,
    StructuredLogTelemetryExporter,
    TelemetryEvent,
    exporter_from_settings,
)


class LangfuseExporterProfileTest(unittest.TestCase):
    def test_deterministic_default_has_no_exporter(self) -> None:
        self.assertIsNone(exporter_from_settings(Settings()))

    def test_production_with_langfuse_selects_langfuse_exporter(self) -> None:
        settings = replace(Settings(), runtime_profile="production", langfuse_enabled=True)
        self.assertIsInstance(exporter_from_settings(settings), LangfuseTelemetryExporter)

    def test_production_without_langfuse_falls_back_to_structured_log_when_enabled(self) -> None:
        settings = replace(Settings(), runtime_profile="production", telemetry_export_enabled=True)
        self.assertIsInstance(exporter_from_settings(settings), StructuredLogTelemetryExporter)

    def test_export_routes_each_event_to_injected_client(self) -> None:
        seen = []

        def client(*, kind, name, payload):
            seen.append((kind, name))

        settings = replace(Settings(), runtime_profile="production", langfuse_enabled=True)
        exporter = exporter_from_settings(settings, langfuse_client=client)
        exporter.export(TelemetryEvent("span", "answer", {"answer_status": "ok"}))
        self.assertEqual(seen, [("span", "answer")])

    def test_exporter_is_failsafe_without_a_client(self) -> None:
        # no client configured -> no-op, never raises (telemetry must not break the answer path)
        LangfuseTelemetryExporter(client=None).export(TelemetryEvent("span", "answer", {}))

    def test_exporter_swallows_client_errors(self) -> None:
        def bad_client(*, kind, name, payload):
            raise RuntimeError("langfuse down")

        LangfuseTelemetryExporter(client=bad_client).export(TelemetryEvent("span", "answer", {}))


if __name__ == "__main__":
    unittest.main()
