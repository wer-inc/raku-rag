"""P4-4 / AF-9 (offline) — the answer-service internal boundary enforces a shared secret.

The deployed answer-service used to blindly trust the loopback request + its x-raku-* identity headers
(plaintext, no auth). This pins the shared-secret gate: when RAKU_INTERNAL_AUTH_SECRET is configured every
/internal/* request must carry a matching X-Internal-Auth header (constant-time); /healthz stays public;
and when the secret is unset (local dev/tests) the gate is a no-op so nothing regresses. The full mTLS on
the deployed API<->answer-service hop + the NestJS clients attaching the secret is the deployment-topology
half (verify_live, blocked-needs-infra without a deployed env).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SERVER = ROOT / "apps/answer-service/server.py"


def _load_server():
    spec = importlib.util.spec_from_file_location("answer_service_server", _SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InternalAuthGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = _load_server()
        cls.src = _SERVER.read_text(encoding="utf-8")

    def _ok(self, *args):
        # call via the module so the plain function isn't bound as a method (no extra self arg)
        return self.server.internal_auth_ok(*args)

    def test_unset_secret_is_a_no_op(self) -> None:
        self.assertTrue(self._ok("", "/internal/answer", ""))
        self.assertTrue(self._ok("", "/internal/manufacturing/answer", "anything"))

    def test_healthz_is_public_even_when_secret_set(self) -> None:
        self.assertTrue(self._ok("s3cret", "/healthz", ""))

    def test_matching_secret_is_allowed(self) -> None:
        self.assertTrue(self._ok("s3cret", "/internal/answer", "s3cret"))

    def test_missing_or_wrong_secret_is_rejected(self) -> None:
        self.assertFalse(self._ok("s3cret", "/internal/answer", ""))
        self.assertFalse(self._ok("s3cret", "/internal/answer", "nope"))

    def test_uses_constant_time_compare(self) -> None:
        # guard against a plain == regression (timing side-channel on the shared secret)
        self.assertIn("hmac.compare_digest", self.src)

    def _handler_method_source(self, method_name: str) -> str:
        marker = f"        def {method_name}(self) -> None:"
        start = self.src.index(marker)
        next_method = self.src.find("\n        def do_", start + len(marker))
        end = next_method if next_method != -1 else self.src.find("\n    return Handler", start)
        return self.src[start:end]

    def test_internal_verbs_enforce_the_gate_before_dispatch(self) -> None:
        # Every internal HTTP verb must call the gate before body parsing or route dispatch.
        for method_name in ("do_GET", "do_POST", "do_PUT", "do_DELETE"):
            with self.subTest(method_name=method_name):
                body = self._handler_method_source(method_name)
                gate = "if not self._internal_auth_ok(path):"
                self.assertIn(gate, body)
                gate_index = body.index(gate)
                for dispatch_token in ("body = self._body()", "parts = [unquote("):
                    token_index = body.find(dispatch_token)
                    if token_index != -1:
                        self.assertLess(gate_index, token_index)


if __name__ == "__main__":
    unittest.main()
