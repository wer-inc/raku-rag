"""P0-T18 — DB-agnostic SQL migration runner (framework only; RT2 at framework level).

Phase 0 delivers the runner (discover / apply / record / idempotent + CLI). Phase 1 (P1-T01/T02+)
adds the real Postgres+pgvector migrations under ``infra/db/migrations``. The runner takes any
DB-API 2.0 connection; the local smoke uses stdlib ``sqlite3`` so it runs with no external service.

A migration is a ``NNNN_name.sql`` file. Applied versions are recorded in ``schema_migrations`` so
re-running is a no-op (idempotent).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: str  # filename without extension, e.g. "0001_core"
    path: str
    sql: str


def discover(migrations_dir: str) -> list[Migration]:
    """Return migrations sorted by filename (lexical order == apply order)."""
    out: list[Migration] = []
    if not os.path.isdir(migrations_dir):
        return out
    for name in sorted(os.listdir(migrations_dir)):
        if not name.endswith(".sql"):
            continue
        path = os.path.join(migrations_dir, name)
        with open(path, encoding="utf-8") as fh:
            out.append(Migration(version=name[:-4], path=path, sql=fh.read()))
    return out


def _apply_sql(conn, sql: str) -> None:
    """Execute a (possibly multi-statement) SQL script across DB-API drivers."""
    executescript = getattr(conn, "executescript", None)
    if callable(executescript):  # sqlite3 fast path
        executescript(sql)
        return
    cur = conn.cursor()
    cur.execute(sql)
    cur.close()


class MigrationRunner:
    def __init__(self, conn, migrations_dir: str) -> None:
        self._conn = conn
        self._dir = migrations_dir

    def _ensure_ledger(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version TEXT PRIMARY KEY,"
            "  applied_at TEXT NOT NULL"
            ")"
        )
        self._conn.commit()

    def applied_versions(self) -> set[str]:
        self._ensure_ledger()
        cur = self._conn.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}

    def apply(self) -> list[str]:
        """Apply pending migrations in order. Returns the versions newly applied (empty if none)."""
        self._ensure_ledger()
        done = self.applied_versions()
        newly: list[str] = []
        for mig in discover(self._dir):
            if mig.version in done:
                continue
            _apply_sql(self._conn, mig.sql)
            self._conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (mig.version, _dt.datetime.now(_dt.timezone.utc).isoformat()),
            )
            self._conn.commit()
            newly.append(mig.version)
        return newly


def _open(db: str):
    """Open a connection. Phase 0 smoke uses sqlite; a postgres:// URL needs psycopg (Phase 1)."""
    if db.startswith("postgres://") or db.startswith("postgresql://"):
        try:
            import psycopg  # type: ignore
        except Exception as exc:  # pragma: no cover - psycopg not installed in Phase 0
            raise SystemExit(
                "postgres URL requires psycopg (Phase 1 dependency); use a sqlite path for the "
                "Phase 0 smoke"
            ) from exc
        return psycopg.connect(db)
    return sqlite3.connect(db)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="raku-rag migration runner (Phase 0 framework)")
    ap.add_argument("--dir", default="infra/db/migrations", help="migrations directory")
    ap.add_argument("--db", default=".local/dev.sqlite", help="sqlite path or postgres URL")
    args = ap.parse_args(argv)
    (
        os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
        if not args.db.startswith(("postgres://", "postgresql://"))
        else None
    )
    conn = _open(args.db)
    runner = MigrationRunner(conn, args.dir)
    applied = runner.apply()
    if applied:
        print(f"applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        print("no pending migrations (up to date)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
