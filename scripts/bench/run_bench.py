#!/usr/bin/env python3
"""Wave 1a scale benchmark: retrieval quality + latency at 3,000-10,000 documents.

Two modes:

``--mode local`` (what CI-adjacent measurement runs — no paid providers):
    In-process against ``ProductionSystem`` over local Postgres with the deterministic hashing
    embedder. Measures the RETRIEVAL PIPELINE MECHANICS at scale: ingest throughput,
    recall@5/recall@10/MRR@10/nDCG@10 (doc-level, per query slice), and p50/p95 search latency
    at 1/4/8 concurrent clients (one Postgres connection per client, closed-loop).
    The default DSN is a DEDICATED database (``raku_bench``) created on demand from the
    maintenance DB; the shared test DBs (raku_parity / raku_tier_b_gate / raku_demo) are refused.

    python3 scripts/bench/run_bench.py --mode local --n-docs 3000 --out /tmp/bench3000.json

``--mode stg`` (runbook in docs/product/scale-bench.md — COSTS REAL MONEY):
    HTTP against a deployed answer-service (OpenAI embeddings + Bedrock) via the in-VPC pattern
    (ops RunTask / port-forward), targeting a DEDICATED ``bench`` tenant + collection so the demo
    tenant is never polluted. Ingesting thousands of documents calls the paid embedding API per
    chunk — the mode therefore refuses to run without ``--yes-costs-money``.

    ANSWER_SERVICE_URL=http://<internal-alb> RAKU_INTERNAL_AUTH_SECRET=... \
        python3 scripts/bench/run_bench.py --mode stg --n-docs 3000 --yes-costs-money

Deterministic corpus: scripts/bench/generate_corpus.py (same --seed => same corpus/queries).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import subprocess
import sys
import threading
import urllib.request
from urllib.parse import quote as urlquote
from concurrent.futures import ThreadPoolExecutor
from math import log2
from pathlib import Path
from time import perf_counter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))  # generate_corpus
sys.path.insert(0, str(ROOT))  # workers.* (root package, same setup as apps/answer-service)
sys.path.insert(0, str(ROOT / "src"))  # raku_rag

import generate_corpus  # noqa: E402

DEFAULT_DSN = "postgresql://raku:raku@127.0.0.1:5432/raku_bench"  # pragma: allowlist secret -- local dev DB credential
# Databases this benchmark must NEVER write to: Tier-B tests TRUNCATE raku_parity /
# raku_tier_b_gate, and raku_demo serves the sales demo KB.
FORBIDDEN_DBNAMES = {"raku_parity", "raku_tier_b_gate", "raku_demo"}

BENCH_TENANT = "bench"
BENCH_COLLECTION = "bench"
BENCH_USER = "bench-user"


# --------------------------------------------------------------------------- rank metrics


def rank_metrics(gold: set[str], ranked_docs: list[str]) -> dict[str, float]:
    """recall@5 / recall@10 / MRR@10 / nDCG@10 at DOCUMENT level (binary relevance)."""
    if not gold:
        return {}
    top5 = set(ranked_docs[:5])
    top10 = set(ranked_docs[:10])
    recall5 = len(gold & top5) / len(gold)
    recall10 = len(gold & top10) / len(gold)
    mrr = 0.0
    for i, doc_id in enumerate(ranked_docs[:10], start=1):
        if doc_id in gold:
            mrr = 1.0 / i
            break
    dcg = sum(
        1.0 / log2(i + 1) for i, doc_id in enumerate(ranked_docs[:10], start=1) if doc_id in gold
    )
    idcg = sum(1.0 / log2(i + 1) for i in range(1, min(len(gold), 10) + 1))
    ndcg = dcg / idcg if idcg else 0.0
    return {"recall@5": recall5, "recall@10": recall10, "mrr@10": mrr, "ndcg@10": ndcg}


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct / 100.0 * (len(ordered) - 1))))
    return ordered[int(idx)]


def aggregate_quality(query_results: list[dict], queries: list[dict]) -> dict:
    by_id = {q["query_id"]: q for q in queries}
    slices: dict[str, list[dict]] = {}
    unanswerable_top1: list[float] = []
    answerable_top1: list[float] = []
    for res in query_results:
        q = by_id[res["query_id"]]
        gold = set(q["gold_document_ids"])
        if not q["answerable"]:
            unanswerable_top1.append(res["top1_score"])
            continue
        answerable_top1.append(res["top1_score"])
        metrics = rank_metrics(gold, res["ranked_docs"])
        slices.setdefault(q["category"], []).append(metrics)
        slices.setdefault("_overall", []).append(metrics)

    def _mean(items: list[dict], key: str) -> float:
        return round(sum(m[key] for m in items) / len(items), 4) if items else 0.0

    out: dict = {"slices": {}}
    for name, items in sorted(slices.items()):
        out["slices"][name.lstrip("_")] = {
            "n": len(items),
            "recall@5": _mean(items, "recall@5"),
            "recall@10": _mean(items, "recall@10"),
            "mrr@10": _mean(items, "mrr@10"),
            "ndcg@10": _mean(items, "ndcg@10"),
        }
    out["unanswerable"] = {
        "n": len(unanswerable_top1),
        "mean_top1_score": (
            round(statistics.fmean(unanswerable_top1), 4) if unanswerable_top1 else 0.0
        ),
        "max_top1_score": round(max(unanswerable_top1), 4) if unanswerable_top1 else 0.0,
    }
    out["answerable_mean_top1_score"] = (
        round(statistics.fmean(answerable_top1), 4) if answerable_top1 else 0.0
    )
    return out


# --------------------------------------------------------------------------- local backend


def _conninfo(dsn: str) -> dict:
    from psycopg import conninfo

    return conninfo.conninfo_to_dict(dsn)


def ensure_bench_database(dsn: str) -> None:
    """Create the dedicated bench DB if absent (via the maintenance DB) and apply migrations."""
    import psycopg

    info = _conninfo(dsn)
    dbname = str(info.get("dbname") or "")
    if dbname in FORBIDDEN_DBNAMES:
        raise SystemExit(
            f"refusing to benchmark against shared DB {dbname!r} "
            f"(tests TRUNCATE it / demo serves from it) — use a dedicated DB, e.g. raku_bench"
        )
    try:
        psycopg.connect(dsn, connect_timeout=5).close()
    except psycopg.OperationalError:
        created = False
        for maintenance in ("postgres", "raku", "template1"):
            maint_info = {**info, "dbname": maintenance}
            try:
                with psycopg.connect(**maint_info, autocommit=True) as conn:
                    conn.execute(f'CREATE DATABASE "{dbname}"')
                created = True
                print(f"[bench] created database {dbname} (via {maintenance})")
                break
            except psycopg.OperationalError:
                continue
        if not created:
            raise SystemExit(f"could not create database {dbname!r}: no maintenance DB reachable")
    env = {**os.environ, "POSTGRES_URL": dsn}
    print(f"[bench] applying migrations to {dbname} (scripts/pg-migrate.sh up)")
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "pg-migrate.sh"), "up"],
        check=True,
        env=env,
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
    )


def _chunking_metadata(doc: dict) -> dict:
    meta = {
        "document_title": doc["title"],
        "document_kind": doc["document_kind"],
        "approval_status": doc["approval_status"],
        "effective_date": doc["effective_date"],
    }
    for key in ("equipment_id", "alarm_code", "part_no"):
        if doc.get(key):
            meta[key] = doc[key]
    return meta


def _bench_synonym_lexicon_entries() -> dict[str, list[str]]:
    """The tenant lexicon a real customer would configure for this corpus's vocabulary.

    Key = canonical document surface form, values = the query-side synonyms (exactly the
    ``SYMPTOM_SYNONYMS`` pairs the synonym eval slice substitutes). Wave 1c expands these for the
    lexical retrieval leg (``retrieval.synonyms`` namespace); seeding them is part of the measured
    condition — pass ``--no-synonyms`` to measure the pre-1c behavior.
    """
    return {
        doc_form: [query_form] for doc_form, query_form in generate_corpus.SYMPTOM_SYNONYMS.items()
    }


def local_seed_synonyms(system) -> None:
    """Idempotent upsert of the bench tenant's retrieval.synonyms lexicon (Wave 1c)."""
    from raku_rag.persistence.lexicon import PostgresLexiconRepository
    from raku_rag.services.lexicon import LexiconService

    lexicon = LexiconService(PostgresLexiconRepository(system._conn))
    for key, values in _bench_synonym_lexicon_entries().items():
        lexicon.update(BENCH_TENANT, "retrieval.synonyms", key, values, actor_id=BENCH_USER)


