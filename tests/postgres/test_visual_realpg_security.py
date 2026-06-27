"""Tier B (real Postgres) visual RLS/deletion parity.

These tests are skip-safe without a local Postgres, but when Tier B is available they pin the
production visual path that Tier A's in-memory checks cannot prove:

1. visual chunks written through ``ProductionSystem.ingest_document(image/*)`` are RLS-scoped, then
   disappear through the deletion/tombstone cascade together with inherited crops.
2. the visual artifact tables introduced by 0002 remain tenant-scoped through RLS.
"""

from __future__ import annotations

import os
from uuid import uuid4
import unittest

from raku_rag.domain.models import BoundingBox, JobStatus, LayoutRegion, ScopeType, SubjectType
from tests.helpers import claims

DSN = os.environ.get("POSTGRES_URL", "postgresql://raku:raku@127.0.0.1:5432/raku_parity")


def _postgres_visual_tables_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='public' "
                    "AND table_name IN ('chunks','visual_assets','layout_regions','crops')"
                )
                return cur.fetchone()[0] == 4
    except Exception:
        return False


@unittest.skipUnless(
    _postgres_visual_tables_available(),
    "Visual Postgres tables not reachable (Tier B / visual migrations required)",
)
class TestVisualRealPgSecurity(unittest.TestCase):
    def setUp(self) -> None:
        from raku_rag.production import ProductionSystem

        self.sys = ProductionSystem(DSN, reset=True)
        self.addCleanup(self.sys.close)
        self.suffix = uuid4().hex[:10]
        self.tenant_a = f"visual_pg_a_{self.suffix}"
        self.tenant_b = f"visual_pg_b_{self.suffix}"

    def test_visual_chunks_are_rls_scoped_and_delete_cascades_to_crops(self) -> None:
        document_id = f"visual_doc_{self.suffix}"
        run = self.sys.ingest_document(
            tenant_id=self.tenant_a,
            collection_id=f"visual_manuals_{self.suffix}",
            source_id="image_upload",
            document_id=document_id,
            document_ref=f"s3://documents/{self.tenant_a}/{document_id}.png",
            raw=(
                b"OCR: Pump panel shows alarm AL-42.\n"
                b"caption: Pump panel with emergency stop label."
            ),
            content_type="image/png",
        )
        self.assertEqual(run.status, JobStatus.SUCCEEDED.value)

        chunks = self.sys.store.visual_chunks_for_document(self.tenant_a, document_id)
        self.assertTrue(chunks, "image ingestion must persist visual chunks to Postgres")
        asset_id = str(chunks[0].metadata["asset_id"])
        self._assert_visual_chunk_count(document_id, tenant_id=self.tenant_a, expected_min=1)
        self._assert_visual_chunk_count(document_id, tenant_id=self.tenant_b, expected_exact=0)

        self.sys.grant(
            self.tenant_a,
            ScopeType.COLLECTION,
            f"visual_manuals_{self.suffix}",
            SubjectType.USER,
            "alice",
        )
        crop = self.sys.crops.create_region_crop(_region_from_chunk(chunks[0]))

        result = self.sys.deletion.delete(self.tenant_a, document_id)

        self.assertGreaterEqual(result.tombstoned_chunks, 1)
        self.assertGreaterEqual(result.purged_chunks, 1)
        self.assertEqual(result.tombstoned_crops, 1)
        self.assertEqual(self.sys.store.visual_chunks_for_document(self.tenant_a, document_id), ())
        self.assertIsNone(self.sys.crops.store.get(self.tenant_a, crop.crop_id))
        self.assertIsNone(
            self.sys.assets.get_visual_asset(claims(self.tenant_a, "alice"), asset_id)
        )

    def test_visual_artifact_tables_are_tenant_scoped_by_rls(self) -> None:
        coll_a = f"visual_rls_coll_a_{self.suffix}"
        coll_b = f"visual_rls_coll_b_{self.suffix}"
        doc_a = f"visual_rls_doc_a_{self.suffix}"
        doc_b = f"visual_rls_doc_b_{self.suffix}"
        self.sys.ingest_text(
            tenant_id=self.tenant_a,
            collection_id=coll_a,
            document_id=doc_a,
            text="Tenant A parent document for visual artifact rows.",
        )
        self.sys.ingest_text(
            tenant_id=self.tenant_b,
            collection_id=coll_b,
            document_id=doc_b,
            text="Tenant B parent document for visual artifact rows.",
        )

        ids_a = self._insert_visual_artifacts(self.tenant_a, coll_a, doc_a, "a")
        ids_b = self._insert_visual_artifacts(self.tenant_b, coll_b, doc_b, "b")

        for table, key_column, key_value in (
            ("visual_assets", "asset_id", ids_a["asset_id"]),
            ("layout_regions", "region_id", ids_a["region_id"]),
            ("crops", "crop_id", ids_a["crop_id"]),
        ):
            with self.subTest(table=table):
                self.assertEqual(self._row_count(table, key_column, key_value, self.tenant_a), 1)
                self.assertEqual(self._row_count(table, key_column, key_value, self.tenant_b), 0)

        self.assertEqual(
            self._row_count("visual_assets", "asset_id", ids_b["asset_id"], self.tenant_b),
            1,
        )

    def _assert_visual_chunk_count(
        self,
        document_id: str,
        *,
        tenant_id: str,
        expected_min: int | None = None,
        expected_exact: int | None = None,
    ) -> None:
        with self.sys._conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (tenant_id,))
            cur.execute(
                "SELECT count(*) FROM chunks WHERE document_id = %s AND modality = 'visual'",
                (document_id,),
            )
            count = cur.fetchone()[0]
        if expected_exact is not None:
            self.assertEqual(count, expected_exact)
        if expected_min is not None:
            self.assertGreaterEqual(count, expected_min)

    def _insert_visual_artifacts(
        self, tenant_id: str, collection_id: str, document_id: str, suffix: str
    ) -> dict[str, str]:
        asset_id = f"asset_{suffix}_{self.suffix}"
        region_id = f"region_{suffix}_{self.suffix}"
        crop_id = f"crop_{suffix}_{self.suffix}"
        with self.sys._conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (tenant_id,))
            cur.execute(
                "INSERT INTO visual_assets "
                "(asset_id, tenant_id, collection_id, document_id, source_id, storage_uri, "
                "checksum, content_type, page_number) "
                "VALUES (%s,%s,%s,%s,'visual_test',%s,'checksum','image/png',1)",
                (
                    asset_id,
                    tenant_id,
                    collection_id,
                    document_id,
                    f"s3://visual/{tenant_id}/{asset_id}.png",
                ),
            )
            cur.execute(
                "INSERT INTO layout_regions "
                "(region_id, tenant_id, collection_id, document_id, asset_id, page_number, "
                "region_type, bbox, ocr_text, crop_uri, metadata) "
                "VALUES (%s,%s,%s,%s,%s,1,'text',%s::jsonb,'AL-42',%s,%s::jsonb)",
                (
                    region_id,
                    tenant_id,
                    collection_id,
                    document_id,
                    asset_id,
                    '{"x":0.1,"y":0.1,"width":0.4,"height":0.2}',
                    f"s3://visual/{tenant_id}/{crop_id}.png",
                    '{"structured_content":{"kind":"ocr_region"}}',
                ),
            )
            cur.execute(
                "INSERT INTO crops "
                "(crop_id, tenant_id, collection_id, document_id, asset_id, region_id, "
                "bbox, crop_uri, redaction_policy_ref, metadata) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'inherit',%s::jsonb)",
                (
                    crop_id,
                    tenant_id,
                    collection_id,
                    document_id,
                    asset_id,
                    region_id,
                    '{"x":0.1,"y":0.1,"width":0.4,"height":0.2}',
                    f"s3://visual/{tenant_id}/{crop_id}.png",
                    '{"inherits_acl_from_document_id":"doc"}',
                ),
            )
        return {"asset_id": asset_id, "region_id": region_id, "crop_id": crop_id}

    def _row_count(self, table: str, key_column: str, key_value: str, tenant_id: str) -> int:
        with self.sys._conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (tenant_id,))
            cur.execute(f"SELECT count(*) FROM {table} WHERE {key_column} = %s", (key_value,))
            return int(cur.fetchone()[0])


def _region_from_chunk(chunk) -> LayoutRegion:
    raw_bbox = chunk.metadata.get("bbox") or {}
    bbox = BoundingBox(
        x=float(raw_bbox.get("x", 0.0)),
        y=float(raw_bbox.get("y", 0.0)),
        width=float(raw_bbox.get("width", 1.0)),
        height=float(raw_bbox.get("height", 1.0)),
    )
    return LayoutRegion(
        tenant_id=chunk.tenant_id,
        collection_id=chunk.collection_id,
        document_id=chunk.document_id,
        asset_id=str(chunk.metadata.get("asset_id") or ""),
        region_id=str(chunk.metadata.get("region_id") or chunk.chunk_id),
        bbox=bbox,
        page_number=int(chunk.metadata.get("page_number") or 1),
        region_type=str(chunk.metadata.get("region_type") or "text"),
        heading_path=chunk.heading_path,
        ocr_text=str(chunk.metadata.get("ocr_text") or ""),
        generated_caption_text=str(chunk.metadata.get("generated_caption_text") or ""),
        crop_uri=str(chunk.metadata.get("crop_uri") or ""),
        metadata=dict(chunk.metadata),
        tombstone=chunk.tombstone,
    )


if __name__ == "__main__":
    unittest.main()
