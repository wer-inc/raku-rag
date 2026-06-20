# UAT Use Case Verification

Verification date: 2026-06-20

This report verifies the use cases in `docs/uat/industry-usecases.md` against executable runtime
tests in the current worktree.

Status meanings:

- `VERIFIED`: executable tests exercise the use case behavior through existing implementation
  entrypoints and fixtures.
- `VERIFIED-BEHAVIORAL`: executable tests exercise the use case behavior through deterministic
  in-memory solution-layer runtime fixtures. This is UAT-level runtime proof, not a claim that every
  production adapter, API route, DB table, or browser flow from the corresponding Speckit task list is
  complete.

## Commands Run

Focused UAT runtime verification:

```text
PYTHONPATH=src python -m unittest tests.uat.test_industry_usecases -v
```

Result: `Ran 27 tests ... OK`.

Each test maps to one use case ID:

- `CrossIndustryUseCases`: X-01 through X-04
- `ManufacturingUseCases`: MFG-01 through MFG-07
- `RealEstateUseCases`: RE-01 through RE-08
- `InvestmentUseCases`: INV-01 through INV-08

Full repository gate:

```text
scripts/gate.sh all
```

Result: `Full suite: GREEN — Ran 566 tests ... OK (skipped=6)`.

## Summary

| Group | Total | Runtime-verified | Not executable | Notes |
|---|---:|---:|---:|---|
| Cross-industry X | 4 | 4 | 0 | Base platform/security/governance behavior is executable. |
| Manufacturing MFG | 7 | 7 | 0 | Existing manufacturing solution runtime plus UAT fixtures verify the behavior. |
| Real Estate RE | 8 | 8 | 0 | Deterministic real-estate solution runtime verifies the UAT behavior. |
| Investment INV | 8 | 8 | 0 | Deterministic investment solution runtime verifies the UAT behavior. |
| **Total** | **27** | **27** | **0** | No use case remains `NOT EXECUTABLE`. |

## Case-by-Case Results

