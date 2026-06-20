"""P0-T22 — seed framework: idempotent, tenant-scoped, deny-by-default (sqlite smoke)."""

from __future__ import annotations

import sqlite3
import unittest

from raku_rag.seed.loader import SeedLoader, SeedSpec, default_local_seed_specs


class TestSeedLoader(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE tenant (tenant_id TEXT PRIMARY KEY, name TEXT)")

    def _spec(self) -> list[SeedSpec]:
        return [SeedSpec("tenant", ("tenant_id",), ({"tenant_id": "t1", "name": "T1"},))]

    def test_idempotent_apply(self) -> None:
        loader = SeedLoader(self.conn)
        self.assertEqual(loader.apply(self._spec())["tenant"], 1)  # inserted once
        self.assertEqual(loader.apply(self._spec())["tenant"], 0)  # second run: no dup
        n = self.conn.execute("SELECT count(*) FROM tenant").fetchone()[0]
        self.assertEqual(n, 1)

    def test_tenant_scoped_invariant(self) -> None:
        bad = [SeedSpec("tenant", ("tenant_id",), ({"tenant_id": "", "name": "x"},))]
        with self.assertRaises(ValueError):
            SeedLoader(self.conn).apply(bad)

    def test_default_seed_is_tenant_scoped_and_deny_by_default(self) -> None:
        specs = {s.table: s for s in default_local_seed_specs()}
        # every seeded row carries a tenant_id
        for spec in specs.values():
            for row in spec.rows:
                self.assertTrue(row.get("tenant_id"), spec.table)
        # deny-by-default: exactly one explicit ACL grant, nothing implicit
        self.assertEqual(len(specs["acl_grant"].rows), 1)
        # no-train default provider policy present
        pp = specs["provider_policy"].rows[0]
        self.assertEqual(pp["no_train_required"], 1)
        self.assertEqual(pp["zero_retention_required"], 1)


if __name__ == "__main__":
    unittest.main()
