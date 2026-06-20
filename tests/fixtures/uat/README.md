# UAT Fixture Plan

This directory is the fixture design for `docs/uat/industry-usecases.md`. It intentionally starts as a
README-only plan: many fixtures are binary formats (PDF, DOCX, XLSX, CSV, images) and should be added
later in a controlled test-data commit with generated or synthetic content only.

No fixture may contain real tenant data, real personal data, real confidential fund data, or third-party
copyrighted source material. Use synthetic names and deterministic small files.

## Shared Fixtures

Proposed files:

| Path | Purpose |
|---|---|
| `common/tenants.json` | `tenant_alpha`, `tenant_beta` |
| `common/users.json` | `admin_alpha`, `operator_alpha`, `reviewer_alpha`, `restricted_alpha`, `operator_beta`, `sales_support_alpha` |
| `common/acl-grants.json` | Tenant, role, group, metadata, and denied-scope grants |
| `common/provider-policies.json` | Default no-train provider policy and negative providers |
| `common/logging-policies.json` | Raw context disabled default and opt-in variants |
| `common/deletion-probe.pdf` | Synthetic tombstone probe document |
| `common/beta-secret.pdf` | Cross-tenant leakage probe document |

Minimum shared metadata columns:

```text
tenant_id
collection_id
document_id
document_type
approval_status
effective_date
obsolete_at
superseded_by
access_scope
acl_tags
no_train_policy_ref
retention_policy_ref
```

## Manufacturing Fixtures

Proposed files:

| File | Document type | Status | Key metadata |
|---|---|---|---|
| `manufacturing/EQ-PRESS-100_取扱説明書_v3.pdf` | `manual` | `approved` | `factory_id=F001`, `equipment_id=EQ-PRESS-100`, `alarm_code=E-142`, `page=42` |
| `manufacturing/TR-2024-017_温度センサー異常.docx` | `trouble_report` | `approved` | `equipment_id=EQ-PRESS-100`, `alarm_code=E-142`, `section=原因と対策` |
| `manufacturing/月次点検表_温度系統.xlsx` | `checklist` | `approved` | `equipment_id=EQ-PRESS-100`, `sheet_name=温度系統`, `cell_range=C12:F18` |
| `manufacturing/EQ-PRESS-100_旧手順書_v2.pdf` | `manual` | `obsolete` | `superseded_by=EQ-PRESS-100_取扱説明書_v3` |
| `manufacturing/安全カバー作業メモ_非公式.docx` | `meeting_minutes` | `draft` | `hazard_tags=safety_cover` |
| `manufacturing/旧安全作業手順書.pdf` | `work_standard` | `obsolete` | `hazard_tags=safety_cover` |
| `manufacturing/品質不良履歴_2022-2025.xlsx` | `quality_report` | `approved` | `customer=A社`, `part_number=PN-10024`, row citations |
| `manufacturing/A社向け部品_寸法不良_是正報告.docx` | `quality_report` | `approved` | `case_id=Q-2024-018`, `measure_class` values |
| `manufacturing/検査基準書_寸法公差.pdf` | `inspection_standard` | `approved` | `defect_type=寸法不良` |
| `manufacturing/F002_EQ-PRESS-200_トラブル事例.pdf` | `trouble_report` | `approved` | ACL negative: `factory_id=F002`, `equipment_id=EQ-PRESS-200` |

Synthetic spreadsheet rows:

| case_id | customer | part_number | defect_type | cause | provisional | permanent | citation |
|---|---|---|---|---|---|---|---|
| `Q-2024-018` | `A社` | `PN-10024` | `寸法不良` | `治具摩耗` | `治具交換` | `点検周期短縮` | `品質不良履歴_2022-2025.xlsx!B18:H18` |
| `Q-2023-091` | `A社` | `PN-10024` | `寸法不良` | `測定条件ばらつき` | `再測定` | `測定手順改定` | `品質不良履歴_2022-2025.xlsx!B42:H42` |

## Real Estate Fixtures

Proposed files:

| File | Document type | Status | Key metadata |
|---|---|---|---|
| `real-estate/Aマンション_305号室_賃貸借契約書.pdf` | `lease_contract` | `approved` | `property_id=P001`, `unit_id=U305`, `page=6`, `section=禁止事項` |
| `real-estate/Aマンション_管理規約.pdf` | `management_rule` | `approved` | `property_id=P001`, `page=12`, `section=ペット飼育` |
| `real-estate/Aマンション_旧管理規約.pdf` | `management_rule` | `obsolete` | `superseded_by=Aマンション_管理規約` |
| `real-estate/305号室_退去立会記録.pdf` | `move_out_document` | `approved` | `legal_risk_category=restoration` |
| `real-estate/原状回復ガイドライン_社内メモ.docx` | `internal_manual` | `draft` | `financial_risk_category=fee_burden` |
| `real-estate/修繕履歴_Aマンション.xlsx` | `repair_history` | `approved` | `property_id=P001`, `unit_id=U305`, row citations |
| `real-estate/見積書_水漏れ_2024-05.pdf` | `estimate` | `approved` | `repair_category=water_leak`, amount metadata |
| `real-estate/請求書_水漏れ_2024-05.pdf` | `invoice` | `approved` | `repair_category=water_leak`, amount metadata |
| `real-estate/入居者問い合わせ履歴.csv` | `tenant_inquiry` | `approved` | `personal_data_category=occupant_contact`, row citations |
| `real-estate/保証人情報.pdf` | `occupant_personal_data` | `approved` | ACL negative: `personal_data_category=guarantor` |
| `real-estate/支払い履歴.xlsx` | `payment_history` | `approved` | ACL negative: `personal_data_category=payment_history` |

