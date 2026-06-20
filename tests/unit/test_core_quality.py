"""T082 - core quality unit coverage."""

from __future__ import annotations

import unittest

from raku_rag.core.security.acl import AclPolicy
from raku_rag.domain.models import (
    ACLGrant,
    Chunk,
    QueryProfile,
    ScopeType,
    ScoredChunk,
    SubjectType,
)
from raku_rag.observability.redaction import Redactor
from raku_rag.providers.chunkers import SentenceChunker
from raku_rag.services.groundedness import GroundednessGate
from tests.helpers import claims

T = "tenant_a"


class TestCoreQuality(unittest.TestCase):
    def test_chunker_respects_japanese_boundaries_and_offsets(self) -> None:
        text = "# 点検手順\n\nポンプを停止します。圧力を確認します！再起動します？"
        chunks = SentenceChunker(max_chars=12).chunk(text)

        self.assertEqual(
            [chunk[0] for chunk in chunks],
            ["ポンプを停止します。", "圧力を確認します！", "再起動します？"],
        )
        self.assertTrue(all(chunk[1] == ("点検手順",) for chunk in chunks))
        for chunk_text, _heading, _position, span in chunks:
            self.assertEqual(text[span[0] : span[1]].strip(), chunk_text)

    def test_acl_is_deny_by_default_and_hierarchical(self) -> None:
        policy = AclPolicy([])
        alice = claims(T, "alice")
        self.assertFalse(policy.can_read(alice, tenant_id=T, collection_id="c", document_id="d1"))

        policy.add(ACLGrant(T, ScopeType.COLLECTION, "c", SubjectType.USER, "alice"))

        self.assertTrue(policy.can_read(alice, tenant_id=T, collection_id="c", document_id="d1"))
        self.assertFalse(
            policy.can_read(
                claims("tenant_b", "alice"), tenant_id=T, collection_id="c", document_id="d1"
            )
        )
        self.assertFalse(
            policy.can_read(claims(T, "bob"), tenant_id=T, collection_id="c", document_id="d1")
        )

    def test_groundedness_gate_rejects_weak_or_unsupported_answers(self) -> None:
        gate = GroundednessGate()
        profile = QueryProfile(score_threshold=0.5, minimum_evidence_count=1)
        chunk = Chunk(
            tenant_id=T,
            chunk_id="c1",
            document_id="d1",
            collection_id="c",
            text="Backups run nightly.",
        )

        self.assertFalse(gate.pre_gate([ScoredChunk(chunk, 0.1)], profile).passed)
        self.assertTrue(gate.pre_gate([ScoredChunk(chunk, 0.9)], profile).passed)
        self.assertTrue(gate.post_check("Nightly backups run.", [chunk]).passed)
        self.assertFalse(gate.post_check("The answer is unrelated.", [chunk]).passed)

    def test_text_visual_exif_and_caption_redaction(self) -> None:
        redactor = Redactor()
        self.assertEqual(redactor.redact("contact alice@example.com"), "contact [REDACTED:email]")
        self.assertEqual(
            redactor.redact_visual_text("caption key sk-ABCDEFGHIJKLMNOP and bob@example.com"),
            "caption key [REDACTED:api_key] and [REDACTED:email]",
        )
        exif = redactor.redact_exif(
            {
                "GPSLatitude": "35.0",
                "Model": "SensitiveCam",
                "ImageDescription": "owner bob@example.com",
                "ColorSpace": "sRGB",
            }
        )
        self.assertEqual(set(exif.removed_keys), {"GPSLatitude", "Model"})
        self.assertEqual(exif.metadata["ImageDescription"], "owner [REDACTED:email]")
        self.assertEqual(exif.metadata["ColorSpace"], "sRGB")


if __name__ == "__main__":
    unittest.main()
