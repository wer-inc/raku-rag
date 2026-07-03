"""issue 0019 — the post-approval PUBLISH path: approved draft -> approved, citable knowledge.

The review screen promises 「承認済み — 正式に公開できます」; this suite pins the honest publish
loop that makes it true, WITHOUT weakening Hard Rule 1:

  - publish is legal ONLY from ``status=approved`` (draft / in_review / rejected -> error, artifact
    untouched);
  - publish is a SEPARATE, attributable HUMAN action — an unattributable/AI actor (no principal /
    empty user_id) is rejected with ``PermissionError`` (the actor always comes from the signed
    principal, never the request body);
  - publish is idempotent server-side: a second publish raises (maps to 409) and can never mint a
    second document;
  - the publish is recorded in the tamper-evident hash-chain audit (``draft.published``: actor,
    draft artifact, new document_id) and stamped on the artifact
    (published_document_id / published_by / published_at);
  - the published document is REAL knowledge: retrievable and citable through the SAME 001
    ACL-guarded answer path, carrying ``approval_status=approved`` + draft provenance.

stdlib only (Tier A).
"""

from __future__ import annotations

import unittest

from raku_rag.domain.models import ScopeType, SubjectType
from raku_rag.manufacturing.domain.draft import DraftStatus, DraftType
from raku_rag.manufacturing.domain.metadata import ApprovalStatus
from raku_rag.manufacturing.drafts.review import InvalidTransitionError
from raku_rag.manufacturing.safety.gate import is_approved_effective
from tests.manufacturing.helpers import T, claims, fresh

# Draft body sentence used to prove the published knowledge is retrievable via the answer path.
_FAQ_SENTENCE = "The conveyor motor lubrication interval is every ninety days under normal load."


def _status_value(artifact) -> str:
    return getattr(artifact.status, "value", artifact.status)


class _PublishBase(unittest.TestCase):
    """Shared fixture: an AI FAQ draft driven to ``approved`` by a human reviewer."""

    def setUp(self) -> None:
        self.sys = fresh()
        self.author = claims(T, "author")
        self.reviewer = claims(T, "rev_1", roles=("reviewer",))
        self.publisher = claims(T, "pub_actor", roles=("reviewer",))
        self.art = self.sys.generate_draft(
            principal=self.author,
            kind=DraftType.FAQ,
            collection_id="manuals",
            manufacturing_filters={"unconfirmed_items": [_FAQ_SENTENCE]},
        )

    def _approve(self) -> None:
        self.sys.assign_reviewer(tenant_id=T, artifact_id=self.art.artifact_id, reviewer_id="rev_1")
        self.sys.review_draft(
            tenant_id=T,
            artifact_id=self.art.artifact_id,
            reviewer=self.reviewer,
            decision="approved",
        )


class TestPublishOnlyFromApproved(_PublishBase):
    """Publish is reachable ONLY from status=approved; every other status errors, record untouched."""

    def _assert_publish_rejected(self) -> None:
        with self.assertRaises(InvalidTransitionError):
            self.sys.publish_draft(principal=self.publisher, artifact_id=self.art.artifact_id)
        stored = self.sys.get_draft(T, self.art.artifact_id)
        self.assertIsNone(stored.published_document_id, "a failed publish must not mark the draft")
        self.assertIsNone(
            self.sys._mvp.registry.get(T, f"pub_{self.art.artifact_id}"),
            "a rejected publish must not ingest a document",
        )

    def test_publish_from_fresh_draft_is_rejected(self) -> None:
        self._assert_publish_rejected()

    def test_publish_from_in_review_is_rejected(self) -> None:
        self.sys.assign_reviewer(tenant_id=T, artifact_id=self.art.artifact_id, reviewer_id="rev_1")
        self._assert_publish_rejected()

    def test_publish_from_rejected_is_rejected(self) -> None:
        self.sys.assign_reviewer(tenant_id=T, artifact_id=self.art.artifact_id, reviewer_id="rev_1")
        self.sys.review_draft(
            tenant_id=T,
            artifact_id=self.art.artifact_id,
            reviewer=self.reviewer,
            decision="rejected",
            comment="not correct",
        )
        self._assert_publish_rejected()


class TestPublishRequiresHumanActor(_PublishBase):
    """Hard Rule 1 carried through publish: only an attributable human principal can publish."""

    def test_unattributable_actor_cannot_publish(self) -> None:
        self._approve()
        for bad_actor in (None, claims(T, "")):
            with self.subTest(actor=bad_actor):
                with self.assertRaises(PermissionError):
                    # Exercise the service seam directly: the HTTP layer always builds the actor
                    # from the signed principal headers, so a body-supplied actor cannot exist.
                    self.sys._drafts.publish(
                        tenant_id=T,
                        artifact_id=self.art.artifact_id,
                        actor=bad_actor,
                        ingest=lambda **kw: self.fail(
                            "ingest must never run without a human actor"
                        ),
                    )
        stored = self.sys.get_draft(T, self.art.artifact_id)
        self.assertIsNone(stored.published_document_id)
        self.assertEqual(_status_value(stored), DraftStatus.APPROVED.value)


