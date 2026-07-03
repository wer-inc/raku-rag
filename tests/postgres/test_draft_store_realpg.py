"""Tier-B: PostgresDraftStore durability + tenant isolation over real Postgres (issue 0012).

SKIPPED unless a Postgres with the manufacturing_draft_artifacts table is reachable (Tier B /
local-only), mirroring the other tests/postgres/* smokes. Proves the AI-draft review queue is durable
across store instances (= survives an answer-service restart / is shared across Fargate tasks), which
the process-local InMemoryDraftStore cannot guarantee.
"""

from __future__ import annotations

import os
import unittest
import uuid

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")


def _draft_table_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'manufacturing_draft_artifacts'"
            )
            return cur.fetchone() is not None
    except Exception:
        return False


@unittest.skipUnless(
    _draft_table_available(),
    "manufacturing_draft_artifacts not reachable (Tier B / manufacturing migrations required)",
)
class TestPostgresDraftStoreDurability(unittest.TestCase):
    def setUp(self) -> None:
        import psycopg

        from raku_rag.manufacturing.domain.draft import (
            CreatedBy,
            DraftArtifact,
            DraftStatus,
            DraftType,
        )
        from raku_rag.persistence.manufacturing_drafts import PostgresDraftStore

        self._psycopg = psycopg
        self._DraftArtifact = DraftArtifact
        self._DraftStatus = DraftStatus
        self._DraftType = DraftType
        self._CreatedBy = CreatedBy
        self._Store = PostgresDraftStore
        self.tenant = f"t_{uuid.uuid4().hex[:8]}"
        self.other = f"t_{uuid.uuid4().hex[:8]}"
        # Register cleanup up-front so a FAILED assertion can't leave orphan rows in the shared DB.
        self.addCleanup(self._purge)
        # NOTE: these tests deliberately do NOT drive a draft to `approved`. The
        # manufacturing_draft_artifacts CHECK `NOT (created_by='ai' AND status='approved')` currently
        # rejects a legitimately human-approved AI draft (issue 0012); the store is therefore not wired
        # in production until that constraint is corrected by a (human-approved) migration. Add an
        # approve-path round-trip assertion here once the migration lands.

    def _conn(self):
        return self._psycopg.connect(DSN, autocommit=True)

    def _artifact(self, store, tenant: str):
        return self._DraftArtifact(
            tenant_id=tenant,
            artifact_id=store.next_id(),
            type=self._DraftType.CHECKLIST,
            created_by=self._CreatedBy.AI,
            created_at="2026-06-28T00:00:00+00:00",
            source_document_ids=("doc_a", "doc_b"),
            source_citations=("doc_a#0",),
            template_id="tmpl_1",
            collection_id="c1",
            content={"items": ["step 1"], "notice": "draft"},
        )

    def test_draft_survives_a_fresh_store_instance(self) -> None:
        # Write with one store/connection, read with a DIFFERENT store/connection — the equivalent of
        # an answer-service restart or a second Fargate task. The in-memory store would return None.
        with self._conn() as w:
            writer = self._Store(w)
            art = self._artifact(writer, self.tenant)
            writer.add(art)
            aid = art.artifact_id

        with self._conn() as r:
            reader = self._Store(r)
            got = reader.get(self.tenant, aid)
            self.assertIsNotNone(got, "draft must persist across store instances (0012)")
            self.assertEqual(got.status, self._DraftStatus.DRAFT)
            self.assertEqual(got.type, self._DraftType.CHECKLIST)
            self.assertEqual(got.source_document_ids, ("doc_a", "doc_b"))
            # payload-carried fields survive the round-trip
            self.assertEqual(got.template_id, "tmpl_1")
            self.assertEqual(got.collection_id, "c1")
            self.assertEqual(got.content.get("items"), ["step 1"])

        self._cleanup(aid)

    def test_save_persists_a_mutation_across_instances(self) -> None:
        with self._conn() as w:
            writer = self._Store(w)
            art = self._artifact(writer, self.tenant)
            writer.add(art)
            aid = art.artifact_id
            # mutate (assign-style) and save
            loaded = writer.get(self.tenant, aid)
            loaded.status = self._DraftStatus.IN_REVIEW
            loaded.reviewer_id = "carol"
            loaded.review_comment = "looks good"
            writer.save(loaded)

        with self._conn() as r:
            got = self._Store(r).get(self.tenant, aid)
            self.assertEqual(got.status, self._DraftStatus.IN_REVIEW)
            self.assertEqual(got.reviewer_id, "carol")
            self.assertEqual(got.review_comment, "looks good")

        self._cleanup(aid)

    def test_publish_fields_round_trip_in_payload(self) -> None:
        # issue 0019 — published_document_id / published_by / published_at ride in the payload jsonb
        # (no schema migration) and must survive a fresh-store read. The artifact deliberately stays
        # in_review here: the CHECK `NOT (created_by='ai' AND status='approved')` still blocks a
        # human-approved AI draft (issue 0012), so this pins ONLY the payload carriage of the fields.
        with self._conn() as w:
            writer = self._Store(w)
            art = self._artifact(writer, self.tenant)
            writer.add(art)
            aid = art.artifact_id
            loaded = writer.get(self.tenant, aid)
            loaded.status = self._DraftStatus.IN_REVIEW
            loaded.published_document_id = f"pub_{aid}"
            loaded.published_by = "carol"
            loaded.published_at = "2026-07-03T00:00:00+00:00"
            writer.save(loaded)

        with self._conn() as r:
            got = self._Store(r).get(self.tenant, aid)
            self.assertEqual(got.published_document_id, f"pub_{aid}")
            self.assertEqual(got.published_by, "carol")
            self.assertEqual(got.published_at, "2026-07-03T00:00:00+00:00")

        self._cleanup(aid)

    def test_list_filters_and_tenant_isolation(self) -> None:
        with self._conn() as w:
            store = self._Store(w)
            a = self._artifact(store, self.tenant)
            store.add(a)
            b = self._artifact(store, self.tenant)
            b.status = self._DraftStatus.IN_REVIEW
            b.reviewer_id = "carol"
            store.add(b)
            # a draft for a DIFFERENT tenant must never appear in this tenant's queue
            other = self._artifact(store, self.other)
            store.add(other)
            ids = (a.artifact_id, b.artifact_id, other.artifact_id)

        with self._conn() as r:
            store = self._Store(r)
            all_mine = {d.artifact_id for d in store.list(self.tenant)}
            self.assertIn(a.artifact_id, all_mine)
            self.assertIn(b.artifact_id, all_mine)
            self.assertNotIn(other.artifact_id, all_mine)  # tenant isolation
            in_review = store.list(self.tenant, status="in_review")
            self.assertEqual({d.artifact_id for d in in_review}, {b.artifact_id})
            mine = store.list(self.tenant, reviewer_id="carol")
            self.assertEqual({d.artifact_id for d in mine}, {b.artifact_id})

        self._cleanup(*ids)

    def _purge(self) -> None:
        with self._conn() as c, c.cursor() as cur:
            for tenant in (self.tenant, self.other):
                cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (tenant,))
                cur.execute(
                    "DELETE FROM manufacturing_draft_artifacts WHERE tenant_id = %s",
                    (tenant,),
                )

    def _cleanup(self, *artifact_ids: str) -> None:
        with self._conn() as c, c.cursor() as cur:
            for tenant in (self.tenant, self.other):
                cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (tenant,))
                cur.execute(
                    "DELETE FROM manufacturing_draft_artifacts WHERE artifact_id = ANY(%s)",
                    (list(artifact_ids),),
                )


if __name__ == "__main__":
    unittest.main()
