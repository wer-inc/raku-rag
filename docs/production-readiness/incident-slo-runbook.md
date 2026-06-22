# Incident, SLO/SLA, and Model Rollback Runbook

**Date:** 2026-06-22  
**Owner:** platform on-call  
**Scope:** P2-4 local production-readiness closure for raku-rag. Companion to
`release-and-rollback.md`, `release-execution-checklist.md`, `risk-register.md`, and
`rag-production-readiness.md`.

This document defines the repo-side operating contract. Final thresholds must be tuned after the
first production load window, but the release decision no longer depends on tribal knowledge.

---

## 1. Service level draft

These are internal SLOs until the service has at least 30 days of production traffic. Do not publish
an external SLA until the observed error budget and support coverage are confirmed.

| Area | SLI | Initial SLO | Hard release gate |
|---|---|---|---|
| Availability | successful API requests / total API requests | 99.5% monthly | staging and prod smoke pass |
| API latency | p95 `/v1/answer` complete latency | <= 2,000 ms monthly | load test p95 <= `Settings.target_p95_latency_ms` |
| Tail latency | p99 `/v1/answer` complete latency | <= 5,000 ms monthly | p99 recorded before GO |
| Retrieval safety | cross-tenant, ACL, deletion, source-poisoning probe failures | 0 | any failure is NO-GO / SEV-1 |
| Grounding quality | golden-corpus precision@k, MRR, faithfulness | >= committed baseline | eval gate GREEN |
| Ingestion freshness | p95 accepted ingest to searchable | <= 15 min | queue age alarm not breaching |
| Ingestion reliability | DLQ visible messages | 0 sustained | DLQ alarm not breaching |
| Error rate | ALB target 5xx rate | < 1% over 5 min | alarm not breaching |
| Privacy | raw secret/PII in logs, traces, eval artifacts | 0 | secret/redaction gates GREEN |

Error budget policy:
- Burn > 25% of monthly budget in 24h: freeze feature releases until root cause is understood.
- Burn > 50% of monthly budget in 7d: require release-captain approval for any non-hotfix deploy.
- Any safety/privacy invariant breach bypasses the error budget and is SEV-1.

## 2. Signal sources

| Signal | Source | Notes |
|---|---|---|
| API 5xx, latency, target health | ALB / ECS / CloudWatch | CDK defines alarms; actions are wired in the real AWS account. |
| RAG stage metrics | app JSON metric logs via `StructuredLogTelemetryExporter` | Enable with `RAKU_TELEMETRY_EXPORT_ENABLED=true`. |
| Traces | sanitized app span JSON logs | No raw query, raw context, raw user id, or raw tenant id. |
| Eval quality and security | `EvaluationRun` plus golden baseline | Includes model/prompt/dataset `version_registry`. |
| Ingestion queue and DLQ | SQS / worker logs / processing state | DLQ visibility and queue age are alertable. |
| Audit trail | `audit_logs` and manufacturing audit writer | Reference-only, tenant-scoped, redacted. |

## 3. Severity and first response

| Severity | Examples | Page | First action |
|---|---|---|---|
| SEV-1 | tenant/ACL leak, deleted content reappears, high-risk unsafe assertion, source-poisoning pass, secret exposure | immediate | contain first: disable traffic or roll back image, then investigate |
| SEV-2 | eval baseline regression, p95/p99 breach, DLQ backlog, ingestion freshness breach | immediate during business hours; otherwise on-call | roll back or hotfix if user impact continues |
| SEV-3 | non-blocking latency/cost drift, accepted CVE review, noisy alerts | next business day | file follow-up and monitor |

Initial incident checklist:
1. Create an incident record with time, release SHA, image digest, tenant impact, and severity.
2. Freeze deploys unless the next deploy is the rollback or approved hotfix.
3. Capture the last 30 minutes of app metric logs, traces, ALB/ECS metrics, SQS metrics, and eval run ids.
4. If SEV-1, execute the app rollback in `release-and-rollback.md §2.1`.
5. Communicate status using `release-and-rollback.md §2.4`.
6. After restore, file a post-incident review with the missing gate or alert that would have caught it earlier.

## 4. Incident playbooks

### 4.1 Security or safety invariant breach
Trigger: ACL/tenant/deletion/source-poisoning/high-risk probe failure, user report, or audit anomaly.

Actions:
1. Roll back the application image to the previous known-good digest.
2. Disable the affected tenant or route if the leak is tenant-scoped and rollback is not enough.
3. Query audit logs by request id / citation id / document id, not raw user text.
4. Re-run Tier A and the eval security probes against the rollback candidate.
5. Keep release frozen until a new hard-gate test reproduces the failure.

### 4.2 Latency or capacity breach
Trigger: p95 > 2s, p99 > 5s, ALB 5xx > 1%, or SQS queue age alarm.

Actions:
1. Check whether the latency is retrieval, rerank, generation, or DB by stage metrics.
2. If generation dominates, cap LLM calls/context tokens or roll back the model/prompt version.
3. If retrieval dominates, inspect vector/lexical query plans and index usage.
4. If ingestion dominates, scale the worker service or pause non-urgent batch jobs.
5. If a release introduced the regression, roll back the image and keep the new build out of prod.

### 4.3 Retrieval quality or grounding regression
Trigger: golden-corpus baseline failure, faithfulness regression, customer-reported wrong citation.

Actions:
1. Stop promotion and compare `version_registry` between the failed run and committed baseline.
2. If model/prompt changed, roll back that config or image and re-run the baseline.
3. If embedding provider/dimension changed, do not hot rollback unless the previous vector index still exists.
4. Add the failing query to the golden corpus or red-team corpus after scrub/review.

### 4.4 Ingestion or indexing backlog
Trigger: DLQ visible messages > 0, queue age breach, processing state stuck.

Actions:
1. Inspect DLQ payload references and worker logs.
2. Retry only idempotent items; ingestion run creation is idempotency-key protected.
3. If parser/chunker/model configuration caused the issue, roll back config and reprocess impacted documents.
4. For suspected data corruption, pause reindex, snapshot the DB, and forward-fix.

## 5. Prompt and model rollback

Prompt/model changes are production changes even when no code changes. They must be tied to
`version_registry` and baseline results.

Rollback order:
1. **Provider/model config rollback:** restore the previous AWS Secrets Manager version or admin
   provider policy value. Re-run the golden baseline before resuming rollout.
2. **Prompt template rollback:** if the prompt is config-backed, restore the previous prompt template
   version; if it is code-backed, roll back the app image. The eval baseline must show the old
   `prompt_template_version`.
3. **Injection guard rollback:** only roll back to a previously gated guard version. Never disable the
   guard to fix latency without release-captain approval.
4. **Embedding model rollback:** treat as an index migration. Roll back only if the previous embedding
   column/index is still available. Otherwise forward-fix by reindexing/backfilling and refreshing the
   golden baseline.
5. **VLM/captioning rollback:** restore the prior model/prompt version and re-run visual redaction and
   asset tests before promotion.

GO criteria after rollback:
- Tier A GREEN.
- Eval baseline GREEN with expected `version_registry`.
- A known grounded query returns citations.
- A cross-tenant query returns no content.
- No DLQ or 5xx alarms are breaching.

## 6. External SLA posture

Recommended launch posture:
- Do not promise a public financial SLA for the first beta window.
- Publish an internal support target instead: SEV-1 response within 15 minutes, SEV-2 within 1 hour,
  SEV-3 next business day.
- After 30 days of measured production traffic, convert the availability SLO into an external SLA only
  if the observed monthly availability and on-call coverage can support it.

