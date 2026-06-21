"""P0-1 root-cause — every release-blocking SECURITY_CHECK must be COMPUTED by a real probe (none
caller-count-only), and each newly-added probe must actually DETECT a leak (mechanism-pinned, §3) and
fail closed.

NEW file (does not modify the protected tests/security/test_eval_security_probes.py). Closes the gap
where unauthorized_context + the 4 visual checks had no probe in DEFAULT_PROBES, so they could never
block the gate.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from raku_rag.eval.probes import (
    DEFAULT_PROBES,
    SecurityProbeSuite,
    unauthorized_context_probe,
    visual_acl_leakage_probe,
    visual_deleted_reappearance_probe,
    visual_thumbnail_crop_leakage_probe,
    visual_unauthorized_context_probe,
)
from raku_rag.eval.runner import SECURITY_CHECKS

_NEW_PROBES = (
    unauthorized_context_probe,
    visual_acl_leakage_probe,
    visual_deleted_reappearance_probe,
    visual_unauthorized_context_probe,
    visual_thumbnail_crop_leakage_probe,
)


class _TextLeakyStub:
    """Insecure base system: search/answer cite EVERY doc (ignore ACL); delete is a no-op."""

    def __init__(self) -> None:
        self._docs: list[str] = []
        self.deletion = SimpleNamespace(
            delete=lambda tenant_id, document_id: SimpleNamespace(invalidated_cache_entries=0)
        )

    def ingest_text(self, *, tenant_id, collection_id, document_id, text) -> None:
        self._docs.append(document_id)

    def grant(self, *a, **k) -> None:
        return None

    def search(self, principal, question, collection_id=None):
        return [
            SimpleNamespace(chunk=SimpleNamespace(document_id=d, tenant_id="probe_t"))
            for d in self._docs
        ]

    def answer(self, principal, question, collection_id=None):
        cites = [SimpleNamespace(document_id=d) for d in self._docs]
        return SimpleNamespace(
            status="ok",
            citations=cites,
            used_chunks=tuple(f"{d}:0" for d in self._docs),
            text="RX99_RESTRICTED_MARGIN leaked",
        )


class _VisualLeakyStub(_TextLeakyStub):
    """Insecure base system with a visual ingestion path that also ignores ACL/deletion."""

    def ingest_visual_fixture(self, *, tenant_id, collection_id, document_id, image, **kw):
        self._docs.append(document_id)
        return SimpleNamespace(
            asset=SimpleNamespace(asset_id=f"asset_{document_id}"),
            regions=[SimpleNamespace(region_id=f"r_{document_id}")],
        )

    def answer(self, principal, question, collection_id=None):
        cites = [
            SimpleNamespace(
                document_id=d, asset_id=f"asset_{d}", crop_uri=f"crop://{d}", kind="visual"
            )
            for d in self._docs
        ]
        return SimpleNamespace(
            status="ok",
            citations=cites,
            used_chunks=tuple(f"{d}:0" for d in self._docs),
            text="RX99 override bypass leaked",
        )


class _DenyStub:
    """Returns nothing for everything — a no-op target must FAIL each probe's positive control."""

    def __init__(self) -> None:
        self.deletion = SimpleNamespace(
            delete=lambda tenant_id, document_id: SimpleNamespace(invalidated_cache_entries=0)
        )

    def ingest_text(self, **k) -> None:
        return None

    def ingest_visual_fixture(self, *, document_id, **k):
        return SimpleNamespace(
            asset=SimpleNamespace(asset_id=f"asset_{document_id}"),
            regions=[SimpleNamespace(region_id="r")],
        )

    def grant(self, *a, **k) -> None:
        return None

    def search(self, *a, **k):
        return []

    def answer(self, *a, **k):
        return SimpleNamespace(
            status="insufficient_evidence", citations=[], used_chunks=(), text=None
        )


def _leaky_for(probe):
    return _TextLeakyStub if probe is unauthorized_context_probe else _VisualLeakyStub


class TestEverySecurityCheckHasAProbe(unittest.TestCase):
    def test_full_coverage(self) -> None:
        outcome = SecurityProbeSuite().run()
        probe_names = set(outcome.counts)
        missing = set(SECURITY_CHECKS) - probe_names
        self.assertFalse(
            missing, f"SECURITY_CHECKS with no probe (caller-count-only): {sorted(missing)}"
        )
        self.assertTrue(outcome.probes_executed)
        for r in outcome.results:
            self.assertEqual(r.status, "ok", msg=str(r))
            self.assertEqual(r.leakage_count, 0, msg=str(r))
            self.assertTrue(r.executed, msg=str(r))


class TestNewProbesDetectLeak(unittest.TestCase):
    def test_leaky_system_each_new_probe_blocks(self) -> None:
        for probe in _NEW_PROBES:
            with self.subTest(probe=probe.__name__):
                result = probe(make_system=_leaky_for(probe))
                self.assertTrue(result.executed, msg=str(result))
                self.assertEqual(result.status, "blocked", msg=str(result))
                self.assertGreaterEqual(result.leakage_count, 1, msg=str(result))


class TestNewProbesFailClosed(unittest.TestCase):
    def test_deny_all_system_is_unavailable_not_pass(self) -> None:
        for probe in _NEW_PROBES:
            with self.subTest(probe=probe.__name__):
                result = probe(make_system=_DenyStub)
                self.assertEqual(result.status, "unavailable", msg=str(result))
                self.assertFalse(result.executed, msg=str(result))


class TestNewProbesInDefaultSuite(unittest.TestCase):
    def test_new_probes_are_registered(self) -> None:
        for probe in _NEW_PROBES:
            self.assertIn(probe, DEFAULT_PROBES, msg=probe.__name__)


if __name__ == "__main__":
    unittest.main()