class TestPublishHappyPath(_PublishBase):
    def test_publish_marks_artifact_and_creates_approved_document(self) -> None:
        self._approve()
        published = self.sys.publish_draft(
            principal=self.publisher, artifact_id=self.art.artifact_id
        )
        # The artifact records the publish (and stays approved — publish is not a status rewrite).
        self.assertEqual(published.published_document_id, f"pub_{self.art.artifact_id}")
        self.assertEqual(published.published_by, "pub_actor")
        self.assertTrue(published.published_at)
        self.assertEqual(_status_value(published), DraftStatus.APPROVED.value)
        # The stored record agrees (the returned value is a detached copy).
        stored = self.sys.get_draft(T, self.art.artifact_id)
        self.assertEqual(stored.published_document_id, published.published_document_id)
        # The published document exists with approved+effective manufacturing metadata + provenance.
        meta = self.sys.get_mfg_meta(T, published.published_document_id)
        self.assertIsNotNone(meta, "published document must carry manufacturing metadata")
        self.assertEqual(meta.approval_status, ApprovalStatus.APPROVED)
        self.assertTrue(is_approved_effective(meta), "published knowledge must be effective now")
        self.assertEqual(meta.extra.get("published_from_draft_id"), self.art.artifact_id)
        self.assertEqual(meta.extra.get("approval_source_detail"), "draft_publish")
        self.assertEqual(meta.extra.get("draft_kind"), "faq")

    def test_second_publish_is_rejected_and_mints_no_second_document(self) -> None:
        self._approve()
        first = self.sys.publish_draft(principal=self.publisher, artifact_id=self.art.artifact_id)
        with self.assertRaises(InvalidTransitionError):
            self.sys.publish_draft(principal=self.publisher, artifact_id=self.art.artifact_id)
        stored = self.sys.get_draft(T, self.art.artifact_id)
        self.assertEqual(
            stored.published_document_id,
            first.published_document_id,
            "a second publish must not change the published document reference",
        )
        # Exactly one draft.published audit entry exists (no double publish slipped through).
        entries = self.sys.audit.read_all(claims(T, "admin"))
        publishes = [e for e in entries if e.action == "draft.published"]
        self.assertEqual(len(publishes), 1)

    def test_publish_is_recorded_in_the_hash_chain_audit(self) -> None:
        self._approve()
        published = self.sys.publish_draft(
            principal=self.publisher, artifact_id=self.art.artifact_id
        )
        admin = claims(T, "admin")
        entries = self.sys.audit.read_all(admin)
        publish_entries = [e for e in entries if e.action == "draft.published"]
        self.assertEqual(len(publish_entries), 1, "publish must be audited exactly once")
        e = publish_entries[0]
        self.assertEqual(e.actor_id, "pub_actor")  # the HUMAN publisher, attributably
        self.assertEqual(e.resource_type, "draft_artifact")
        self.assertEqual(e.resource_id, self.art.artifact_id)
        self.assertEqual(e.decision, "published")
        self.assertIn(published.published_document_id, e.document_ids_used)
        self.assertEqual(
            e.client_metadata.get("published_document_id"), published.published_document_id
        )
        # The audit log remains a tamper-evident intact hash chain after the publish write.
        self.assertTrue(self.sys.audit.verify_chain(admin))


class TestPublishedKnowledgeIsCitable(_PublishBase):
    """The point of publishing: the approved FAQ becomes answerable through the 001 answer path."""

    def test_published_faq_is_retrievable_and_cited_as_approved(self) -> None:
        self._approve()
        published = self.sys.publish_draft(
            principal=self.publisher, artifact_id=self.art.artifact_id
        )
        # Same 001 ACL rules as any other knowledge: grant the asker the publish collection.
        self.sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "op")
        op = claims(T, "op")
        ans = self.sys.answer(op, "what is the conveyor motor lubrication interval?")
        self.assertEqual(ans.status, "ok")
        cited = {c.document_id for c in ans.citations}
        self.assertIn(
            published.published_document_id,
            cited,
            "the published draft must be citable as answer evidence (issue 0019 DoD)",
        )
        pub_citation = next(
            c for c in ans.citations if c.document_id == published.published_document_id
        )
        self.assertEqual(pub_citation.approval_status, "approved")

    def test_unpublished_approved_draft_is_not_yet_knowledge(self) -> None:
        # Control: approval ALONE must not leak the draft into the answer path (publish is the
        # explicit boundary crossing).
        self._approve()
        self.sys.grant(T, ScopeType.COLLECTION, "manuals", SubjectType.USER, "op")
        ans = self.sys.answer(claims(T, "op"), "what is the conveyor motor lubrication interval?")
        cited = {c.document_id for c in ans.citations}
        self.assertNotIn(f"pub_{self.art.artifact_id}", cited)


if __name__ == "__main__":
    unittest.main()