def local_ingest(dsn: str, settings, documents: list[dict]) -> dict:
    from raku_rag.domain.models import ScopeType, SubjectType
    from raku_rag.production import ProductionSystem

    system = ProductionSystem(dsn, settings=settings, reset=True)
    try:
        system.grant(
            BENCH_TENANT,
            ScopeType.COLLECTION,
            BENCH_COLLECTION,
            SubjectType.USER,
            BENCH_USER,
        )
        chunk_count = 0
        failed: list[str] = []
        started = perf_counter()
        for i, doc in enumerate(documents, start=1):
            job = system.ingest_text(
                tenant_id=BENCH_TENANT,
                collection_id=BENCH_COLLECTION,
                document_id=doc["document_id"],
                text=doc["content"],
                source_id=doc["document_kind"],
                chunking_metadata=_chunking_metadata(doc),
            )
            if job.status != "succeeded":
                failed.append(f"{doc['document_id']}: {job.failure_reason}")
            chunk_count += job.chunk_count
            if i % 500 == 0:
                elapsed = perf_counter() - started
                print(f"[bench] ingested {i}/{len(documents)} docs ({i / elapsed:.1f} docs/s)")
        elapsed = perf_counter() - started
        if failed:
            raise SystemExit(f"{len(failed)} ingest failures, first: {failed[0]}")
        return {
            "docs": len(documents),
            "chunks": chunk_count,
            "seconds": round(elapsed, 2),
            "docs_per_sec": round(len(documents) / elapsed, 2),
            "chunks_per_sec": round(chunk_count / elapsed, 2),
        }
    finally:
        system.close()


