# Vector Index DR and Reindex Runbook

**Date:** 2026-06-22  
**Owner:** platform on-call  
**Scope:** P2-6 local production-readiness closure for vector index recovery, embedding-space changes,
and retrieval freshness/recency behavior.

This runbook covers repo-side operating rules. Actual restore drills require the deployed Postgres /
pgvector cluster, object storage, and AWS backup configuration.

---

## 1. What can fail

| Failure | User symptom | Primary recovery |
|---|---|---|
| vector index missing/corrupt | slow retrieval, query plan falls back to scan | rebuild ANN/vector indexes, run EXPLAIN gate |
| chunk rows missing/corrupt | relevant docs disappear | restore DB snapshot or re-ingest source documents |
| embedding model/dimension changed | retrieval quality drops or insert rejects vectors | run planned reindex/backfill in the target embedding space |
| stale/deleted chunks returned | deleted/obsolete content appears | stop release, run deletion/citation probes, restore from known-good snapshot if data corruption |
| lexical/metadata index missing | exact id/code lookup degrades | rebuild metadata/lexical indexes and rerun exact-match tests |

## 2. Recovery order

1. **Contain:** freeze deploys and stop non-urgent ingestion/reindex jobs.
2. **Classify:** check whether the issue is DB/index structure, chunk data, embedding model mismatch,
   or retrieval application logic.
3. **Preserve evidence:** record release SHA, image digest, DB snapshot id, migration version,
   embedding model/dimension, and `version_registry`.
4. **Choose recovery path:**
   - index-only issue: rebuild indexes in place.
   - chunk/vector row corruption: restore DB snapshot to scratch, compare, then restore or re-ingest.
   - embedding change issue: execute `ReindexPlan`, do not hot-flip dimensions without a compatible
     index/table.
   - app regression: roll back image first, then re-evaluate data repair.
5. **Verify:** run Tier A, eval security probes, golden corpus, EXPLAIN gate, and a smoke query with
   expected citations.

## 3. Index rebuild checklist

Run in a maintenance window for production-sized corpora:

1. Confirm the current migration set is applied.
2. Rebuild vector/lexical/metadata indexes concurrently where supported.
3. Run `ANALYZE` on chunks/documents.
4. Run the EXPLAIN gate and verify the planner does not fall back to a sequential scan for the
   production retrieval shapes.
5. Run exact identifier lookup smoke tests for equipment id / alarm code / document metadata filters.
6. Run golden-corpus eval and compare to the committed baseline.

Do not mark the incident resolved until retrieval quality and latency are both inside budget.

## 4. Reindex/backfill policy

Embedding provider or dimension changes are data migrations:

- The selected provider/dimension must be explicit in settings and eval `version_registry`.
- If the new dimension is incompatible with the current vector column/index, create a parallel
  embedding/index path or run a planned migration. Do not mix dimensions in one index.
- Reindex/backfill is chunk-scoped and idempotent. Source text checksum can remain unchanged, but
  `embedding_model_version`, `embedding_dimension`, or `chunking_config_version` changes force
  re-embedding/rechunking.
- After backfill, refresh the committed golden baseline only after SME/release-captain approval.
- Keep the previous image/config and previous vector snapshot until the new baseline and load gates
  pass.

## 5. Freshness and recency checks

The retrieval path already includes bounded recency/metadata-aware candidate union. DR validation must
prove that this still works after restore/reindex:

- newly approved effective documents can be found.
- obsolete/tombstoned documents are excluded.
- document metadata filters still apply before answer generation.
- recency boost changes ranking only within the allowed retrieval profile, not ACL visibility.

## 6. Restore drill

Quarterly or before public launch:

1. Restore the latest production RDS snapshot to a scratch cluster.
2. Apply migrations to the expected release version.
3. Rebuild vector/lexical indexes and run `ANALYZE`.
4. Deploy the current app image against the scratch cluster.
5. Run Tier B, EXPLAIN gate, golden corpus, deletion/tenant/ACL/source-poisoning probes, and a
   representative load smoke.
6. Record restore time, reindex time, p95/p99, and any manual steps. Feed gaps back into this runbook.

Initial DR targets until measured:

- RPO: latest RDS automated snapshot plus source object store durability.
- RTO: 4 hours for app rollback, 8 hours for DB restore + vector index rebuild on the first production
  scale tier.

