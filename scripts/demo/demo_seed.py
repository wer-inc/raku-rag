#!/usr/bin/env python3
"""Seed the PoC demo tenant with a realistic 東洋精機 manufacturing knowledge base.

Ingests scripts/demo/demo_docs.json into the running answer-service via
POST /internal/ingest (identity in body), with manufacturing approval metadata so
the safety overlay (approved / draft / obsolete / pending_review) drives the demo.
Idempotent: re-ingesting the same document_id overwrites.
"""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "demo_docs.json"), encoding="utf-8") as _docs_file:
    DOCS = json.load(_docs_file)
AS_URL = os.environ.get("ANSWER_SERVICE_URL", "http://127.0.0.1:8088")
# The answer-service enforces the internal-boundary shared secret when RAKU_INTERNAL_AUTH_SECRET is
# set (demo_up.sh exports it). Seeding posts straight to /internal/ingest, so it must present the same
# header or every ingest 401s with internal_auth_required (silent empty KB). No secret -> dev no-op.
INTERNAL_AUTH = os.environ.get("RAKU_INTERNAL_AUTH_SECRET", "")
TENANT = os.environ.get("DEMO_TENANT", "demo")
COLLECTION = os.environ.get("DEMO_COLLECTION", "manuals")

# The demo identities the dev-token issuer (apps/web/app/api/dev-token/route.ts) recognizes. ACL is
# deny-by-default, so WITHOUT a grant every ingested doc is invisible and search/answer return empty.
# Grant each demo user READ on the demo collection so any demo login can retrieve. Cognito sales users
# authenticate as real email users with the ``sales_demo`` group/role, not as one of the local dev-token
# users below. Granting the role keeps ACL deny-by-default intact while letting sales-demo accounts
# retrieve the prepared corpus.
# "phone-gateway" is the 024 telephony-channel SERVICE identity (Connect adapter Lambda): what the
# phone AI can answer = what this user is granted, keeping ACL deny-by-default for the phone path.
DEMO_USERS = ["alice", "misaki", "bob", "carol", "dave", "phone-gateway"]
DEMO_ROLES = ["sales_demo"]


