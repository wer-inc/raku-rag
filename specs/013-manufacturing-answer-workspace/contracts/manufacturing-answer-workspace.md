# Contract: Manufacturing Answer Workspace

## Endpoint

`POST /v1/manufacturing/answer`

The Web workspace uses the same auth headers as the generic answer endpoint:

- `Authorization: Bearer local-dev-key` in local/dev mode
- `X-User-Token: <signed principal token>`

Tenant and user identity are derived by the API middleware from the signed token.

## Request

```json
{
  "query": "How do I disassemble the press safely?",
  "collection_id": "manuals",
  "intent_hint": "maintenance",
  "manufacturing_filters": {
    "factory_id": "factory-a"
  }
}
```

For the PoC v0 Web workspace, only `query` and `collection_id` are sent by default.

## Response

```json
{
  "status": "insufficient_evidence",
  "text": null,
  "answer_template_version": "answer-template/v1",
  "display_sections": [],
  "confidence": null,
  "citations": [
    {
      "kind": "text",
      "document_id": "press-manual",
      "chunk_id": "chunk-7",
      "source_id": "manuals",
      "version": 3,
      "retrieval_score": 0.91,
      "approval_status": "approved",
      "effective_date": "2026-01-10",
      "approval_source": "qa-system"
    }
  ],
  "used_chunks": [],
  "correlation_id": "trace_123",
  "manufacturing": {
    "high_risk": true,
    "high_risk_reason_codes": ["disassembly"],
    "safety_block_reason": "approved_citation_missing",
    "obsolete_warning": false,
    "requires_onsite_confirmation": true,
    "notice": "作業実施前に現場責任者または有資格者の確認が必要です。"
  }
}
```

## Compatibility

- `/v1/answer` continues to return `AnswerResponse` without a required `manufacturing` block.
- Manufacturing citation provenance fields are optional on the base `Citation` type because older/generic answer paths may not include them.