def local_search_fns(dsn: str, settings, concurrency: int, *, synonyms: bool = True):
    """One ProductionSystem (own Postgres connection) per concurrent client."""
    from raku_rag.domain.models import IdentityClaims
    from raku_rag.production import ProductionSystem

    principal = IdentityClaims(tenant_id=BENCH_TENANT, user_id=BENCH_USER)
    systems = [ProductionSystem(dsn, settings=settings) for _ in range(concurrency)]
    if synonyms:
        # Wave 1c measured condition: tenant lexicon rows exist (idempotent, works with
        # --skip-ingest) and each client's retrieval reads them — same post-construction
        # attachment the deployed answer-service uses (apps/answer-service/server.py).
        from raku_rag.persistence.lexicon import PostgresLexiconRepository
        from raku_rag.services.lexicon import LexiconService

        local_seed_synonyms(systems[0])
        for system in systems:
            system.retrieval._lexicon = LexiconService(PostgresLexiconRepository(system._conn))

    def make(system):
        def search(question: str) -> tuple[list[str], float]:
            scored = system.search(principal, question, BENCH_COLLECTION)
            ranked = list(dict.fromkeys(s.chunk.document_id for s in scored))
            top1 = float(scored[0].retrieval_score) if scored else 0.0
            return ranked, top1

        return search

    def close() -> None:
        for system in systems:
            system.close()

    return [make(s) for s in systems], close


# --------------------------------------------------------------------------- stg backend


