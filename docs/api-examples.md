# API Examples

All product APIs are served under `/v1`. Protected routes require:

```http
Authorization: Bearer local-dev-key
X-User-Token: <signed user token>
```

The signed token supplies `tenant_id`, `user_id`, `groups`, and `roles`.

## Search

```bash
curl -sS http://127.0.0.1:3000/v1/search \
  -H "authorization: Bearer local-dev-key" \
  -H "x-user-token: $USER_TOKEN" \
  -H "content-type: application/json" \
  -d '{"query":"when do backups run?","collection_id":"manuals","top_k":5}'
```

## Answer

```bash
curl -sS http://127.0.0.1:3000/v1/answer \
  -H "authorization: Bearer local-dev-key" \
  -H "x-user-token: $USER_TOKEN" \
  -H "content-type: application/json" \
  -d '{"query":"what alarm does the pump panel show?","collection_id":"manuals"}'
```

Successful visual answers include visual citations with `asset_id`, `page_number`, `region_id`, `bbox`, and `crop_uri`.

## Ingest

```bash
curl -sS http://127.0.0.1:3000/v1/ingest \
  -H "authorization: Bearer local-dev-key" \
  -H "x-user-token: $USER_TOKEN" \
  -H "content-type: application/json" \
  -d '{"collection_id":"manuals","source_id":"upload","document_id":"doc1","ref":"file:///tmp/doc.txt","content_type":"text/plain"}'
```

## Asset View

```bash
curl -sS http://127.0.0.1:3000/v1/assets/asset_abc123 \
  -H "authorization: Bearer local-dev-key" \
  -H "x-user-token: $USER_TOKEN"
```

Unauthorized, missing, or deleted assets return 404-equivalent responses.

## Evaluation

```bash
curl -sS http://127.0.0.1:3000/v1/evaluations/sets \
  -H "authorization: Bearer local-dev-key" \
  -H "x-user-token: $USER_TOKEN" \
  -H "content-type: application/json" \
  -d '{"items":[{"question":"when do backups run?","expected_evidence":[{"document_id":"backup_manual"}]}]}'
```

Then create a run:

```bash
curl -sS http://127.0.0.1:3000/v1/evaluations/runs \
  -H "authorization: Bearer local-dev-key" \
  -H "x-user-token: $USER_TOKEN" \
  -H "content-type: application/json" \
  -d '{"eval_set_id":"eval_set_123","collection_id":"manuals"}'
```
