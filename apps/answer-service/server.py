"""Python answer-service — the internal HTTP boundary over the Postgres-backed ProductionSystem.

This is the one place that exposes the proven RAG core (001 Step 2/3: Postgres + pgvector + RLS, with the
security + ranking parity gates green) over HTTP. The NestJS API is a THIN product facade that forwards
authenticated requests here; the RAG truth (retrieval / ACL / ranking) lives ONLY in ProductionSystem and
is never reimplemented in TypeScript.

    POST /internal/answer  {tenant_id,user_id,groups,roles,query,collection_id?} -> AnswerResponse JSON
    POST /internal/search  {...}                                                 -> {results,correlation_id}
    GET  /healthz                                                                -> {status:"ok"}

Run:  POSTGRES_URL=postgresql://raku:raku@127.0.0.1:5432/raku_parity \
      PYTHONPATH=src python3 apps/answer-service/server.py --seed --port 8088
stdlib only (http.server) + the project's psycopg-backed ProductionSystem.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Run as a script: put the project's src/ on sys.path so `raku_rag` imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from raku_rag.domain.models import IdentityClaims, ScopeType, SubjectType  # noqa: E402
from raku_rag.production import DEFAULT_DSN, ProductionSystem  # noqa: E402


def seed(system: ProductionSystem) -> None:
    """Seed a small demo tenant so the vertical slice is touchable end-to-end."""
    docs = {
        "m1": "The maintenance interval for pump P-12 is ninety days per the equipment manual.",
        "m2": "Alarm E-152 on the press indicates a hydraulic pressure fault: stop the line and "
        "check the accumulator before restarting.",
        "m3": "The torque specification for the M8 cover bolt on the conveyor is twelve newton metres.",
    }
    for doc_id, text in docs.items():
        system.ingest_text(tenant_id="demo", collection_id="manuals", document_id=doc_id, text=text)
    system.grant("demo", ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")


def _claims(body: dict) -> IdentityClaims:
    return IdentityClaims(
        tenant_id=str(body["tenant_id"]),
        user_id=str(body["user_id"]),
        groups=tuple(body.get("groups") or ()),
        roles=tuple(body.get("roles") or ()),
    )


def _answer_json(ans) -> dict:
    return {
        "status": ans.status,
        "text": ans.text,
        "citations": [
            {
                "kind": c.kind,
                "document_id": c.document_id,
                "chunk_id": c.chunk_id,
                "source_id": c.source_id,
                "version": c.version,
                "text_range": list(c.text_range) if c.text_range else None,
                "retrieval_score": c.retrieval_score,
            }
            for c in ans.citations
        ],
        "used_chunks": [
            {"chunk_id": cid, "document_id": cid.split(":")[0], "retrieval_score": 0.0}
            for cid in ans.used_chunks
        ],
        "confidence": ans.confidence,
        "freshness": (
            {
                "indexed_at": ans.freshness[0].indexed_at,
                "document_version": ans.freshness[0].document_version,
                "source_freshness": ans.freshness[0].source_freshness,
            }
            if ans.freshness
            else None
        ),
        "correlation_id": ans.correlation_id,
    }


def make_handler(system: ProductionSystem):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("content-length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                self._send(200, {"status": "ok", "backend": "production-system"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                body = self._body()
                principal = _claims(body)
                query = str(body.get("query") or "")
                collection_id = body.get("collection_id")
                if self.path == "/internal/answer":
                    self._send(200, _answer_json(system.answer(principal, query, collection_id)))
                elif self.path == "/internal/search":
                    results = system.search(principal, query, collection_id)
                    self._send(
                        200,
                        {
                            "results": [
                                {
                                    "document_id": r.chunk.document_id,
                                    "chunk_id": r.chunk.chunk_id,
                                    "text": r.chunk.text,
                                    "retrieval_score": r.retrieval_score,
                                }
                                for r in results
                            ]
                        },
                    )
                else:
                    self._send(404, {"error": "not found"})
            except KeyError as exc:
                self._send(400, {"error": f"missing field: {exc}"})
            except Exception as exc:  # pragma: no cover - surface as 500 to the facade
                self._send(500, {"error": str(exc)})

        def log_message(self, *_args) -> None:  # quiet
            return

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description="raku-rag answer-service (ProductionSystem over HTTP)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("ANSWER_SERVICE_PORT", "8088")))
    ap.add_argument("--seed", action="store_true", help="reset + seed a demo tenant on startup")
    args = ap.parse_args()

    dsn = os.environ.get("POSTGRES_URL", DEFAULT_DSN)
    system = ProductionSystem(dsn, reset=args.seed)
    if args.seed:
        seed(system)
        print(f"seeded demo tenant; ProductionSystem on {dsn}", flush=True)

    httpd = HTTPServer(("127.0.0.1", args.port), make_handler(system))
    print(f"answer-service listening on http://127.0.0.1:{args.port} (/internal/answer)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()


if __name__ == "__main__":
    main()
