# Paid Pilot Readiness

This is the CTO-facing gate for selling the next customer a limited paid pilot. It is intentionally
stricter than "demo works" and narrower than "general production ready".

## Positioning

Sell the first customer deployment as a controlled manufacturing knowledge pilot:

- One customer, one site or department, limited users.
- Curated datasources, explicit ACL mapping, and no open-ended connectors without review.
- Production profile enabled for the pilot runtime.
- No claim of broad enterprise GA until the production promotion gate is signed.

## Readiness Levels

| Level | Meaning | Allowed external claim |
|---|---|---|
| Pilot Candidate | Code, local gates, docs, and runbooks exist. Live evidence is incomplete. | "Ready to schedule a paid pilot readiness run." |
| Paid Pilot Ready | Live smoke, real model eval, safety sign-off, and rollback/restore evidence are complete. | "Ready for a scoped paid pilot." |
| Production Ready | Pilot evidence plus production promotion approval and customer-specific operating controls are signed. | "Ready for production launch under the signed scope." |

Current repo state must be checked with:

```bash
python3 scripts/pilot_readiness_status.py
```

Use `--fail-on-not-ready` in release automation.

## Pilot Runtime Contract

The pilot runtime is fixed unless the CTO approves a change:

- `RAKU_RUNTIME_PROFILE=production`
- Cognito authentication and signed backend principal only
- OpenAI `text-embedding-3-small` at 256 dimensions for the pilot embedding path
- Bedrock Claude for answer generation
- Bedrock rerank enabled
- Bedrock Guardrails enabled
- Langfuse enabled with sanitized traces only
- CloudWatch alarms wired to the operations topic
- Raw retrieved context, tokens, secrets, and PII are not logged

## Go Criteria

The pilot cannot be sold as ready until all requirements in
`specs/prod-readiness/paid-pilot-gate.json` pass.

The high-signal evidence is:

- Local and CI gates on the release commit.
- Real Bedrock generation, rerank, and Guardrails checks.
- OpenAI 256 reindex completion evidence.
- Production smoke with zero skips.
- ACL cross-tenant probe, deletion/tombstone probe, source poisoning refusal, and high-risk refusal.
- Langfuse trace existence with sanitized payload.
- CloudWatch alarm action wiring.
- Rollback and backup/restore drills.
- SME safety sign-off.
- Spend and scope approvals.

## No-Go Rules

- Do not mark a requirement complete from code review alone when it requires real infra.
- Do not run Bedrock/OpenAI billed eval or reindex without spend approval.
- Do not treat all-high-risk classifier behavior as a safety pass.
- Do not sell as production ready while rollback/restore evidence is missing.
- Do not include `goal.md`, local notes, or generated CDK context files as release evidence.

