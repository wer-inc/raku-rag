#!/usr/bin/env python3
"""Seed the PoC demo tenant with a realistic 東洋精機 manufacturing knowledge base.

Ingests scripts/demo/demo_docs.json into the running answer-service via
POST /internal/ingest (identity in body), with manufacturing approval metadata so
the safety overlay (approved / draft / obsolete / pending_review) drives the demo.
Idempotent: re-ingesting the same document_id overwrites.
"""
import json
import os
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = json.load(open(os.path.join(HERE, "demo_docs.json"), encoding="utf-8"))
AS_URL = os.environ.get("ANSWER_SERVICE_URL", "http://127.0.0.1:8088")
TENANT = os.environ.get("DEMO_TENANT", "demo")
COLLECTION = os.environ.get("DEMO_COLLECTION", "manuals")
UPLOAD_DIR = os.environ.get("RAKU_UPLOAD_DIR", "/tmp/raku-demo-seed")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def ingest(doc: dict) -> tuple[str, object]:
    path = os.path.join(UPLOAD_DIR, doc["document_id"] + ".txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc["content"])
    body = {
        "tenant_id": TENANT,
        "user_id": "alice",
        "groups": [],
        "roles": ["tenant_admin"],
        "collection_id": COLLECTION,
        "source_id": doc.get("document_kind", "demo"),
        "document_id": doc["document_id"],
        "document_ref": "file://" + path,
        "content_type": "text/plain",
        "manufacturing": {
            "approval_status": doc["approval_status"],
            "effective_date": doc.get("effective_date") or None,
            "approval_source": "workflow",
            "document_kind": doc.get("document_kind"),
            # Only set safety_category for genuinely high-risk docs. The classifier's METADATA stage
            # treats ANY non-empty safety_category as high-risk, so a literal "none" string would make
            # every benign maintenance/quality doc flag high-risk — destroying the safety distinction.
            **(
                {"safety_category": doc["safety_category"]}
                if doc.get("safety_category") and doc["safety_category"] != "none"
                else {}
            ),
        },
    }
    req = urllib.request.Request(
        AS_URL + "/internal/ingest",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    try:
        res = json.load(urllib.request.urlopen(req, timeout=30))
        return res.get("status", "?"), res.get("chunk_count")
    except urllib.error.HTTPError as exc:
        return "ERROR", exc.read().decode("utf-8", "replace")[:160]
    except Exception as exc:  # noqa: BLE001
        return "ERROR", str(exc)[:160]


def main() -> None:
    ok = 0
    print(f"[demo-seed] ingesting {len(DOCS)} documents into {TENANT}/{COLLECTION} via {AS_URL}")
    for doc in DOCS:
        status, chunks = ingest(doc)
        if status == "succeeded":
            ok += 1
        print(f"  {status:10} {doc['document_id']:22} {doc['approval_status']:14} chunks={chunks}")
    print(f"[demo-seed] done: {ok}/{len(DOCS)} succeeded")


if __name__ == "__main__":
    main()
