# API Contracts: Real Estate Property Management Knowledge RAG

All APIs inherit 001 auth, tenant isolation, ACL pre-filter, citation, groundedness, audit, cost, redaction, no-train, and ProviderPolicy behavior. 003 APIs map internally to 010 IndustryProfile/workflow/draft/dashboard services.

## POST /real-estate/metadata/import

- req: `{ collection_id, records:[{ document_id?, source_document_id?, metadata }] }`
- res 202: `{ import_run_id, accepted_count, rejected_count, status_url }`
- Audit: `real_estate_metadata_import`.

## POST /real-estate/documents/enrich

- req: `{ document_id, metadata?, enrichment_options? }`
- res 200: `{ document_id, real_estate_metadata, warnings[] }`

## GET /real-estate/properties/{property_id}/knowledge

- res 200: `{ property_id, documents[], active_contracts[], repair_summary, owner_reports[], citations[] }`
- ACL: unauthorized property data returns 404/empty without existence leakage.

## GET /real-estate/units/{unit_id}/knowledge

- res 200: `{ unit_id, lease_contracts[], repair_cases[], inquiries[], documents[], citations[] }`

## POST /real-estate/workflows/contract-question

- req: `{ question, property_id?, unit_id?, lease_contract_id?, occupant_id?, collection_id? }`
- res 200: `{ status, answer?, citations[], risk_decision, gate_decision, review_required?, warnings[] }`
- errors: `insufficient_evidence`, `risk_gate_blocked`, `unauthorized`.

## POST /real-estate/workflows/repair-investigation

- req: `{ property_id?, unit_id?, equipment_type?, repair_category?, symptom, time_range? }`
- res 200: `{ status, similar_cases[], summary, citations[], warnings[] }`

## POST /real-estate/workflows/occupant-reply-draft

- req: `{ inquiry_text, property_id?, unit_id?, occupant_id?, tone?, reviewer_id?, reviewer_group? }`
- res 201: `{ artifact_id, artifact_type:"occupant_reply", status:"draft", source_citations[], audit_log_ref }`

## POST /real-estate/workflows/owner-report-draft

- req: `{ property_id, owner_id?, repair_case_ids[]?, report_period?, reviewer_id?, reviewer_group? }`
- res 201: `{ artifact_id, artifact_type:"owner_report", status:"draft", source_citations[], audit_log_ref }`

## POST /real-estate/workflows/move-out-checklist-draft

- req: `{ unit_id, lease_contract_id?, move_out_date?, reviewer_id?, reviewer_group? }`
- res 201: `{ artifact_id, artifact_type:"move_out_checklist", status:"draft", source_citations[], audit_log_ref }`

## POST /real-estate/workflows/restoration-explanation-draft

- req: `{ unit_id, restoration_case_id?, inquiry_text?, reviewer_id?, reviewer_group? }`
- res 201: `{ artifact_id, artifact_type:"restoration_explanation", status:"draft", source_citations[], audit_log_ref }`

## GET /real-estate/drafts/{artifact_id}

- res 200: `{ artifact_id, artifact_type, status, payload, source_citations, review_state, audit_log_ref }`

## POST /real-estate/drafts/{artifact_id}/review

- req: `{ action:"assign|submit|approve|reject|archive", reviewer_id?, reviewer_group?, review_comment?, approval_decision? }`
- res 200: `{ artifact_id, status, reviewed_at?, audit_log_ref }`

## GET /real-estate/dashboard

- req query: `time_range`, `branch_id?`, `property_id?`, `document_type?`
- res 200: `{ widgets, warnings[] }`

## GET /real-estate/kpi

- res 200: `{ self_resolution_rate, average_time_to_answer, inquiry_response_time_reduction, grounded_answer_rate, insufficient_evidence_rate, low_rating_rate, unanswered_question_count, frequently_referenced_documents, obsolete_document_candidates, knowledge_gap_topics, draft_review_completion_rate, high_risk_query_count, risk_gate_block_count, repair_case_lookup_count, owner_report_draft_count, occupant_reply_draft_count }`

## GET /real-estate/audit

- res 200: `{ events:[{ event_type, resource_type, resource_id, decision, timestamp, trace_id }] }`

## GET /real-estate/governance/status

- res 200: `{ no_train, audit_coverage, risk_gate, draft_review, personal_data_redaction, provider_governance, ismap_readiness_memo, poc_readiness }`
