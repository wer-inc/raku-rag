"""Contract for the AI電話 rename + the browser TTS voice picker (call simulator voice mode).

apps/web has no TS unit runner, so this pins at source level that: the nav/tab label is 「AI電話」;
the call simulator exposes a device-voice selector + rate/pitch persisted via lib/voice-prefs; and the
speak path actually applies those prefs. Same marker style as test_web_upload_reconcile.py.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FULL_SAAS = ROOT / "apps/web/app/components/FullSaasScreen.tsx"
FULL_SAAS_LIB = ROOT / "apps/web/lib/full-saas.ts"
VOICE_PREFS = ROOT / "apps/web/lib/voice-prefs.ts"


class WebPhoneVoiceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.full_saas = FULL_SAAS.read_text(encoding="utf-8")
        cls.lib = FULL_SAAS_LIB.read_text(encoding="utf-8")
        cls.voice_prefs = VOICE_PREFS.read_text(encoding="utf-8")

    def test_phone_is_renamed_to_ai_denwa(self) -> None:
        self.assertIn('label: "AI電話"', self.lib)
        self.assertNotIn('label: "電話AI"', self.lib)
        self.assertIn('aria-label="AI電話の機能"', self.full_saas)

    def test_voice_prefs_module_exposes_load_save_with_clamps(self) -> None:
        for marker in (
            "export function loadVoicePrefs",
            "export function saveVoicePrefs",
            "DEFAULT_VOICE_PREFS",
            "export function clampRate",
            "export function clampPitch",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.voice_prefs)

    def test_simulator_has_voice_selector_and_applies_prefs(self) -> None:
        for marker in (
            "window.speechSynthesis.getVoices()",  # enumerate device voices
            '"voiceschanged"',  # voices load async
            "function applyVoicePrefs(utterance: SpeechSynthesisUtterance)",
            "applyVoicePrefs(utterance);",  # applied on the spoken turn
            "updateVoicePrefs({ voiceURI:",  # the <select>
            "updateVoicePrefs({ rate:",  # speed slider
            "updateVoicePrefs({ pitch:",  # pitch slider
            "function previewVoice()",  # 試聴 button
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.full_saas)


if __name__ == "__main__":
    unittest.main()
