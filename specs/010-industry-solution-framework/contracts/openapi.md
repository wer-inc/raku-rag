# API Contracts: Industry Solution Framework

All endpoints inherit 001 authentication, tenant isolation, ACL pre-filter, audit, cost tracking, redaction, no-train, and provider policy behavior.

## GET /industries

- res 200: `{ industries:[{ industry_id, name, status, version }] }`
- ACL: tenant-scoped list of enabled profiles.
- Audit: `industry_profile_list`.

## GET /industries/{industry_id}/profile

- res 200: `{ industry_id, version, document_types, metadata_schema, workflows, draft_artifact_types, kpis, dashboard_widgets, governance_profile }`
- errors: 404 for unavailable/unauthorized profile.

## POST /industries/{industry_id}/metadata/validate

- req: `{ metadata, schema_version?, document_type? }`
- res 200: `{ valid, errors[], normalized_metadata, indexed_fields }`
- Audit: `industry_metadata_validate`.

## POST /industries/{industry_id}/documents/enrich

- req: `{ document_id, metadata, enrichment_options? }`
- res 200: `{ document_id, metadata_schema_version, enriched_metadata, warnings[] }`
- ACL: caller must have document metadata update permission.
- Audit: `industry_document_enrich`.

## POST /industries/{industry_id}/workflows/{workflow_id}/run

- req: `{ collection_id?, input, retrieval_profile_id?, dry_run? }`
- res 200: `{ workflow_run_id, status, answer?, citations[], risk_decision?, gate_decision?, draft_artifact_id?, kpi_events[], audit_log_ref }`
- errors: `insufficient_evidence`, `risk_gate_blocked`, `unauthorized`, `budget_exceeded`, `temporarily_unavailable`.

## POST /industries/{industry_id}/drafts/{artifact_type}

- req: `{ payload, source_citations[], source_document_ids[], reviewer_id?, reviewer_group?, template_id? }`
- res 201: `{ artifact_id, status:"draft", review_required, audit_log_ref }`
- Rule: AI-created artifacts must start as `draft` and cannot auto-approve.

## GET /industries/{industry_id}/drafts/{artifact_id}

- res 200: `{ artifact_id, industry_id, artifact_type, status, payload, source_citations, review_state, audit_log_ref }`
- ACL: artifact and source citations must be authorized.

## POST /industries/{industry_id}/drafts/{artifact_id}/review

- req: `{ action:"assign|submit|approve|reject|archive", reviewer_id?, reviewer_group?, review_comment?, approval_decision?, required_changes? }`
- res 200: `{ artifact_id, status, reviewed_at?, audit_log_ref }`
- Rule: allowed transitions come from DraftReviewPolicy.

## GET /industries/{industry_id}/dashboard

- req query: `time_range`, `filters`
- res 200: `{ widgets:[{ widget_id, name, kpis, data, warnings[] }] }`
- ACL: no unauthorized document, draft, entity, or KPI leakage.

## GET /industries/{industry_id}/kpi

- req query: `kpi_ids`, `time_range`, `filters`
- res 200: `{ kpis:[{ kpi_id, value, aggregation_window, source, calculated_at }] }`

## GET /industries/{industry_id}/governance/status

- res 200: `{ no_train, audit_coverage, retention, pii_policy, provider_governance, risk_policy, draft_review, regulated_extensions? }`
