# API Contracts: Investment Management / Mutual Fund Knowledge RAG

All APIs inherit 001 authentication, tenant isolation, ACL pre-filter, citation, groundedness, audit, cost, redaction, no-train, ProviderPolicy, RetrievalProfile, LoggingPolicy, tombstone, and evaluation behavior. 006 APIs map internally to 010 IndustryProfile and financial/regulated extensions.

## POST /investment/metadata/import

- req: `{ collection_id, records:[{ document_id?, source_document_id?, metadata }] }`
- res 202: `{ import_run_id, accepted_count, rejected_count, status_url }`
- Audit: `investment_metadata_import`.

## POST /investment/documents/enrich

- req: `{ document_id, metadata?, enrichment_options? }`
- res 200: `{ document_id, investment_metadata, normalized_aliases, warnings[] }`

## GET /investment/funds/{fund_id}/knowledge

- res 200: `{ fund_id, fund, documents[], prospectus_refs[], reports[], guidelines[], risk_reports[], citations[] }`
- ACL: unauthorized fund data returns 404/empty without existence leakage.

## POST /investment/workflows/fund-question

- req: `{ question, fund_id?, share_class_id?, document_type?, collection_id? }`
- res 200: `{ status, answer?, citations[], risk_decision?, gate_decision?, review_required?, warnings[] }`
- errors: `insufficient_evidence`, `risk_gate_blocked`, `advice_boundary_blocked`, `unauthorized`.

## POST /investment/workflows/rfp-response-draft

- req: `{ rfp_id?, question, fund_id?, distribution_partner_id?, reviewer_id?, reviewer_group? }`
- res 201: `{ artifact_id, artifact_type:"rfp_response", status:"draft", disclosure_evidence_ids[], source_citations[], audit_log_ref }`

## POST /investment/workflows/ddq-response-draft

- req: `{ ddq_id?, question, fund_id?, reviewer_id?, reviewer_group? }`
- res 201: `{ artifact_id, artifact_type:"ddq_response", status:"draft", disclosure_evidence_ids[], source_citations[], audit_log_ref }`

## POST /investment/workflows/inquiry-reply-draft

- req: `{ inquiry_id?, inquiry_text, fund_id?, source_type?, reviewer_id?, reviewer_group? }`
- res 201: `{ artifact_id, artifact_type:"inquiry_reply", status:"draft", disclosure_evidence_ids[], source_citations[], audit_log_ref }`

## POST /investment/workflows/marketing-material-check

- req: `{ document_id? | artifact_id?, statements[]?, fund_id?, strictness? }`
- res 200: `{ check_id, status, contradiction_results[], disclosure_evidence_ids[], review_required, audit_log_ref }`

## POST /investment/workflows/monthly-commentary-draft

- req: `{ fund_id, report_date, performance_period?, source_document_ids[]?, reviewer_id?, reviewer_group? }`
- res 201: `{ artifact_id, artifact_type:"monthly_commentary", status:"draft", disclosure_evidence_ids[], source_citations[], audit_log_ref }`

## POST /investment/workflows/compliance-rule-question

- req: `{ question, fund_id?, compliance_category?, collection_id? }`
- res 200: `{ status, answer?, citations[], risk_decision, review_required, warnings[] }`

## GET /investment/drafts/{artifact_id}

- res 200: `{ artifact_id, artifact_type, status, compliance_review_status, payload, source_citations, disclosure_evidence_ids, audit_log_ref }`

## POST /investment/drafts/{artifact_id}/review

- req: `{ action:"assign|submit|approve|reject|archive", reviewer_id?, reviewer_group?, review_comment?, approval_decision? }`
- res 200: `{ artifact_id, status, reviewed_at?, audit_log_ref }`

## POST /investment/drafts/{artifact_id}/compliance-review

- req: `{ action:"assign|request_changes|approve|reject", reviewer_group?, required_changes?, review_comment?, decision? }`
- res 200: `{ artifact_id, compliance_review_status, audit_log_ref }`

## GET /investment/disclosure-evidence/{artifact_id}

- res 200: `{ artifact_id, disclosure_evidence:[{ statement_id, source_citations, source_document_ids, source_as_of_date, source_effective_date, evidence_status }] }`

## GET /investment/dashboard

- req query: `time_range`, `fund_id?`, `department_id?`, `document_type?`
- res 200: `{ widgets, warnings[] }`

## GET /investment/kpi

- res 200: `{ self_resolution_rate, average_time_to_answer, grounded_answer_rate, insufficient_evidence_rate, low_rating_rate, unanswered_question_count, frequently_referenced_documents, obsolete_document_candidates, knowledge_gap_topics, regulated_query_count, advice_boundary_trigger_count, compliance_review_pending_count, compliance_gate_block_count, disclosure_inconsistency_count, rfp_response_draft_count, ddq_response_draft_count, marketing_material_review_count, inquiry_response_time_reduction }`

## GET /investment/audit

- res 200: `{ events:[{ event_type, resource_type, resource_id, decision, reason, policy_version, timestamp, trace_id }] }`

## GET /investment/governance/status

- res 200: `{ no_train, audit_coverage, advice_boundary, regulated_activity, disclosure_evidence, compliance_review, record_retention, provider_governance, financial_ai_governance_notes }`
