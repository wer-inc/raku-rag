# PoC Evaluation Plan

## Purpose

Evaluate whether the RAG platform and industry solution layers are safe, grounded, useful, and cost-aware before broad implementation.

## Dataset Strategy

For each industry, prepare 20-50 representative Japanese documents where possible:

- Manufacturing: manuals, work instructions, alarm lists, trouble reports, inspection sheets, quality reports.
- Real estate: lease contracts, important explanations, management rules, repair histories, inspection reports, owner reports, invoices, inquiry histories.
- Investment: prospectuses, trust deeds, monthly reports, fund reports, marketing material, compliance rules, RFP/DDQ, inquiry histories, risk and ESG reports.

Include positive answer cases, insufficient evidence cases, obsolete/draft-only evidence cases, ACL-denied cases, spreadsheet/table/cell citation cases, and high-risk cases.

## Parser/OCR Evaluation

Candidates:

- AWS-only/customer-managed parser path
- Azure Document Intelligence
- Google Document AI
- Textract
- OSS parser/Tesseract where appropriate

Metrics:

- parser output schema validity
- table structure accuracy
- spreadsheet cell_range citation accuracy
- OCR text accuracy sample
- layout region accuracy sample
- p95 parse/index latency
- provider policy compliance
- residency/no-train opt-in compliance

## Embedding/Retrieval/Rerank Evaluation

Candidates:

- Cohere Embed Multilingual v3 via Bedrock
- Titan embeddings if needed
- metadata exact + identifier/code + vector + rerank
- vector + rerank baseline
- optional hybrid search or OpenSearch fallback

Metrics:

- recall@5
- recall@10
- MRR
- exact code lookup success rate
- citation accuracy
- context precision/recall where dataset supports it
- p95 search latency
- query cost

## Answer and Groundedness Evaluation

Metrics:

- groundedness
- citation accuracy
- insufficient evidence correct rejection rate
- no hallucinated answer rule compliance
- answer latency p50/p95
- query cost

## Security and Governance Hard Gates

Absolute gates:

- tenant leakage = 0
- ACL leakage = 0
- deleted/tombstoned documents searchable = 0
- unauthorized context in LLM/VLM input = 0
- raw retrieved context logging violation = 0
- no-train policy violation = 0
- external parser without ProviderPolicy opt-in = 0
- AI DraftArtifact auto-approval = 0

## Industry-Specific Evaluation

### Manufacturing

- high-risk safety query requires approved/effective citation
- dangerous work answer shows review/qualified-person notice where applicable
- provisional/permanent countermeasure distinction preserved
- safety_gate_block_count measured

### Real Estate

- contract/cost/restoration/legal risk requires approved/effective citation
- occupant/lessee personal data redacted and ACL-filtered
- obsolete/draft evidence not used as formal basis
- risk_gate_block_count measured

### Investment

- advice boundary triggered for advice-like intent
- regulated query requires approved/effective citation
- marketing material contradiction detection measured
- DisclosureEvidence generated for regulated drafts
- compliance_review_pending_count measured

## Acceptance Thresholds

MVP uses baseline-relative gates for quality and absolute gates for security/governance. Initial PoC should establish baselines rather than claim final production thresholds.

Minimum acceptance before implementation roadmap advances beyond Phase 1:

- all security/governance hard gates pass
- exact identifier lookup works in representative cases
- citations are traceable and inspectable
- insufficient evidence behavior is correct in representative no-evidence cases
