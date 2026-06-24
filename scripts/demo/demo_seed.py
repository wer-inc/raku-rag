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
# The answer-service enforces the internal-boundary shared secret when RAKU_INTERNAL_AUTH_SECRET is
# set (demo_up.sh exports it). Seeding posts straight to /internal/ingest, so it must present the same
# header or every ingest 401s with internal_auth_required (silent empty KB). No secret -> dev no-op.
INTERNAL_AUTH = os.environ.get("RAKU_INTERNAL_AUTH_SECRET", "")
TENANT = os.environ.get("DEMO_TENANT", "demo")
COLLECTION = os.environ.get("DEMO_COLLECTION", "manuals")
UPLOAD_DIR = os.environ.get("RAKU_UPLOAD_DIR", "/tmp/raku-demo-seed")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _post(path: str, body: dict) -> tuple[str, object]:
    headers = {"content-type": "application/json"}
    if INTERNAL_AUTH:
        headers["X-Internal-Auth"] = INTERNAL_AUTH
    req = urllib.request.Request(
        AS_URL + path, data=json.dumps(body).encode("utf-8"), headers=headers
    )
    try:
        res = json.load(urllib.request.urlopen(req, timeout=30))
        return res.get("status", "?"), res.get("chunk_count")
    except urllib.error.HTTPError as exc:
        return "ERROR", exc.read().decode("utf-8", "replace")[:160]
    except Exception as exc:  # noqa: BLE001
        return "ERROR", str(exc)[:160]


def _mfg_block(doc: dict) -> dict:
    return {
        "approval_status": doc["approval_status"],
        "effective_date": doc.get("effective_date") or None,
        "approval_source": "workflow",
        "document_kind": doc.get("document_kind"),
        **(
            {"safety_category": doc["safety_category"]}
            if doc.get("safety_category") and doc["safety_category"] != "none"
            else {}
        ),
    }


def register_trouble_case(doc: dict) -> tuple[str, object]:
    """Trouble reports are registered as a TroubleCase graph (symptom -> cause -> split
    provisional/permanent countermeasures) so trouble-cases/search resolves structured countermeasures,
    not just text. The register route ingests the body too, so do NOT also call /internal/ingest."""
    tc = doc["trouble_case"]
    body = {
        "tenant_id": TENANT,
        "user_id": "alice",
        "groups": [],
        "roles": ["tenant_admin"],
        "collection_id": COLLECTION,
        "source_id": "case",
        "source_document_id": doc["document_id"],
        "document_id": doc["document_id"],
        "text": doc["content"],
        "manufacturing": _mfg_block(doc),
        "symptom": tc.get("symptom") or "",
        "equipment_id": tc.get("equipment_id"),
        "failure_mode": tc.get("failure_mode") or {},
        "provisional": tc.get("provisional") or [],
        "permanent": tc.get("permanent") or [],
        "recurrence": tc.get("recurrence"),
    }
    status, _ = _post("/internal/manufacturing/trouble-cases/register", body)
    # The register route returns {"status": "registered"}; report it as a success for the seed summary.
    return ("succeeded" if status in ("registered", "?") else status), "graph"


def ingest(doc: dict) -> tuple[str, object]:
    if doc.get("trouble_case"):
        return register_trouble_case(doc)
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
    headers = {"content-type": "application/json"}
    if INTERNAL_AUTH:
        headers["X-Internal-Auth"] = INTERNAL_AUTH
    req = urllib.request.Request(
        AS_URL + "/internal/ingest",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
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
