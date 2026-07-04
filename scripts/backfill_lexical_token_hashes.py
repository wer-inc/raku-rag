#!/usr/bin/env python3
"""Backfill the 0026 ingest-time retrieval columns (Wave 1d search-path performance):
chunks.lexical_token_hashes, chunks.identifier_compacts, documents.identifier_compacts.

Rows ingested before 0026 carry the '{}' default and make the lexical retrieval leg fall back to
the exhaustive (pre-1d, slow-but-exact) path for their whole tenant — see
persistence/postgres.py::lexical_matches. This script computes the ingest-time token hashes
(core/hybrid_retrieval.lexical_token_hashes — the SAME function the store's upsert uses, so
backfilled and freshly-ingested rows are indistinguishable) for every live row that still has the
sentinel value. Idempotent; safe to re-run; batched.

Usage:
    POSTGRES_URL=postgresql://<user>:<password>@127.0.0.1:5432/<db> \
        python3 scripts/backfill_lexical_token_hashes.py [--batch 500] [--dry-run]

Runs as the connecting user WITHOUT dropping to the RLS app role: the backfill is a maintenance
operation across all tenants (same posture as scripts/pg-migrate.sh).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from raku_rag.core.hybrid_retrieval import (  # noqa: E402
    lexical_token_hashes,
    metadata_hot_identifier_compacts,
)


def _load_jsonish(value):
    import json

    if value is None:
        return None
    return json.loads(value) if isinstance(value, str) else value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dsn = os.environ.get("POSTGRES_URL", "")
    if not dsn:
        print("set POSTGRES_URL to the target database", file=sys.stderr)
        return 2

    import psycopg

    updated = 0
    with psycopg.connect(dsn, autocommit=True) as conn:
        # 1. lexical token hashes ('{}' = un-backfilled sentinel; text-less rows excluded).
        while True:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT chunk_id, text FROM chunks "
                    "WHERE lexical_token_hashes = '{}' AND text <> '' "
                    "ORDER BY chunk_id LIMIT %s",
                    (args.batch,),
                )
                rows = cur.fetchall()
            if not rows:
                break
            if args.dry_run:
                print(f"[dry-run] would backfill {len(rows)} token-hash rows (first: {rows[0][0]})")
                break
            with conn.cursor() as cur:
                for chunk_id, text in rows:
                    # lexical_token_hashes returns the [0] marker for token-less non-empty text,
                    # so a backfilled row can never look like the '{}' un-backfilled sentinel.
                    cur.execute(
                        "UPDATE chunks SET lexical_token_hashes = %s::int4[] "
                        "WHERE chunk_id = %s",
                        (lexical_token_hashes(text), chunk_id),
                    )
            updated += len(rows)
            print(f"[backfill] token hashes: {updated} rows done")
        # 2. identifier compacts (NULL = never computed; '{}' = computed, no identifiers).
        for table, key in (("chunks", "chunk_id"), ("documents", "document_id")):
            while True:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT {key}, metadata FROM {table} "
                        "WHERE identifier_compacts IS NULL "
                        f"ORDER BY {key} LIMIT %s",
                        (args.batch,),
                    )
                    rows = cur.fetchall()
                if not rows:
                    break
                if args.dry_run:
                    print(f"[dry-run] would backfill {len(rows)} {table}.identifier_compacts rows")
                    break
                with conn.cursor() as cur:
                    for row_id, metadata in rows:
                        cur.execute(
                            f"UPDATE {table} SET identifier_compacts = %s::text[] "
                            f"WHERE {key} = %s",
                            (
                                metadata_hot_identifier_compacts(_load_jsonish(metadata) or {}),
                                row_id,
                            ),
                        )
                updated += len(rows)
                print(f"[backfill] {table} identifier compacts: batch of {len(rows)} done")
    print(f"[backfill] complete: {updated} rows updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