class StgClient:
    """HTTP client for the deployed answer-service /internal surface (in-VPC access required)."""

    def __init__(self) -> None:
        self.base = os.environ.get("ANSWER_SERVICE_URL", "").rstrip("/")
        if not self.base:
            raise SystemExit("--mode stg requires ANSWER_SERVICE_URL (internal ALB / forwarded)")
        self.internal_auth = os.environ.get("RAKU_INTERNAL_AUTH_SECRET", "")

    def _request(self, method: str, path: str, body: dict) -> dict:
        headers = {"content-type": "application/json"}
        if self.internal_auth:
            headers["X-Internal-Auth"] = self.internal_auth
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.load(res)

    def _identity(self) -> dict:
        return {
            "tenant_id": BENCH_TENANT,
            "user_id": BENCH_USER,
            "groups": [],
            "roles": ["tenant_admin"],
        }

    def grant_acl(self) -> None:
        headers = {
            "content-type": "application/json",
            "x-raku-tenant-id": BENCH_TENANT,
            "x-raku-user-id": BENCH_USER,
            "x-raku-groups": "[]",
            "x-raku-roles": json.dumps(["tenant_admin"]),
        }
        if self.internal_auth:
            headers["X-Internal-Auth"] = self.internal_auth
        body = {
            "grants": [
                {
                    "scope_type": "collection",
                    "scope_id": BENCH_COLLECTION,
                    "subject_type": "user",
                    "subject_id": BENCH_USER,
                }
            ],
            "reason": "scale bench: dedicated bench tenant collection read",
        }
        req = urllib.request.Request(
            self.base + "/internal/admin/acl",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="PUT",
        )
        urllib.request.urlopen(req, timeout=30).read()

    def seed_synonyms(self) -> None:
        """Seed the bench tenant's retrieval.synonyms lexicon via the audited admin API (1c)."""
        headers = {
            "content-type": "application/json",
            "x-raku-tenant-id": BENCH_TENANT,
            "x-raku-user-id": BENCH_USER,
            "x-raku-groups": "[]",
            "x-raku-roles": json.dumps(["tenant_admin"]),
        }
        if self.internal_auth:
            headers["X-Internal-Auth"] = self.internal_auth
        for key, values in _bench_synonym_lexicon_entries().items():
            req = urllib.request.Request(
                self.base + "/internal/admin/lexicon/retrieval.synonyms/" + urlquote(key),
                data=json.dumps({"values": values}).encode("utf-8"),
                headers=headers,
                method="PUT",
            )
            urllib.request.urlopen(req, timeout=30).read()

    def ingest(self, doc: dict) -> tuple[str, int]:
        content_b64 = base64.b64encode(doc["content"].encode("utf-8")).decode("ascii")
        body = {
            **self._identity(),
            "collection_id": BENCH_COLLECTION,
            "source_id": doc["document_kind"],
            "document_id": doc["document_id"],
            "document_ref": f"data:text/plain;base64,{content_b64}",
            "content_type": "text/plain",
        }
        res = self._request("POST", "/internal/ingest", body)
        return str(res.get("status", "?")), int(res.get("chunk_count") or 0)

    def search(self, question: str) -> tuple[list[str], float]:
        body = {
            **self._identity(),
            "query": question,
            "collection_id": BENCH_COLLECTION,
            "top_k": 20,
        }
        res = self._request("POST", "/internal/search", body)
        results = res.get("results", [])
        ranked = list(dict.fromkeys(str(r.get("document_id", "")) for r in results))
        top1 = float(results[0].get("retrieval_score") or 0.0) if results else 0.0
        return ranked, top1


def stg_ingest(client: StgClient, documents: list[dict]) -> dict:
    client.grant_acl()
    chunk_count = 0
    started = perf_counter()
    for i, doc in enumerate(documents, start=1):
        status, chunks = client.ingest(doc)
        if status not in ("succeeded", "skipped"):
            raise SystemExit(f"stg ingest failed for {doc['document_id']}: {status}")
        chunk_count += chunks
        if i % 200 == 0:
            elapsed = perf_counter() - started
            print(f"[bench] stg ingested {i}/{len(documents)} docs ({i / elapsed:.1f} docs/s)")
    elapsed = perf_counter() - started
    return {
        "docs": len(documents),
        "chunks": chunk_count,
        "seconds": round(elapsed, 2),
        "docs_per_sec": round(len(documents) / elapsed, 2),
        "chunks_per_sec": round(chunk_count / elapsed, 2),
    }


# --------------------------------------------------------------------------- harness


