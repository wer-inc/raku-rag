"""P1-5 (offline) — build_langfuse_client edge wiring, verified without a network or the real SDK.

build_langfuse_client turns Settings into the keyword-only (kind, name, payload) callable that
LangfuseTelemetryExporter injects. Every "not wired" path must fail safe to None (no exporter, no
crash); the wired path must emit one Langfuse trace per event named "<kind>.<name>". A fake langfuse
module stands in for the SDK so this stays a stdlib-only, no-network test (the real trace landing in a
Langfuse UI is verify_live, blocked-needs-infra).
"""

from __future__ import annotations

import sys
import types
import unittest
from dataclasses import replace

from raku_rag.core.config import Settings
from raku_rag.observability.langfuse_client import build_langfuse_client


def _wired_settings() -> Settings:
    return replace(
        Settings(),
        runtime_profile="production",
        langfuse_enabled=True,
        langfuse_host="http://localhost:3001",
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",
    )


class _FakeLangfuse:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.traces: list = []
        self.flushed = 0
        _FakeLangfuse.instances.append(self)

    def trace(self, **kwargs):
        self.traces.append(kwargs)

    def flush(self):
        self.flushed += 1

    def shutdown(self):
        pass


class _FakeLangfuseModule(types.ModuleType):
    Langfuse = _FakeLangfuse


class BuildLangfuseClientTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeLangfuse.instances = []
        self._saved = sys.modules.get("langfuse")
        module = _FakeLangfuseModule("langfuse")
        module.Langfuse = _FakeLangfuse
        sys.modules["langfuse"] = module

    def tearDown(self) -> None:
        if self._saved is not None:
            sys.modules["langfuse"] = self._saved
        else:
            sys.modules.pop("langfuse", None)

    def test_disabled_returns_none(self) -> None:
        self.assertIsNone(build_langfuse_client(Settings()))

    def test_enabled_but_missing_keys_returns_none(self) -> None:
        settings = replace(Settings(), langfuse_enabled=True, langfuse_host="http://localhost:3001")
        self.assertIsNone(build_langfuse_client(settings))

    def test_sdk_absent_returns_none(self) -> None:
        # Simulate the `prod` extra not being installed: `from langfuse import Langfuse` raises.
        sys.modules["langfuse"] = None  # type: ignore[assignment]
        self.assertIsNone(build_langfuse_client(_wired_settings()))

    def test_wired_emits_one_trace_per_event(self) -> None:
        client = build_langfuse_client(_wired_settings())
        self.assertIsNotNone(client)
        client(kind="span", name="answer", payload={"answer_status": "ok"})
        self.assertEqual(len(_FakeLangfuse.instances), 1)
        traces = _FakeLangfuse.instances[0].traces
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["name"], "span.answer")
        self.assertEqual(traces[0]["input"], {"answer_status": "ok"})
        self.assertEqual(traces[0]["metadata"], {"raku.kind": "span", "raku.name": "answer"})

    def test_client_is_constructed_with_host_and_keys(self) -> None:
        build_langfuse_client(_wired_settings())
        kwargs = _FakeLangfuse.instances[0].kwargs
        self.assertEqual(kwargs["host"], "http://localhost:3001")
        self.assertEqual(kwargs["public_key"], "pk-lf-test")
        self.assertEqual(kwargs["secret_key"], "sk-lf-test")


if __name__ == "__main__":
    unittest.main()
