"""ADR-018 §10 / §8.4 — real Bedrock (Claude vision) adapters for VLM draft + handwriting/seal.

These are opt-in and §19 cloud-egress-gated. The tests inject a fake ``build_bedrock_vision_invoker``-
shaped callable so the request/parse handling is validated OFFLINE (no boto3, no AWS). Live verification
needs Bedrock credentials, which the environment does not have.
"""

from __future__ import annotations

import os
import unittest
from contextlib import contextmanager

from raku_rag.providers.vlm_draft import (
    BedrockVlmDraftProvider,
    select_vlm_draft_provider,
)
from raku_rag.services.quality_detectors import (
    BedrockVisualArtifactDetector,
    _parse_artifact_signals,
    select_visual_artifact_detector,
)


@contextmanager
def _env(**values: str):
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


class BedrockVlmDraftTest(unittest.TestCase):
    def test_registered_by_name(self) -> None:
        self.assertIsInstance(select_vlm_draft_provider("bedrock"), BedrockVlmDraftProvider)

    def test_injected_invoker_produces_a_draft(self) -> None:
        seen: dict[str, object] = {}

        def fake(*, model_id, prompt, image=None, max_tokens=512, media_type="image/png"):
            seen.update(model_id=model_id, prompt=prompt, image=image)
            return "  Transcribed line 1\nTranscribed line 2  "

        provider = BedrockVlmDraftProvider(invoker=fake, model_id="test-model")
        self.assertTrue(provider.available())
        result = provider.draft_from_image(b"PNGBYTES", page_no=3)
        self.assertEqual(result.text, "Transcribed line 1\nTranscribed line 2")
        self.assertEqual(result.model, "test-model")
        self.assertEqual(result.provider, "bedrock")
        # The page image is actually forwarded to the VLM.
        self.assertEqual(seen["image"], b"PNGBYTES")

    def test_unavailable_without_egress_optin(self) -> None:
        # No injected invoker + egress not opted in -> unavailable, and a no-op empty draft.
        with _env(RAKU_ALLOW_CLOUD_EGRESS="false"):
            provider = BedrockVlmDraftProvider()
            self.assertFalse(provider.available())
            self.assertEqual(provider.draft_from_image(b"x", page_no=1).text, "")


class BedrockVisualArtifactTest(unittest.TestCase):
    def test_registered_by_name(self) -> None:
        self.assertIsInstance(
            select_visual_artifact_detector("bedrock"), BedrockVisualArtifactDetector
        )

    def test_injected_invoker_parses_signals(self) -> None:
        def fake(*, model_id, prompt, image=None, max_tokens=512, media_type="image/png"):
            return '{"handwriting": true, "seal": false, "drawing": true}'

        detector = BedrockVisualArtifactDetector(invoker=fake)
        signals = detector.detect(b"PNG", page_no=1)
        self.assertTrue(signals.handwriting_detected)
        self.assertFalse(signals.seal_detected)
        self.assertTrue(signals.drawing_like)
        self.assertTrue(signals.any())

    def test_parses_json_embedded_in_prose(self) -> None:
        signals = _parse_artifact_signals(
            'Here is the result: {"handwriting": false, "seal": true, "drawing": false} done.'
        )
        self.assertTrue(signals.seal_detected)
        self.assertFalse(signals.handwriting_detected)

    def test_parse_failure_flags_nothing(self) -> None:
        for bad in ("not json at all", "", "{oops", "[1,2,3]"):
            signals = _parse_artifact_signals(bad)
            self.assertFalse(signals.any(), bad)

    def test_unavailable_without_egress_optin(self) -> None:
        with _env(RAKU_ALLOW_CLOUD_EGRESS="0"):
            detector = BedrockVisualArtifactDetector()
            self.assertFalse(detector.available())
            self.assertFalse(detector.detect(b"x", page_no=1).any())


if __name__ == "__main__":
    unittest.main()