def _internal_headers(*, content_type: bool = False, principal: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if content_type:
        headers["content-type"] = "application/json"
    if principal:
        headers["x-raku-tenant-id"] = TENANT
        headers["x-raku-user-id"] = "alice"
        headers["x-raku-groups"] = json.dumps([])
        headers["x-raku-roles"] = json.dumps(DEMO_ROLES)
    if INTERNAL_AUTH:
        headers["X-Internal-Auth"] = INTERNAL_AUTH
    return headers


def _post(path: str, body: dict) -> tuple[str, object]:
    headers = _internal_headers(content_type=True)
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


def delete_existing_doc(document_id: str) -> tuple[str, object]:
    """Tombstone/purge the existing demo doc through the service before re-ingest.

    This keeps the registry, chunks, cache, and ingestion idempotency state aligned. Raw SQL deletes can
    leave a live registry row with stale embedding metadata, causing a same-checksum re-seed to skip the
    re-embedding that demo deployments rely on.
    """
    headers = _internal_headers(content_type=True, principal=True)
    req = urllib.request.Request(
        AS_URL + f"/internal/documents/{document_id}",
        data=None,
        headers=headers,
        method="DELETE",
    )
    try:
        res = json.load(urllib.request.urlopen(req, timeout=30))
        return str(res.get("status") or "?"), res.get("purged_chunks")
    except urllib.error.HTTPError as exc:
        return "ERROR", exc.read().decode("utf-8", "replace")[:160]
    except Exception as exc:  # noqa: BLE001
        return "ERROR", str(exc)[:160]


def list_existing_collection_docs() -> tuple[str, object]:
    """List every live document currently visible in the demo collection.

    The seed first grants collection READ to the demo role, so this ACL-filtered inventory becomes a
    tenant/collection-scoped cleanup list without adding a raw database delete path.
    """
    query = urllib.parse.urlencode({"collection_id": COLLECTION})
    req = urllib.request.Request(
        AS_URL + f"/internal/manufacturing/documents?{query}",
        headers=_internal_headers(principal=True),
    )
    try:
        res = json.load(urllib.request.urlopen(req, timeout=30))
        docs = res.get("documents") or []
        document_ids = sorted(
            {
                str(doc.get("document_id") or "")
                for doc in docs
                if isinstance(doc, dict) and str(doc.get("document_id") or "")
            }
        )
        return "listed", document_ids
    except urllib.error.HTTPError as exc:
        return "ERROR", exc.read().decode("utf-8", "replace")[:160]
    except Exception as exc:  # noqa: BLE001
        return "ERROR", str(exc)[:160]


def _context_extra(doc: dict) -> dict:
    text = f"{doc.get('title') or ''}\n{doc.get('content') or ''}"
    extra = {
        "document_title": doc.get("title") or doc["document_id"],
        "source_system": "demo_seed",
        "source_sync_freshness": "curated_demo_seed",
        "factory_id": doc.get("factory_id") or "toyoseiki-factory-1",
    }
    for key in ("line_id", "process_id", "equipment_id"):
        if doc.get(key):
            extra[key] = doc[key]
    if "equipment_id" not in extra:
        equipment_id = _infer_equipment_id(text)
        if equipment_id:
            extra["equipment_id"] = equipment_id
    if "line_id" not in extra:
        line_id = _infer_line_id(text)
        if line_id:
            extra["line_id"] = line_id
    return {key: value for key, value in extra.items() if value}


def _infer_equipment_id(text: str) -> str:
    for pattern in (
        r"\b(?:MCC|CV|PR|ESD)-[A-Za-z0-9-]+\b",
        r"\b(?:E|P|V|T)-\d+[A-Za-z]?\b",
        r"\bM\d+\b",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def _infer_line_id(text: str) -> str:
    match = re.search(r"\b[A-Z]-Line\b", text, re.IGNORECASE)
    return match.group(0) if match else ""


def _mfg_block(doc: dict) -> dict:
    return {
        "approval_status": doc["approval_status"],
        "effective_date": doc.get("effective_date") or None,
        "approval_source": "workflow",
        "document_kind": doc.get("document_kind"),
        "extra": _context_extra(doc),
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
    # Inline the content as a base64 data: ref. The seed runs in the migrate-seed container, a
    # SEPARATE container from the answer-service, so a file:// ref written to local /tmp here is
    # unreadable there (silent empty KB). data: refs carry the bytes in-request — no shared FS needed.
    content_b64 = base64.b64encode(doc["content"].encode("utf-8")).decode("ascii")
    body = {
        "tenant_id": TENANT,
        "user_id": "alice",
        "groups": [],
        "roles": ["tenant_admin"],
        "collection_id": COLLECTION,
        "source_id": doc.get("document_kind", "demo"),
        "document_id": doc["document_id"],
        "document_ref": f"data:text/plain;base64,{content_b64}",
        "content_type": "text/plain",
        # Only set safety_category for genuinely high-risk docs. The classifier's METADATA stage
        # treats ANY non-empty safety_category as high-risk, so a literal "none" string would make
        # every benign maintenance/quality doc flag high-risk — destroying the safety distinction.
        "manufacturing": _mfg_block(doc),
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


def grant_demo_acl() -> tuple[str, object]:
    """PUT /internal/admin/acl — collection-scoped READ grant for demo users/roles.

    The grant is persisted in acl_grants and is idempotent. The seed applies it before cleanup so the
    ACL-filtered document inventory can see and purge stale same-collection demo documents.
    """
    grants = [
        {
            "scope_type": "collection",
            "scope_id": COLLECTION,
            "subject_type": "user",
            "subject_id": user,
        }
        for user in DEMO_USERS
    ]
    grants.extend(
        {
            "scope_type": "collection",
            "scope_id": COLLECTION,
            "subject_type": "role",
            "subject_id": role,
        }
        for role in DEMO_ROLES
    )
    headers = _internal_headers(content_type=True, principal=True)
    req = urllib.request.Request(
        AS_URL + "/internal/admin/acl",
        data=json.dumps({"grants": grants, "reason": "demo seed: collection read for demo users"}).encode(
            "utf-8"
        ),
        headers=headers,
        method="PUT",
    )
    try:
        res = json.load(urllib.request.urlopen(req, timeout=30))
        return "granted", len(res.get("grants", []))
    except urllib.error.HTTPError as exc:
        return "ERROR", exc.read().decode("utf-8", "replace")[:160]
    except Exception as exc:  # noqa: BLE001
        return "ERROR", str(exc)[:160]


def main() -> None:
    ok = 0
    principals = ", ".join(DEMO_USERS + [f"role:{role}" for role in DEMO_ROLES])
    acl_status, acl_info = grant_demo_acl()
    print(f"[demo-seed] acl grant ({principals} -> read {COLLECTION}): {acl_status} {acl_info}")

    curated_ids = {str(doc["document_id"]) for doc in DOCS}
    list_status, existing = list_existing_collection_docs()
    if list_status == "listed":
        existing_ids = set(existing if isinstance(existing, list) else [])
        purge_ids = sorted(existing_ids | curated_ids)
        print(
            f"[demo-seed] tombstoning {len(purge_ids)} live/curated documents "
            f"in {TENANT}/{COLLECTION}"
        )
    else:
        purge_ids = sorted(curated_ids)
        print(
            f"[demo-seed] collection inventory failed ({existing}); "
            f"falling back to {len(purge_ids)} curated documents"
        )
    for document_id in purge_ids:
        status, purged = delete_existing_doc(document_id)
        print(f"  {status:10} {document_id:22} purged_chunks={purged}")
    print(f"[demo-seed] ingesting {len(DOCS)} documents into {TENANT}/{COLLECTION} via {AS_URL}")
    for doc in DOCS:
        status, chunks = ingest(doc)
        if status == "succeeded":
            ok += 1
        print(f"  {status:10} {doc['document_id']:22} {doc['approval_status']:14} chunks={chunks}")
    print(f"[demo-seed] done: {ok}/{len(DOCS)} succeeded")


if __name__ == "__main__":
    main()
