# Release Execution Sheet — operator runbook for the real-infra remainder

**Date:** 2026-06-21 · Companion to `rag-production-readiness.md` (what), `release-and-rollback.md`
(policy), `loop-state.md` (history). This is the **copy-pasteable "run these in order"** sheet for the
items that **cannot be completed or verified from the dev sandbox** (no Postgres, AWS, Docker daemon,
load infra, or Git remote auth here). Everything build-and-sandbox-verifiable is **done, green, and
committed** on branch `003-production-readiness-hardening` (5 commits; full suite 666 + NestJS e2e 77).

Run on a host with Docker + a pgvector Postgres + AWS creds. Each step is a release-gate; a RED stops GO.

---

## 0. Push + PR (your base decision)
The branch sits on top of the *other task's* perf commit `e26c397`, which is **not on `origin` yet** —
so the PR base changes what it contains. Choose the base, then:
```bash
git push -u origin 003-production-readiness-hardening
gh pr create --base <002-manufacturing-field-knowledge-rag | main> \
  --head 003-production-readiness-hardening \
  --title "Production-readiness hardening (P0-1, P1-1/2/5/8/12/13, GAP-S3, T117/T118)" \
  --body-file docs/production-readiness/rag-production-readiness.md
```
Review the **safety-boundary commit `1b50866`** (GAP-S3 / P1-1 / P1-2) as a unit before merge.

## 1. CI all-green on the runner
Push triggers `gate.yml` (Tier A + full suite + RT1 compose + §5 separation) and `ci.yml`
(lint/unit/contract/integration/security-hard-gate/eval-gate) + `security-scan.yml` + `deploy-checks.yml`.
Confirm every job is green. Tier-B and Tier-D are change-gated and run on the GitHub Docker host.

## 2. Tier B — real Postgres + pgvector  (final-criteria: Tier B green)
```bash
docker compose -f infra/docker-compose.yml up -d postgres
POSTGRES_URL=<conn> scripts/postgres-migration-smoke.sh      # applies 0001..0007 up/down, RLS smoke
scripts/gate.sh b                                            # security parity + ranking parity on real PG
```
Then the P1-1 Postgres-data step (the one code item left): on the manufacturing ingest path, persist
`ManufacturingDocumentMetadata.to_mapping()` into `Document.metadata` (and chunk metadata) so the
overlay resolver reads it back over `ProductionSystem`; add a Tier-B test asserting the high-risk gate
fires over Postgres. (`to_mapping`/`from_mapping` + the registry-backed resolver already exist.)

## 3. Performance — real numbers + EXPLAIN  (final-criteria: p95/p99 in budget)
```bash
# real load: point load_harness at the deployed service (large corpus, many tenants), record p50/p95/p99/QPS
POSTGRES_URL=<conn> scripts/postgres-explain-gate.sh         # fails on Seq Scan over chunks (index regression)
```
Compare p95/p99 to `Settings.target_p95_latency_ms` (2000ms) / `min_throughput_qps` (5).

## 4. Deploy + supply-chain gates
- Configure GitHub OIDC + `vars.AWS_DEPLOY_ROLE_ARN` / `vars.AWS_REGION`; run `deploy.yml` (dry-run first).
- Build/push images (Dockerfiles for api/web/worker) to ECR; `deploy-checks.yml` emits SBOM + Trivy.
- **Trivy → blocking:** triage the first HIGH/CRITICAL report, add accepted CVEs to a committed
  `.trivyignore`, bump fixable base images, then flip `exit-code: "0"`→`"1"` in `deploy-checks.yml`
  (`release-and-rollback.md §4`).

## 5. Operational dry-runs  (real env)
- **Rollback** (`release-and-rollback.md §2`): redeploy a prior image digest; confirm `/v1/health` + a
  grounded answer + cross-tenant probe returns nothing.
- **Migration forward-fix / down:** confirm expand-only on the cluster; `*.down.sql` only for
  non-destructive rollback; data-affecting → forward-fix.
- **Backup/restore:** restore from an RDS snapshot to a scratch instance; verify a known answer + RLS.

## 6. Final release GO  (human judgment — `release-and-rollback.md §1`)
GO only when: Tier A/B green · security probes default-on · golden-corpus baseline green · no
ACL/tenant/deletion leakage · high-risk safety gate green · p95/p99 in budget · raw-context/secret/PII
logging violations 0 · all §1.2 human boxes checked · open Critical/High `risk-register.md` PRs not
regressed (note **PR-003/PR-016 → Mitigating/Fixed** but confirm the Postgres-data step in §2).

---

### Status of the four systems
- **安全性 (safety):** ✅ GAP-S3 fixed+gated · P1-2 in-flow defense · P1-1 overlay on the deployed path · probes default-on. (Tier-B confirmation in §2.)
- **本番運用 (ops):** ✅ retrieval failure logging · eval persistence · runbooks. Dry-runs in §5.
- **リリースゲート (release gate):** ✅ in CI (gate.yml full suite + ci.yml eval-gate incl. new safety/quality gates + security-scan + deploy-checks + migration smoke). Trivy-blocking flip in §4.
- **実環境接続 (real-env):** 🔶 §2–§5 — your infrastructure.
