from __future__ import annotations

import importlib
import os
import unittest

from raku_rag.dagster import DagsterPartitionKey, dagster_run_url, parse_partition_key

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class TestDagsterSkeleton(unittest.TestCase):
    def test_required_control_plane_packages_exist(self) -> None:
        for package in ["assets", "resources", "jobs", "sensors", "schedules", "checks"]:
            path = os.path.join(ROOT, "src", "raku_rag", "dagster", package)
            self.assertTrue(os.path.isdir(path), f"missing dagster package: {package}")
            importlib.import_module(f"raku_rag.dagster.{package}")

    def test_partition_key_round_trips_and_emits_tags(self) -> None:
        partition = DagsterPartitionKey(
            tenant_id="tenant/a",
            collection_id="manuals",
            source_id="s3://bucket/source",
            sync_run_id="sync 001",
        )

        parsed = parse_partition_key(partition.to_key())

        self.assertEqual(parsed, partition)
        self.assertEqual(parsed.tags()["tenant_id"], "tenant/a")
        self.assertEqual(parsed.tags()["sync_run_id"], "sync 001")

    def test_dagster_run_url_escapes_run_id(self) -> None:
        self.assertEqual(
            dagster_run_url("https://dagster.example/", "run 1/2"),
            "https://dagster.example/runs/run%201%2F2",
        )

    def test_online_answer_search_paths_do_not_import_dagster(self) -> None:
        for rel in ["src/raku_rag/services/answer.py", "src/raku_rag/services/retrieval.py"]:
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                self.assertNotIn("raku_rag.dagster", fh.read())


if __name__ == "__main__":
    unittest.main()