| ID | Status | Runtime evidence | What is proven | Remaining gap |
|---|---|---|---|---|
| X-01 | VERIFIED | `tests.uat.test_industry_usecases.CrossIndustryUseCases.test_x_01_tenant_and_acl_boundary_prevents_cross_tenant_leakage` | Tenant and ACL-denied docs are excluded before scoring and absent from answers/citations. | None for runtime behavior. |
| X-02 | VERIFIED | `test_x_02_deleted_documents_never_reappear_in_answer_search_or_cache` | Deleted/tombstoned docs disappear from answer/search and dependent cache entries are invalidated. | None for runtime behavior. |
| X-03 | VERIFIED | `test_x_03_no_train_default_blocks_unverified_providers_and_training_use` | No-train default, opt-in requirement, fail-closed provider policy, and training-use refusal are enforced. | None for runtime behavior. |
| X-04 | VERIFIED | `test_x_04_raw_context_is_not_stored_while_reference_metadata_is_retained` | Raw retrieved context storage is disabled by default while citation/chunk/document reference metadata remains. | Docker/Langfuse host smoke remains environment-dependent outside this UAT test. |
| MFG-01 | VERIFIED | `test_mfg_01_equipment_error_answer_uses_approved_evidence_and_cell_anchor` | Equipment-error lookup returns approved/effective metadata and spreadsheet cell anchoring for `EQ-PRESS-100` / `E-142`. | Exact long-lived fixture corpus can still be materialized from `tests/fixtures/uat/README.md`. |
| MFG-02 | VERIFIED | `test_mfg_02_hazardous_work_blocks_without_approved_effective_safety_evidence` | Hazardous work without approved/effective safety evidence is blocked with no guessed procedure or citation. | None for runtime behavior. |
| MFG-03 | VERIFIED-BEHAVIORAL | `test_mfg_03_similar_trouble_case_returns_causes_and_candidate_measures` | Similar trouble cases return causes, recurrence prevention, citations, provisional/permanent split, and candidate labeling. | Exact external `PN-10024` spreadsheet fixture remains fixture-plan work. |
| MFG-04 | VERIFIED | `test_mfg_04_generated_checklist_is_draft_with_sources_and_never_self_approved` | AI checklist artifacts are draft-only, carry source citations/document IDs, and cannot self-approve. | None for runtime behavior. |
| MFG-05 | VERIFIED | `test_mfg_05_obsolete_or_draft_material_is_not_formal_primary_evidence` | Obsolete/draft-only evidence is not used as formal primary evidence and raises an obsolete warning. | None for runtime behavior. |
| MFG-06 | VERIFIED | `test_mfg_06_factory_department_acl_excludes_unauthorized_confidential_documents` | Factory/department/role ACL excludes denied factory documents before scoring and prevents citation/body leakage. | None for runtime behavior. |
| MFG-07 | VERIFIED | `test_mfg_07_dashboard_kpi_and_safety_telemetry_are_audit_derived` | Dashboard, KPI, and safety telemetry are audit-derived and expose required manufacturing counters. | Browser dashboard UAT remains separate UI work. |
| RE-01 | VERIFIED-BEHAVIORAL | `test_re_01_contract_condition_answer_uses_current_contract_and_rules` | Contract/rule answer cites current approved lease and management rules and excludes obsolete rules. | Real-estate API/DB contracts are now covered separately by `003` tests. |
| RE-02 | VERIFIED-BEHAVIORAL | `test_re_02_restoration_fee_question_is_review_required_and_excludes_draft_memo` | Restoration-fee burden questions require review, block final judgment, and exclude draft internal memos as formal evidence. | Real-estate API/DB contracts are now covered separately by `003` tests. |
| RE-03 | VERIFIED-BEHAVIORAL | `test_re_03_repair_history_returns_rows_with_document_and_cell_evidence` | Repair-history investigation returns table rows, amount visibility, sheet/cell evidence, estimates, invoices, and inquiry citations. | Real-estate API/DB contracts are now covered separately by `003` tests. |
| RE-04 | VERIFIED-BEHAVIORAL | `test_re_04_occupant_reply_is_draft_with_review_and_grounding` | Occupant replies are draft-only, grounded, assigned to reviewers, and not auto-approved. | Real-estate API/DB contracts are now covered separately by `003` tests. |
| RE-05 | VERIFIED-BEHAVIORAL | `test_re_05_owner_report_is_draft_with_financial_evidence_and_no_auto_approval` | Owner reports are draft-only, cite repair/estimate/invoice evidence, and require review. | Real-estate API/DB contracts are now covered separately by `003` tests. |
| RE-06 | VERIFIED-BEHAVIORAL | `test_re_06_personal_data_acl_denies_payment_contact_and_guarantor_leakage` | Restricted users receive no personal/payment/guarantor citations or existence details; denial is audited. | Real-estate API/DB contracts are now covered separately by `003` tests. |
| RE-07 | VERIFIED-BEHAVIORAL | `test_re_07_legal_judgment_is_not_auto_finalized` | Legal judgment questions are blocked/review-required and are not auto-finalized. | Real-estate API/DB contracts are now covered separately by `003` tests. |
| RE-08 | VERIFIED-BEHAVIORAL | `test_re_08_admin_dashboard_surfaces_real_estate_kpis_without_denied_drilldown` | Real-estate dashboard surfaces required counters without leaking denied personal-data drilldowns. | Real-estate API/DB contracts are now covered separately by `003` tests. |
| INV-01 | VERIFIED-BEHAVIORAL | `test_inv_01_fund_information_uses_current_prospectus_with_review_trace` | Fund facts cite current prospectuses and carry regulated-review trace. | Investment API/DB contracts are now covered separately by `006` tests. |
| INV-02 | VERIFIED-BEHAVIORAL | `test_inv_02_advice_boundary_blocks_buy_sell_or_suitability_recommendation` | Buy/sell/advice/suitability requests are blocked and limited to product-fact citations. | Investment API/DB contracts are now covered separately by `006` tests. |
| INV-03 | VERIFIED-BEHAVIORAL | `test_inv_03_rfp_ddq_response_is_draft_with_compliance_review_and_sources` | RFP/DDQ response artifacts are draft-only, source-backed, and pending compliance review. | Investment API/DB contracts are now covered separately by `006` tests. |
| INV-04 | VERIFIED-BEHAVIORAL | `test_inv_04_marketing_material_check_flags_disclosure_inconsistency` | Marketing-material checks flag disclosure/performance-claim inconsistency and require review. | Investment API/DB contracts are now covered separately by `006` tests. |
| INV-05 | VERIFIED-BEHAVIORAL | `test_inv_05_monthly_commentary_is_draft_and_avoids_future_guarantee` | Monthly commentaries remain draft-only and include non-guarantee language. | Investment API/DB contracts are now covered separately by `006` tests. |
| INV-06 | VERIFIED-BEHAVIORAL | `test_inv_06_compliance_rule_search_requires_review_and_cites_rules` | Compliance-rule answers cite approved rule documents and require review. | Investment API/DB contracts are now covered separately by `006` tests. |
| INV-07 | VERIFIED-BEHAVIORAL | `test_inv_07_confidential_fund_acl_blocks_other_fund_and_research_memo_leakage` | Other-fund internal minutes and research memos are denied without citations or existence details. | Investment API/DB contracts are now covered separately by `006` tests. |
| INV-08 | VERIFIED-BEHAVIORAL | `test_inv_08_dashboard_tracks_regulated_kpis_and_excludes_unauthorized_fund_detail` | Investment dashboard tracks regulated-query, advice-boundary, compliance-review, disclosure, and draft counters without unauthorized fund detail. | Investment API/DB contracts are now covered separately by `006` tests. |

## Interpretation

The current repository verifies all 27 listed use cases at runtime:

```text
Use case verification: 27/27 runtime-verified.
NOT EXECUTABLE cases: 0.
```

Important scope note: this is UAT-level executable verification. It proves the behavior through
runtime tests and deterministic solution-layer implementations. The `002` manufacturing, `003`
real-estate, and `006` investment tracks are now covered by separate API, migration, OpenAPI,
Dagster/control-plane, KPI, and PoC contract tests; the final `001` local dependency smoke is covered
by the RT1 GitHub-hosted Docker run recorded in `docs/loop-engineering.md`.

## Next Verification Work

1. Re-run `scripts/gate.sh all` after the report/contract updates in this cycle.
2. Materialize the exact synthetic file corpus from `tests/fixtures/uat/README.md` so every
   `VERIFIED-BEHAVIORAL` row can be promoted to file-fixture-backed `VERIFIED`.
