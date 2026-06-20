"""T060 — NO-TRAIN HARD GATE SC-MFG-009 (FR-MFG-016~018/029, GQ1, Hard Rule 7).

This is an ABSOLUTE gate (loop-engineering §3 mechanism-pin). Customer data is NEVER used for
model training / improvement without an explicit tenant-admin opt-in (training_opt_in=True AND a
non-empty opt_in_contract_ref), and a capability whose available providers are NOT
no-train-guaranteed is BLOCKED (surfaced as ``temporarily_unavailable``), never silently degraded to
a non-no-train provider. A regression in either direction MUST fail this test.

Mechanism pinned (do NOT weaken in stage 2):
 (1) OPT-IN REQUIRED — attempting to use customer data for training/improvement when
     ``training_opt_in`` is False (the default) OR there is no ``opt_in_contract_ref`` is REJECTED
     (raises). Assert the refusal explicitly; SC-MFG-009 counts such uses as 0.
 (2) BLOCK NOT DEGRADE — a capability whose only available providers are NOT no-train-guaranteed,
     with ``provider_no_train_required=True``, is BLOCKED. The capability surfaces as status
     ``temporarily_unavailable`` with NO assertion, and it MUST NOT silently fall back to a
     non-no-train provider (GQ1=block).
 (3) POSITIVE CONTROLS — a no-train-guaranteed provider capability is ALLOWED, and training WITH
     ``training_opt_in=True`` AND a non-empty ``opt_in_contract_ref`` is PERMITTED. This blocks a
     degenerate "always block / always reject" implementation from passing.

Authoritative: spec FR-MFG-016~018/029, SC-MFG-009; contracts/mfg-openapi.md §F + "安全・監査";
contracts/mfg-interfaces.md §7 (NoTrainGuard); data-model §G; quickstart S8; GQ1. Assertion style
mirrors tests/manufacturing/test_safety_gate.py + tests/security/test_acl_leak.py.

Entrypoint contract the stage-2 ``ManufacturingSystem`` + ``NoTrainGuard`` must satisfy (the minimal
002 no-train surface; provider no-train *capability verification* itself is Base CR-001-B in 001 —
here 002 enforces policy/opt-in against an INJECTED provider-capability map):

  ManufacturingSystem(*, provider_capabilities=None, no_train_providers=None, ...)
      ``provider_capabilities``: {capability_name: (provider_name, ...)} — which providers serve a
          capability (the answer/draft/embedding/ocr/vlm features). Injected (analog of the 001
          LLMProvider wiring); when omitted the system uses a safe default map.
      ``no_train_providers``: a set/iterable of provider names that are no-train-GUARANTEED
          (the Base CR-001-B verified set, injected here). A provider NOT in this set is treated as
          NOT no-train-guaranteed.
      exposes ``self.no_train`` — a ``raku_rag.manufacturing.interfaces.NoTrainGuard`` implementation
          bound to the per-tenant DataUsePolicyStore + the injected capability/no-train maps.

  NoTrainGuard.assert_no_train(tenant_id, data_kind) -> None
      Raises (refuses) unless the tenant policy has training_opt_in=True AND a non-empty
      opt_in_contract_ref. ``data_kind`` is a reference label (e.g. "answer"/"draft"/"feedback").
  NoTrainGuard.capability_allowed(tenant_id, capability) -> bool
      False when provider_no_train_required=True and the capability has NO no-train-guaranteed
      provider available (GQ1=block); True when at least one available provider is no-train-guaranteed.

  ManufacturingSystem.use_for_training(*, tenant_id, data_kind, actor) -> None
      The single funnel for "use customer data for training/improvement". Delegates to
      ``no_train.assert_no_train`` (so opt-in-less training is impossible) BEFORE any use; records the
      attempt/decision to the audit log (FR-MFG-019/021). Raises on refusal.
  ManufacturingSystem.capability_status(tenant_id, capability) -> str
      "temporarily_unavailable" when ``no_train.capability_allowed`` is False (GQ1 block — capability
      origin, no inferred answer), else "ok". This is the status surfaced by the answer/feature path.
  ManufacturingSystem.update_data_use_policy / get_data_use_policy — see test_governance_contract.py.

TDD: RED now because the no-train enforcement surface
(``ManufacturingSystem.use_for_training`` / ``.capability_status`` / ``self.no_train``) is
unimplemented (missing-impl), NOT an unrelated import error.
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import IdentityClaims
from raku_rag.manufacturing.app import ManufacturingSystem

T = "tenant_mfg"


def _admin(tenant: str = T, user: str = "admin-1") -> IdentityClaims:
    return IdentityClaims(tenant_id=tenant, user_id=user, roles=("admin",))


# A capability map where the SAME capability is served by a NON-no-train provider only, while another
# capability is served by a no-train-guaranteed provider. The no-train set is the Base CR-001-B
# "verified" set — providers NOT in it are treated as not no-train-guaranteed.
CAPS = {
    "answer_llm": ("trustworthy_llm",),  # served by a no-train-guaranteed provider
    "fancy_embedding": ("leaky_embedding",),  # served ONLY by a NON-no-train provider
    "mixed_ocr": ("leaky_ocr", "trustworthy_ocr"),  # at least one no-train provider available
}
NO_TRAIN_PROVIDERS = ("trustworthy_llm", "trustworthy_ocr")  # the Base CR-001-B verified set


def _fresh() -> ManufacturingSystem:
    return ManufacturingSystem(provider_capabilities=CAPS, no_train_providers=NO_TRAIN_PROVIDERS)


# --- (1) OPT-IN REQUIRED -------------------------------------------------------------------------
class TestOptInRequiredForTraining(unittest.TestCase):
    """Customer data may NOT be used for training/improvement without an explicit admin opt-in."""

    def test_default_policy_rejects_training_use(self) -> None:
        # Default policy: no_train_default=True, training_opt_in=False → any training use is refused.
        sys = _fresh()
        with self.assertRaises(Exception) as ctx:
            sys.use_for_training(tenant_id=T, data_kind="answer", actor=_admin())
        # Refusal is about the missing opt-in, not an incidental error.
        self.assertNotIsInstance(ctx.exception, (AttributeError, TypeError, NameError, ImportError))

    def test_guard_assert_no_train_raises_by_default(self) -> None:
        # The underlying guard itself refuses (the funnel cannot be bypassed by calling it directly).
        sys = _fresh()
        with self.assertRaises(Exception):
            sys.no_train.assert_no_train(T, "feedback")

    def test_opt_in_true_without_contract_ref_still_rejected(self) -> None:
        # FR-MFG-018: opt-in WITHOUT a contract reference is not a valid opt-in. The policy store
        # refuses to even persist such a state; training use therefore remains impossible.
        sys = _fresh()
        with self.assertRaises(ValueError):
            sys.update_data_use_policy(tenant_id=T, patch={"training_opt_in": True}, actor=_admin())
        # And training is still refused (policy unchanged → opt-in absent).
        with self.assertRaises(Exception):
            sys.use_for_training(tenant_id=T, data_kind="answer", actor=_admin())

    def test_training_use_count_is_zero_without_opt_in(self) -> None:
        # SC-MFG-009 framing: across several attempts under the default policy, the number of
        # ACCEPTED training uses is 0 (every attempt raises; none succeeds).
        sys = _fresh()
        accepted = 0
        for kind in ("answer", "draft", "feedback", "eval"):
            try:
                sys.use_for_training(tenant_id=T, data_kind=kind, actor=_admin())
                accepted += 1
            except Exception:
                pass
        self.assertEqual(
            accepted, 0, "no training use may be accepted without admin opt-in (SC-MFG-009=0)"
        )


# --- (2) BLOCK NOT DEGRADE -----------------------------------------------------------------------
class TestBlockNotDegrade(unittest.TestCase):
    """A capability without a no-train-guaranteed provider is BLOCKED, never silently degraded."""

    def test_non_no_train_capability_is_blocked(self) -> None:
        sys = _fresh()
        self.assertFalse(
            sys.no_train.capability_allowed(T, "fancy_embedding"),
            "a capability whose only provider is NOT no-train-guaranteed must be disallowed "
            "(provider_no_train_required + GQ1=block)",
        )

    def test_blocked_capability_surfaces_temporarily_unavailable(self) -> None:
        sys = _fresh()
        status = sys.capability_status(T, "fancy_embedding")
        self.assertEqual(
            status,
            "temporarily_unavailable",
            "GQ1: a no-train-unguaranteed capability must surface as 'temporarily_unavailable' "
            "(capability-origin block), NOT an inferred/degraded answer",
        )

    def test_does_not_silently_fall_back_to_non_no_train_provider(self) -> None:
        # The selected provider for a blocked capability must NEVER be a non-no-train provider; if the
        # system exposes a resolver it must refuse rather than hand back the leaky provider.
        sys = _fresh()
        resolved = None
        raised = False
        try:
            resolved = sys.resolve_capability_provider(T, "fancy_embedding")
        except Exception:
            raised = True
        self.assertTrue(
            raised or resolved is None or resolved not in CAPS["fancy_embedding"],
            "must NOT silently fall back to the non-no-train provider 'leaky_embedding' (no silent degrade)",
        )
        self.assertNotEqual(
            resolved,
            "leaky_embedding",
            "a blocked capability must never resolve to a non-no-train provider",
        )


# --- (3) POSITIVE CONTROLS -----------------------------------------------------------------------
class TestPositiveControls(unittest.TestCase):
    """Block a degenerate 'always reject / always block' impl: legitimate use IS permitted."""

    def test_no_train_guaranteed_capability_is_allowed(self) -> None:
        sys = _fresh()
        self.assertTrue(
            sys.no_train.capability_allowed(T, "answer_llm"),
            "a capability served by a no-train-GUARANTEED provider must be allowed",
        )
        self.assertEqual(sys.capability_status(T, "answer_llm"), "ok")

    def test_capability_with_at_least_one_no_train_provider_is_allowed(self) -> None:
        # 'mixed_ocr' has one leaky + one no-train provider → allowed (a no-train provider exists).
        sys = _fresh()
        self.assertTrue(sys.no_train.capability_allowed(T, "mixed_ocr"))
        self.assertEqual(sys.capability_status(T, "mixed_ocr"), "ok")

    def test_training_permitted_with_opt_in_and_contract_ref(self) -> None:
        # Admin opts in WITH a contract reference (FR-MFG-018) → training/improvement use is permitted.
        sys = _fresh()
        sys.update_data_use_policy(
            tenant_id=T,
            patch={"training_opt_in": True, "opt_in_contract_ref": "CONTRACT-2026-009"},
            actor=_admin(),
        )
        # Now the funnel permits the use (must NOT raise) and the guard agrees.
        sys.use_for_training(tenant_id=T, data_kind="eval", actor=_admin())  # no raise == permitted
        sys.no_train.assert_no_train(T, "eval")  # guard no longer refuses

    def test_opt_in_is_tenant_scoped_other_tenant_still_blocked(self) -> None:
        # Opting one tenant in must NOT relax no-train for a different tenant (001 tenancy reused).
        sys = _fresh()
        sys.update_data_use_policy(
            tenant_id=T,
            patch={"training_opt_in": True, "opt_in_contract_ref": "CONTRACT-2026-009"},
            actor=_admin(),
        )
        other = "tenant_other"
        with self.assertRaises(Exception):
            sys.use_for_training(tenant_id=other, data_kind="answer", actor=_admin(other))


if __name__ == "__main__":
    unittest.main()
