"""Migration discipline contract.

The real Postgres migrations are intentionally lightweight SQL files, but the release process still
needs mechanical protection against the expensive failures: skipped numbers, missing rollback files,
and smoke scripts that forget to apply the newest migration.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_MIGRATIONS = ROOT / "infra/db/migrations/postgres"
RUNNER = ROOT / "src/raku_rag/migrations/runner.py"
PG_MIGRATE = ROOT / "scripts/pg-migrate.sh"
MIGRATION_SMOKE = ROOT / "scripts/postgres-migration-smoke.sh"


def _up_migrations() -> list[Path]:
    return sorted(
        path
        for path in POSTGRES_MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")
        if not path.name.endswith(".down.sql")
    )


class MigrationDisciplineContractTest(unittest.TestCase):
    def test_postgres_migrations_are_contiguous_and_unique(self) -> None:
        migrations = _up_migrations()
        versions = [path.name[:4] for path in migrations]
        self.assertEqual(len(versions), len(set(versions)), "duplicate migration version found")
        expected = [f"{i:04d}" for i in range(1, len(versions) + 1)]
        self.assertEqual(
            versions,
            expected,
            "Postgres migration versions must be contiguous from 0001 with no gaps",
        )

    def test_every_postgres_migration_has_down_pair(self) -> None:
        missing = [
            path.name for path in _up_migrations() if not path.with_suffix(".down.sql").exists()
        ]
        self.assertEqual(missing, [], "every Postgres migration needs a paired .down.sql")

    def test_runner_and_pg_migrate_record_applied_versions(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        shell_runner = PG_MIGRATE.read_text(encoding="utf-8")
        for text, name in ((runner, "Python runner"), (shell_runner, "Postgres shell runner")):
            with self.subTest(runner=name):
                self.assertIn("schema_migrations", text)
                self.assertRegex(text, re.compile(r"CREATE TABLE IF NOT EXISTS .*schema_migrations", re.S))
                self.assertIn("PRIMARY KEY", text)

    def test_postgres_migration_smoke_discovers_all_numbered_migrations(self) -> None:
        smoke = MIGRATION_SMOKE.read_text(encoding="utf-8")
        self.assertIn("up_migrations", smoke)
        self.assertIn("find infra/db/migrations/postgres", smoke)
        self.assertIn("! -name '*.down.sql'", smoke)
        self.assertIn("for ((i=${#up_migrations[@]} - 1; i >= 0; i--))", smoke)
        for path in _up_migrations():
            with self.subTest(migration=path.name):
                self.assertTrue(
                    path.with_suffix(".down.sql").exists(),
                    f"{path.name} must rollback in smoke via its down pair",
                )


if __name__ == "__main__":
    unittest.main()
