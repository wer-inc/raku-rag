---
name: add-datasource-connector
description: >-
  Add a new datasource connector (the 8th, 9th, …) by matching raku-rag's
  existing connector pattern exactly — not by inventing a second architecture.
  TRIGGER when adding/onboarding a new external source (e.g. "add a Jira
  connector", "support SharePoint as a datasource", "wire up <vendor> sync").
  DO NOT TRIGGER for editing an existing connector's behaviour, for generic
  HTTP-client code, or for non-datasource integrations.
metadata:
  origin: adapted from ECC api-connector-builder; tailored to raku-rag's datasource layer
  version: "1.0.0"
---

# Add a datasource connector (raku-rag house style)

The job is to add a **repo-native** sync surface, not a generic HTTP client.
raku-rag already ships 8 connectors (S3 / URL / DB(mysql,postgres) / kintone /
Confluence / Notion / Box / Google Drive). A new one must look obvious next to
them. See the auto-memory `datasource-connectors-e2e` and `datasource-trust-policy-review`.

## Guardrails (do not violate)

- Do **not** invent a new integration architecture — the registry + builder
  convention below already exists; extend it.
- Start from **two existing in-repo connectors**, not vendor docs. Read the
  closest analog (polling-API → copy Confluence/Notion; object-store → copy S3;
  single-record → copy kintone) before writing anything.
- Any outbound HTTP **must** go through the injected `fetch_url` (the
  SSRF-hardened fetcher: IP-pinning, allowlists, auth-strip). Never call
  `urllib`/`requests` directly. See memory `ssrf-connector-preship-gate`.
- A connector **cannot self-grant approval**. Approval comes from the
  server-side `approval_policy` (trusted → approved+imported / default
  review_required → pending_review). Do not add an `approved=true` shortcut in
  the sync body. See memory `datasource-trust-policy-review`.
- Don't stop at fetch code: the registry dispatch, the cross-stack wiring, and
  tests are all part of "done".

## The pattern to match

### Layer 0 — registry dispatch (SSOT)

`src/raku_rag/services/datasource_sync.py` → `build_sync_documents()`
(~line 209) switches on `source_type` and delegates to a per-source builder:

```python
if source_type == "confluence":
    return _confluence_documents(source_id, config, body, effective_limit, fetch_url or _fetch_url)
# ... add your new branch here, before the final `raise ValueError(...)`
```

Add one branch + one `_<source>_documents(...)` builder. Match the existing
builder signature exactly (`source_id, config, body, limit[, fetch_url]`) and
return `list[SyncDocument]`.

### The 4 cross-stack layers (a connector is end-to-end, not just the builder)

1. **answer-service / Python** — the `_<source>_documents()` builder above +
   its dispatch branch in `datasource_sync.py`. Onboarding/validation lives in
   `datasource_onboarding.py`.
2. **API / NestJS** — `apps/api/src/admin/settings.controller.ts` &
   `connectors/oauth.controller.ts` (config schema, OAuth if needed). Preserve
   the `X-Internal-Auth` spread when touching forwarded headers (memory
   `internal-auth-gate-half-landed`).
3. **web / Next.js** — the datasource config UI (source-type option + its
   config fields), matching the other connectors' form.
4. **trust/approval policy** — register the source under the config-driven
   `approval_policy`; do not bypass it.

## Workflow

1. **Learn the house style** — read 2 existing builders in `datasource_sync.py`
   (pick the closest model: API-poll vs object-store vs single-record).
2. **Narrow the surface** — auth flow, key entities, list+fetch operations,
   pagination/limit (clamped to ≤100 like `effective_limit`), polling vs webhook.
3. **Build in repo-native layers** — config/schema → builder (via `fetch_url`)
   → mapping to `SyncDocument` → dispatch branch → API/web wiring → policy.
4. **Validate against the source pattern** — diff your builder against the
   analog you copied; it should differ only where the vendor genuinely differs.

## Quality checklist

- [ ] new `source_type` branch added to `build_sync_documents()` before the `raise`
- [ ] `_<source>_documents()` matches existing builder signature & returns `list[SyncDocument]`
- [ ] all outbound HTTP goes through injected `fetch_url` (no direct urllib/requests)
- [ ] limit clamped (`effective_limit`, ≤100); pagination/retry follows repo norms
- [ ] config validation exists (mirror `datasource_onboarding.py`)
- [ ] no self-granted approval; relies on server-side `approval_policy`
- [ ] API + web wiring complete (source-type selectable end-to-end)
- [ ] tests mirror existing connector tests; `scripts/gate.sh a` green
- [ ] auto-memory `datasource-connectors-e2e` updated if the recipe changed

## Related

- memory: `datasource-connectors-e2e`, `datasource-trust-policy-review`, `ssrf-connector-preship-gate`
- code: `src/raku_rag/services/datasource_sync.py`, `datasource_onboarding.py`
