# Release Execution Sheet — operator runbook for the real-infra remainder

**Date:** 2026-06-21 · Companion to `rag-production-readiness.md` (what), `release-and-rollback.md`
(policy), `loop-state.md` (history). This is the **copy-pasteable "run these in order"** sheet for the
items that **cannot be completed or verified from the dev sandbox** (real AWS deploy, production-scale
load, backup/restore, and human safety release approval). Everything build-and-sandbox-verifiable is
expected to pass before this sheet is used; the latest local reconciliation is recorded in
`loop-state.md`.

Run on a host with Docker + a pgvector Postgres + AWS creds. Each step is a release-gate; a RED stops GO.

For a paid pilot, first run the narrower CTO gate:

```bash
python3 scripts/pilot_readiness_status.py --fail-on-not-ready
```

If this reports `NOT READY`, do not sell the environment as pilot-ready. Complete the blocked
ledger units or evidence files shown in the report.

---

## 0. Commit / PR hygiene
Before using this real-infra checklist, put the local hardening changes into reviewable commits/PRs
and confirm the working tree contains no accidental files.
```bash
git diff --check
detect-secrets scan --baseline .secrets.baseline
scripts/gate.sh all
gh pr create --base <release-base> \
  --body-file docs/production-readiness/rag-production-readiness.md
```
Any change touching the safety boundary (GAP-S / SC-MFG controls) still needs explicit human review.

## 1. CI all-green on the runner
Push triggers `gate.yml` (Tier A + full suite + RT1 compose + §5 separation) and `ci.yml`
(lint/unit/contract/integration/security-hard-gate/eval-gate) + `security-scan.yml` + `deploy-checks.yml`.
Confirm every job is green. Tier-B and Tier-D are change-gated and run on the GitHub Docker host.

## 2. Tier B — real Postgres + pgvector  (final-criteria: Tier B green)
```bash
docker compose -f infra/docker-compose.yml up -d postgres
POSTGRES_URL=<conn> scripts/postgres-migration-smoke.sh      # applies migrations up/down, RLS smoke
scripts/gate.sh b                                            # security parity + ranking parity on real PG
```
The P1-1 Postgres-data/write path is repo-side implemented; this step verifies the merged code against
the target pgvector/Postgres version and tenant/RLS configuration.

## 3. Performance — real numbers + EXPLAIN  (final-criteria: p95/p99 in budget)
```bash
# real load: point load_harness at the deployed service (large corpus, many tenants), record p50/p95/p99/QPS
POSTGRES_URL=<conn> scripts/postgres-explain-gate.sh         # fails on Seq Scan over chunks (index regression)
```
Compare p95/p99 to `Settings.target_p95_latency_ms` (2000ms) / `min_throughput_qps` (5).

## 4. Deploy + supply-chain gates
- Configure GitHub OIDC + `vars.AWS_DEPLOY_ROLE_ARN` / `vars.AWS_REGION`; run `deploy.yml` (dry-run first).
- Build/push images (Dockerfiles for api/web/worker) to ECR; `deploy-checks.yml` emits SBOM + Trivy.
- **Trivy → blocking: ✅ DONE.** OS layers 0 HIGH/CRITICAL; prod-only installs remove dev CVEs; Next.js
  advisories are fixed; NestJS 11 removes prod picomatch exposure. The only accepted runtime HIGH family
  left is `multer@2.1.1` via `@nestjs/platform-express@11.1.27` (0 CRITICAL; availability DoS; no upload
  route; WAF/rate-limits in front) in committed `.trivyignore`; `exit-code: "1"` + `trivyignores:
  .trivyignore` in `deploy-checks.yml` (`release-and-rollback.md §4`). Remaining ops: build/push images
  to ECR once AWS is wired and confirm the updated CI image scan.
- Confirm `CloudWatchAlarmNames` exists after CDK deploy and wire alarm actions/escalation topics for API
  5xx, ingestion DLQ, ingestion queue age, Aurora CPU, and WAF rate-limit blocks.

## 5. Operational dry-runs  (real env)
- **Rollback** (`release-and-rollback.md §2`): redeploy a prior image digest; confirm `/v1/health` + a
  grounded answer + cross-tenant probe returns nothing.
- **Migration forward-fix / down:** confirm expand-only on the cluster; `*.down.sql` only for
  non-destructive rollback; data-affecting → forward-fix.
- **Backup/restore:** restore from an RDS snapshot to a scratch instance; verify a known answer + RLS.
- **Vector DR:** follow `vector-dr-runbook.md` on the scratch cluster: rebuild vector/lexical indexes,
  run `ANALYZE`, execute EXPLAIN gate + golden corpus, and record restore/reindex time.
- **Incident/SLO/prompt rollback:** review `incident-slo-runbook.md`, confirm the release has an on-call
  owner, and verify the configured model/prompt rollback path restores the expected eval
  `version_registry`.

## 6. Final release GO  (human judgment — `release-and-rollback.md §1`)
GO only when: Tier A/B green · security probes default-on · golden-corpus baseline green · no
ACL/tenant/deletion leakage · high-risk safety gate green · p95/p99 in budget · raw-context/secret/PII
logging violations 0 · SLO/incident thresholds accepted · all §1.2 human boxes checked · open Critical/High `risk-register.md` PRs not
regressed (note **PR-003/PR-016 → Fixed repo-side** but confirm the deployed stack is running those
gates).

---

### Status of the four systems
- **安全性 (safety):** ✅ GAP-S3 fixed+gated · P1-2 in-flow defense · P1-1 overlay on the deployed path · probes default-on. (Tier-B confirmation in §2.)
- **本番運用 (ops):** ✅ retrieval failure logging · eval persistence · release/rollback + incident/SLO/model-rollback runbooks. Dry-runs in §5.
- **リリースゲート (release gate):** ✅ in CI (gate.yml full suite + ci.yml eval-gate incl. new safety/quality gates + security-scan + deploy-checks + migration smoke). Trivy-blocking flip in §4.
- **実環境接続 (real-env):** 🔶 §2–§5 — your infrastructure.
