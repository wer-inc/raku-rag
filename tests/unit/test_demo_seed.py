from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "scripts" / "demo" / "demo_seed.py"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("demo_seed", SEED)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load demo_seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDemoSeed(TestCase):
    def test_select_purge_ids_preserves_user_uploads_and_connector_syncs(self) -> None:
        # The core safety guarantee: a re-seed may only tombstone docs the seed OWNS (curated ids +
        # seed source_ids). User uploads ("file-*") and connector syncs must survive — a deploy-time
        # re-seed wiping them is the deploy-seed-wipes-user-uploads incident this guards against.
        module = _load_seed_module()
        existing = [
            {"document_id": "seed-stale", "source_id": "work_instruction"},  # old seed doc -> purge
            {"document_id": "AK_upload", "source_id": "file-manuals"},  # user upload -> PRESERVE
            {"document_id": "confluence-42", "source_id": "confluence"},  # connector -> PRESERVE
        ]
        with patch.object(module, "SEED_SOURCE_IDS", {"work_instruction", "demo", "case"}):
            purge_ids, preserved = module.select_purge_ids(existing, {"m1"})

        self.assertEqual(purge_ids, ["m1", "seed-stale"])
        self.assertEqual(
            {entry["document_id"] for entry in preserved}, {"AK_upload", "confluence-42"}
        )

    def test_main_tombstones_seed_docs_but_never_user_uploads(self) -> None:
        module = _load_seed_module()
        docs = (
            {
                "document_id": "d1",
                "approval_status": "approved",
                "document_kind": "work_instruction",
            },
            {"document_id": "d2", "approval_status": "draft", "document_kind": "inspection"},
        )
        existing = [
            {"document_id": "d1", "source_id": "work_instruction"},  # curated + still present
            {"document_id": "stale-seed", "source_id": "inspection"},  # seed-owned stale -> purge
            {"document_id": "AK_upload", "source_id": "file-manuals"},  # USER UPLOAD -> preserve
        ]
        calls: list[tuple[str, str]] = []

        def delete_existing_doc(document_id: str) -> tuple[str, int]:
            calls.append(("delete", document_id))
            return "succeeded", 1

        def ingest(doc: dict) -> tuple[str, int]:
            calls.append(("ingest", doc["document_id"]))
            return "succeeded", 1

        with (
            patch.object(module, "DOCS", docs),
            patch.object(
                module, "SEED_SOURCE_IDS", {"work_instruction", "inspection", "demo", "case"}
            ),
            patch.object(module, "delete_existing_doc", side_effect=delete_existing_doc),
            patch.object(
                module, "list_existing_collection_docs", return_value=("listed", existing)
            ),
            patch.object(module, "ingest", side_effect=ingest),
            patch.object(module, "grant_demo_acl", return_value=("granted", 2)),
            patch("builtins.print"),
        ):
            module.main()

        deletes = [document_id for kind, document_id in calls if kind == "delete"]
        self.assertEqual(deletes, ["d1", "d2", "stale-seed"])  # sorted(curated ∪ seed-owned)
        self.assertNotIn("AK_upload", deletes)  # the incident invariant: uploads survive a re-seed
        self.assertEqual(
            [document_id for kind, document_id in calls if kind == "ingest"], ["d1", "d2"]
        )

    def test_main_falls_back_to_curated_docs_when_collection_list_fails(self) -> None:
        module = _load_seed_module()
        docs = (
            {"document_id": "d1", "approval_status": "approved"},
            {"document_id": "d2", "approval_status": "draft"},
        )
        calls: list[tuple[str, str]] = []

        def delete_existing_doc(document_id: str) -> tuple[str, int]:
            calls.append(("delete", document_id))
            return "succeeded", 1

        def ingest(doc: dict) -> tuple[str, int]:
            calls.append(("ingest", doc["document_id"]))
            return "succeeded", 1

        with (
            patch.object(module, "DOCS", docs),
            patch.object(module, "delete_existing_doc", side_effect=delete_existing_doc),
            patch.object(module, "list_existing_collection_docs", return_value=("ERROR", "boom")),
            patch.object(module, "ingest", side_effect=ingest),
            patch.object(module, "grant_demo_acl", return_value=("granted", 2)),
            patch("builtins.print"),
        ):
            module.main()

        self.assertEqual(
            calls,
            [
                ("delete", "d1"),
                ("delete", "d2"),
                ("ingest", "d1"),
                ("ingest", "d2"),
            ],
        )
