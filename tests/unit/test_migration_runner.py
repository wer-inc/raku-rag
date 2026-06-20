"""P0-T17 — migration runner framework + idempotency (RT2 at framework level, sqlite smoke)."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from raku_rag.migrations.runner import MigrationRunner, discover


class TestMigrationRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self._write("0001_a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
        self._write("0002_b.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY);")
        self.conn = sqlite3.connect(":memory:")

    def _write(self, name: str, sql: str) -> None:
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
            fh.write(sql)

    def test_discover_is_ordered(self) -> None:
        self.assertEqual([m.version for m in discover(self.dir)], ["0001_a", "0002_b"])

    def test_apply_then_idempotent(self) -> None:
        runner = MigrationRunner(self.conn, self.dir)
        applied = runner.apply()
        self.assertEqual(applied, ["0001_a", "0002_b"])  # both applied in order
        # tables exist
        names = {
            r[0]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertIn("a", names)
        self.assertIn("b", names)
        # ledger recorded
        self.assertEqual(runner.applied_versions(), {"0001_a", "0002_b"})
        # re-apply is a no-op (idempotent)
        self.assertEqual(runner.apply(), [])

    def test_new_migration_applied_on_rerun(self) -> None:
        runner = MigrationRunner(self.conn, self.dir)
        runner.apply()
        self._write("0003_c.sql", "CREATE TABLE c (id INTEGER PRIMARY KEY);")
        self.assertEqual(runner.apply(), ["0003_c"])  # only the new one


if __name__ == "__main__":
    unittest.main()
