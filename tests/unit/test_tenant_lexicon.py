"""★V2 tenant_lexicon — additive-only resolution, validation, and channel wiring."""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.domain.audit import InMemoryAuditLogWriter
from raku_rag.manufacturing.safety.classifier import RuleHighRiskClassifier
from raku_rag.persistence.lexicon import InMemoryLexiconRepository
from raku_rag.phone.orchestrator import classify_intent
from raku_rag.services.lexicon import LexiconError, LexiconService

ADMIN = IdentityClaims(tenant_id="tenant_a", user_id="alice", roles=("tenant_admin",))


class LexiconServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = InMemoryAuditLogWriter()
        self.svc = LexiconService(InMemoryLexiconRepository(), audit=self.audit)

    def test_resolution_is_additive_defaults_never_removed(self) -> None:
        defaults = {"electric_shock": ("感電", "live wire")}
        self.svc.update(
            "tenant_a",
            "safety.high_risk_keywords",
            "electric_shock",
            ["漏電ブレーカー"],
            actor_id="alice",
        )
        merged = self.svc.resolve("tenant_a", "safety.high_risk_keywords", defaults)
        # The structural invariant: every default survives, tenant terms are appended.
        for term in defaults["electric_shock"]:
            self.assertIn(term, merged["electric_shock"])
        self.assertIn("漏電ブレーカー", merged["electric_shock"])

    def test_tenant_isolation_and_new_keys(self) -> None:
        self.svc.update(
            "tenant_a", "phone.intents", "warranty", ["保証", "延長保証"], actor_id="alice"
        )
        self.assertIn("warranty", self.svc.resolve("tenant_a", "phone.intents", {}))
        self.assertEqual(self.svc.resolve("tenant_b", "phone.intents", {}), {})

    def test_validation_and_audit(self) -> None:
        with self.assertRaises(LexiconError):
            self.svc.update("tenant_a", "not.a.namespace", "k", ["v"], actor_id="alice")
        with self.assertRaises(LexiconError):
            self.svc.update(
                "tenant_a", "chat.handoff_triggers", "default", ["", "  "], actor_id="alice"
            )
        self.svc.update(
            "tenant_a", "chat.handoff_triggers", "default", ["係の人"], actor_id="alice"
        )
        entries = [e for e in self.audit.read_all(ADMIN) if e.action == "lexicon.updated"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].resource_id, "chat.handoff_triggers/default")

    def test_remove_only_drops_overrides(self) -> None:
        self.svc.update("tenant_a", "phone.intents", "warranty", ["保証"], actor_id="alice")
        self.assertTrue(self.svc.remove("tenant_a", "phone.intents", "warranty", actor_id="a"))
        defaults = {"refund_cancellation": ("返金",)}
        merged = self.svc.resolve("tenant_a", "phone.intents", defaults)
        self.assertEqual(merged, {"refund_cancellation": ("返金",)})  # defaults intact


class ChannelWiringTest(unittest.TestCase):
    def test_safety_classifier_accepts_tenant_extras(self) -> None:
        from raku_rag.manufacturing.domain.safety import ClassificationSource

        clf = RuleHighRiskClassifier()
        # New-industry vocabulary outside the built-in sets. Without extras the terse query only
        # trips the AMBIGUOUS fail-safe (no concrete reason code); with tenant extras it becomes a
        # concrete KEYWORD detection carrying the labeled reason — auditable, not just cautious.
        query = "オートクレーブの滅菌槽を開けたい"
        baseline = clf.classify(query, ())
        self.assertNotIn("high_pressure", baseline.reason_codes)
        extras = {"high_pressure": ("オートクレーブ",)}
        result = clf.classify(query, (), extra_keywords=extras)
        self.assertTrue(result.is_high_risk)
        self.assertIn("high_pressure", result.reason_codes)
        self.assertEqual(result.classification_source, ClassificationSource.KEYWORD)

    def test_phone_intent_accepts_tenant_extras(self) -> None:
        self.assertEqual(classify_intent("保証期間を延長したい", None), "faq")
        extras = {"warranty": ("保証",)}
        self.assertEqual(classify_intent("保証期間を延長したい", None, extras), "warranty")
        # Built-in intents still win with their defaults present.
        self.assertEqual(classify_intent("解約したいです", None, extras), "refund_cancellation")


if __name__ == "__main__":
    unittest.main()
