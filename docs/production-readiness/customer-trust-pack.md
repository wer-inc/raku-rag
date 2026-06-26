# Customer Trust Pack

This is the customer-facing security and operations summary for a scoped paid pilot. It is written to
avoid over-claiming: anything that still needs live evidence must be shown as pending until the paid
pilot gate passes.

## What We Can Say

- The platform is multi-tenant and uses deny-by-default ACL filtering before answers and citations.
- Deleted or tombstoned documents are blocked from search, answer, and citation paths.
- Manufacturing high-risk answers require approved and effective evidence or must abstain.
- AI-generated manufacturing artifacts remain draft until human review.
- Retrieved context is treated as untrusted data, not instructions.
- Structured CSV/XLSX questions are routed away from vector RAG when exact aggregation is required.
- Production profile is configured to use Cognito, Bedrock, OpenAI embeddings, Guardrails, Langfuse,
  CloudWatch, and Secrets Manager.

## What We Must Prove Per Pilot

- Cognito tenant, group, and role mapping matches the customer's operating model.
- Source ACL changes are reflected before pilot users can query affected content.
- No cross-tenant answer, citation, source preview, or asset can leak.
- Deletion and tombstone behavior works after reindex and restore.
- Bedrock Guardrails and high-risk safety classifiers block the agreed dangerous-query corpus.
- Langfuse and CloudWatch contain only sanitized operational telemetry.
- Rollback and restore are executable within the agreed pilot operating target.

## Customer Data Handling

- No customer secret or token is committed to the repository.
- Connector credentials must be stored in the configured secret store.
- Raw retrieved context is disabled in logs by default.
- PII and sensitive content detection metadata can be recorded, but raw sensitive context must not be
  copied into release evidence.
- Model-provider no-train and data-use posture must be included in the customer DPA or pilot terms.

## Operational Commitments For Pilot

- One named release captain.
- One named customer technical owner.
- One named safety/SME reviewer for high-risk manufacturing content.
- Daily review of failed ingestion jobs, DLQ, safety refusals, and high-risk telemetry during the
  pilot.
- Written approval before expanding datasource count, user count, model provider, or data residency.

## Open Items Until Evidence Exists

The following are not customer claims until evidence files are signed:

- Real Bedrock answer quality.
- Real OpenAI reindex completion.
- Langfuse trace visibility.
- CloudWatch alarm action delivery.
- Rollback and backup/restore drill success.
- SME sign-off for the dangerous/benign red-team corpus.