Synthetic repair rows:

| date | unit_id | incident | response | vendor | amount | citation |
|---|---|---|---|---|---:|---|
| `2024-05-12` | `U305` | `洗面台下水漏れ` | `パッキン交換` | `B設備` | `18000` | `修繕履歴_Aマンション.xlsx!B20:H20` |
| `2023-11-03` | `U305` | `上階漏水疑い` | `現地確認のみ` | `C工務店` | `0` | `入居者問い合わせ履歴.csv row 42` |

## Investment Fixtures

Proposed files:

| File | Document type | Status | Key metadata |
|---|---|---|---|
| `investment/FUND-001_交付目論見書_2025.pdf` | `delivered_prospectus` | `approved` | `fund_id=FUND-001`, `isin=JP0000000000`, fee/hedge sections |
| `investment/FUND-001_請求目論見書_2025.pdf` | `requested_prospectus` | `approved` | `fund_id=FUND-001`, detailed policy sections |
| `investment/FUND-001_月報_2025-05.pdf` | `monthly_report` | `approved` | `report_date=2025-05`, `performance_period=2025-05` |
| `investment/FUND-001_旧販売用資料.pdf` | `marketing_material` | `obsolete` | negative obsolete evidence |
| `investment/RFP_2025_運用体制質問.docx` | `rfp` | `draft` | RFP prompt source |
| `investment/DDQ_過去回答_2024.docx` | `ddq` | `approved` | prior approved answer |
| `investment/運用体制資料_2025.pdf` | `product_summary` | `approved` | operating structure evidence |
| `investment/ESG方針_2025.pdf` | `esg_report` | `approved` | ESG evidence |
| `investment/リスク管理体制.pdf` | `risk_report` | `approved` | risk management evidence |
| `investment/FUND-001_販売用資料_draft.pptx` | `marketing_material` | `draft` | contradiction-check target |
| `investment/パフォーマンス要因分析_2025-05.xlsx` | `risk_report` | `approved` | factor-analysis spreadsheet cells |
| `investment/運用会議メモ_2025-05.docx` | `investment_committee_minutes` | internal | internal reference, not customer-facing evidence |
| `investment/コンプライアンス規程_販売資料.pdf` | `compliance_manual` | `approved` | performance disclosure rules |
| `investment/社内規程_広告審査.pdf` | `internal_policy` | `approved` | marketing review rules |
| `investment/FUND-002_運用会議メモ.docx` | `investment_committee_minutes` | `approved` | ACL negative: `fund_id=FUND-002` |
| `investment/FUND-002_銘柄調査メモ.docx` | `research_memo` | `approved` | ACL negative: `research_memo_access=false` |

Minimum investment metadata columns:

```text
fund_id
fund_name
share_class_id
isin
asset_class
investment_target
currency_hedge_policy
trust_fee
risk_classification
document_type
as_of_date
effective_date
performance_period
disclosure_category
compliance_risk_category
advice_boundary_category
confidential_data_category
approval_status
```

## Phase Execution Order

| Phase | Cases | Required fixture status |
|---|---|---|
| UAT-0 | Documentation and fixture contract only | README and manifest-like metadata rows |
| UAT-1 | X-01, X-02, X-03, X-04 | Shared fixtures |
| UAT-2 | MFG-01, MFG-02, MFG-03, MFG-04, MFG-06, then MFG-05/MFG-07 | Manufacturing fixtures |
| UAT-3 | RE-01, RE-02, RE-03, RE-04, RE-06, then RE-05/RE-07/RE-08 | Real estate fixtures |
| UAT-4 | INV-01, INV-02, INV-03, INV-04, INV-07, then INV-05/INV-06/INV-08 | Investment fixtures |
| UAT-5 | Repeat X-01 through X-04 and dashboards after each industry run | All fixtures |

## Fixture Authoring Rules

- Prefer tiny deterministic files with one or two cited sections each.
- Include a machine-readable manifest beside binary fixtures when they are added:
  `tests/fixtures/uat/manifest.json`.
- The manifest should include `test_ids`, `document_id`, `path`, `document_type`, `approval_status`,
  `metadata`, `acl_scope`, `expected_citations`, and `negative_controls`.
- Use synthetic PII markers such as `PERSON_ALPHA_001`, not real names or contact details.
- Use synthetic fund data and avoid real performance claims.
- Add both positive and negative controls for every ACL/risk/evidence behavior.
