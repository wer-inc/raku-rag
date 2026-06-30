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
    def test_main_tombstones_existing_docs_before_reingest(self) -> None:
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

        def grant_demo_acl() -> tuple[str, int]:
            calls.append(("grant", "acl"))
            return "granted", 2

        with (
            patch.object(module, "DOCS", docs),
            patch.object(module, "delete_existing_doc", side_effect=delete_existing_doc),
            patch.object(module, "ingest", side_effect=ingest),
            patch.object(module, "grant_demo_acl", side_effect=grant_demo_acl),
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
                ("grant", "acl"),
            ],
        )