def run_query_load(search_fns, queries: list[dict], concurrency: int) -> tuple[list[dict], dict]:
    """Closed-loop load: ``concurrency`` clients each work a round-robin shard sequentially."""
    shards = [queries[i::concurrency] for i in range(concurrency)]
    results_lock = threading.Lock()
    all_results: list[dict] = []

    def worker(idx: int) -> None:
        search = search_fns[idx]
        local: list[dict] = []
        for q in shards[idx]:
            t0 = perf_counter()
            ranked, top1 = search(q["question"])
            latency_ms = (perf_counter() - t0) * 1000
            local.append(
                {
                    "query_id": q["query_id"],
                    "latency_ms": latency_ms,
                    "ranked_docs": ranked,
                    "top1_score": top1,
                }
            )
        with results_lock:
            all_results.extend(local)

    started = perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(worker, range(concurrency)))
    wall = perf_counter() - started
    latencies = [r["latency_ms"] for r in all_results]
    summary = {
        "concurrency": concurrency,
        "queries": len(all_results),
        "wall_seconds": round(wall, 2),
        "qps": round(len(all_results) / wall, 2) if wall else 0.0,
        "p50_ms": round(percentile(latencies, 50), 1),
        "p95_ms": round(percentile(latencies, 95), 1),
        "mean_ms": round(statistics.fmean(latencies), 1) if latencies else 0.0,
        "max_ms": round(max(latencies), 1) if latencies else 0.0,
    }
    return all_results, summary


def print_report(report: dict) -> None:
    print("\n=== scale bench report ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Wave 1a scale benchmark (see module docstring)")
    parser.add_argument("--mode", choices=("local", "stg"), default="local")
    parser.add_argument("--n-docs", type=int, default=3000)
    parser.add_argument("--n-queries", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260703)
    parser.add_argument("--dsn", default=os.environ.get("BENCH_POSTGRES_URL", DEFAULT_DSN))
    parser.add_argument(
        "--concurrency", default="1,4,8", help="comma-separated client counts (default 1,4,8)"
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="reuse the previously ingested corpus (must match --n-docs/--seed)",
    )
    parser.add_argument("--top-k", type=int, default=20, help="search profile top_k (>=10)")
    parser.add_argument(
        "--no-synonyms",
        action="store_true",
        help="do NOT seed/attach the retrieval.synonyms tenant lexicon (measure pre-1c behavior)",
    )
    parser.add_argument("--out", default="", help="write the JSON report here")
    parser.add_argument(
        "--yes-costs-money",
        action="store_true",
        help="required for --mode stg: paid embedding/LLM calls per document/query",
    )
    args = parser.parse_args()
    concurrency_levels = [int(c) for c in args.concurrency.split(",") if c.strip()]

    corpus = generate_corpus.generate(n_docs=args.n_docs, n_queries=args.n_queries, seed=args.seed)
    documents, queries = corpus["documents"], corpus["queries"]
    report: dict = {
        "mode": args.mode,
        "n_docs": args.n_docs,
        "n_queries": len(queries),
        "seed": args.seed,
        "top_k": args.top_k,
        "synonyms": not args.no_synonyms,
    }

    if args.mode == "stg":
        if not args.yes_costs_money:
            raise SystemExit(
                "--mode stg ingests thousands of documents through PAID embedding APIs and "
                "runs paid queries. Re-run with --yes-costs-money after reading the runbook "
                "in docs/product/scale-bench.md (dedicated 'bench' tenant, in-VPC access)."
            )
        client = StgClient()
        if not args.skip_ingest:
            report["ingest"] = stg_ingest(client, documents)
        if not args.no_synonyms:
            # Server-side expansion: the deployed answer-service reads the tenant_lexicon rows.
            client.seed_synonyms()
        search_fns = [client.search for _ in range(max(concurrency_levels))]

        def close() -> None:
            return None

    else:
        from raku_rag.core.config import Settings

        ensure_bench_database(args.dsn)
        settings = Settings(default_top_k=max(10, args.top_k))
        if not args.skip_ingest:
            report["ingest"] = local_ingest(args.dsn, settings, documents)
        search_fns, close = local_search_fns(
            args.dsn, settings, max(concurrency_levels), synonyms=not args.no_synonyms
        )

    try:
        # Warmup (per-connection plans/caches), excluded from measurements.
        for q in queries[:3]:
            search_fns[0](q["question"])

        report["latency"] = {}
        quality_results: list[dict] | None = None
        for level in concurrency_levels:
            print(f"[bench] query load: {len(queries)} queries at concurrency {level}")
            results, summary = run_query_load(search_fns[:level], queries, level)
            report["latency"][str(level)] = summary
            if quality_results is None:
                quality_results = results
        assert quality_results is not None
        report["quality"] = aggregate_quality(quality_results, queries)
    finally:
        close()

    print_report(report)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[bench] report written to {out_path}")


if __name__ == "__main__":
    main()
