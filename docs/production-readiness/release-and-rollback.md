# Release & Rollback Runbook — raku-rag

**Date:** 2026-06-21 · Owner: platform on-call · Scope: P1-12 tail (deployment operability).
Companion to `rag-production-readiness.md` (audit), `risk-register.md` (PR-012/PR-014), and the CI
workflows under `.github/workflows/`. **No production secrets live in this repo** — auth to AWS is via
GitHub OIDC role assumption (see §3); data-plane secrets live in AWS Secrets Manager (CDK-managed).

> Safety boundary reminder (`docs/loop-engineering.md §6`): a release that changes the high-risk
> answer gate, draft approval, no-train, or audit behavior is **always human-reviewed**. Rolling
> *back* to a known-good image is allowed at any severity; rolling *forward* through the safety
> boundary is not an incident shortcut.

---

## 1. Release checklist — preflight → go/no-go

A build is **GO** only if every row is GREEN. Any RED = **NO-GO** (do not promote to prod).

### 1.1 Automated gates (must be GREEN on the release commit)
| Preflight check | Where | Go criterion |
|---|---|---|
| Tier A hard gates (ACL leak / tenant isolation / deletion / 6 mfg safety + eval security probes) | `gate.yml` → `scripts/gate.sh a` | GREEN, **0 tolerance** |
| Full suite | `gate.yml` → `scripts/gate.sh all` | GREEN |
| §5 verification/generation separation | `gate.yml` separation job | "separation OK" |
| Tier B Postgres/pgvector/RLS parity (on relevant change) | `gate.yml` tier-b | GREEN |
| RT1 local dependency compose smoke | `gate.yml` rt1-compose | GREEN |
| Eval quality + security gate (incl. **golden-corpus committed baseline**, no regression) | `ci.yml` eval-gate + `tests/integration/test_golden_corpus.py` | GREEN; precision@k/MRR/faithfulness ≥ baseline |
| Secret scan (detect-secrets vs `.secrets.baseline` + seeded self-test) | `security-scan.yml` | GREEN |
| Image build + SBOM + Trivy scan (api/web/worker) | `deploy-checks.yml` | builds GREEN; SBOM produced; Trivy findings triaged (see §4) |
| CDK synth | `deploy-checks.yml` cdk-synth | synth OK |
| Migration runner smoke (apply + idempotency) | `ci.yml` | "applied 1 migration" + idempotent |

### 1.2 Human go/no-go (release captain)
- [ ] Diff reviewed; any change touching the **safety boundary** has explicit human approval (SC-MFG-006/007/009/010, GAP-S items).
- [ ] **Open Critical/High PR risks** reviewed (`risk-register.md`): no Critical PR is regressed by this release. (Known still-open: **PR-003** safety-overlay-not-deployed, **PR-016/GAP-S3** source-poisoning — releasing does not *worsen* them.)
- [ ] DB migrations in this release are **expand-only / backward-compatible** (see §3.2); destructive changes are staged separately.
- [ ] Rollback target identified: previous prod image digest + previous migration version recorded (see §2).
- [ ] Staging smoke passed (deploy to staging → `/v1/health` 200, a grounded answer with citations, a cross-tenant query returns nothing).
- [ ] On-call + comms owner assigned for the release window.

**GO** = all automated GREEN + all human boxes checked. Otherwise **NO-GO**.

---

## 2. Rollback runbook

Roll back the moment a release breaches an SLO/safety invariant; investigate after. Record the
previous-good **image digest** and **migration version** at deploy time (§1.2) so rollback is mechanical.

### 2.1 Application image rollback (fastest; default)
1. Identify the last-good image digest (from the release record / ECR `raku-rag-{api,web,worker}` immutable tags).
2. Redeploy the previous digest: re-run the CD workflow (§3) with `image_tag=<previous-digest>`, or in AWS roll the ECS service back to the previous task definition revision.
3. Verify: `/v1/health` 200; a known grounded query returns citations; cross-tenant probe returns nothing.
4. App rollback is **safe and unconditional** — images are immutable and carry no schema changes by themselves.

### 2.2 Migration rollback / forward-fix policy
**Default = forward-fix, not down-migrate.** Each Postgres migration has a paired `*.down.sql`
(`infra/db/migrations/postgres/0001..0006`), validated up+down in `gate.yml` tier-b and
`scripts/postgres-migration-smoke.sh`. But in prod:
- **Expand/contract discipline:** ship schema changes expand-only (additive) so the *previous* app image keeps working against the *new* schema → app rollback (§2.1) needs no DB change. Destructive/contracting changes go in a later release after the old code is gone.
- **A `.down.sql` is run ONLY when** the migration is non-destructive (no dropped columns/data) AND app rollback alone cannot restore service. Data-affecting migrations are **never auto-down in prod** — forward-fix with a new migration instead.
- **Never** run `.down.sql` that drops data to "undo" a bad release; restore from the RDS snapshot (35-day retention, prod) if data integrity is at risk, then forward-fix.
- Migrations are idempotent + ledgered (`schema_migrations`), so re-apply is safe.

### 2.3 Configuration rollback
- App/runtime config and secrets are in **AWS Secrets Manager** (CDK-managed, versioned). Roll back by pinning the previous secret version; no repo change needed.
- CDK/infra config changes roll back via `git revert` of the infra commit → re-run CD (`cdk deploy`).
- Feature/policy toggles (provider/logging/retrieval policies) are tenant-scoped admin state — revert via the admin API, audited (`provider_config_audit_events`).

### 2.4 Incident communications
| Severity | Trigger | Action | Comms |
|---|---|---|---|
| **SEV-1** | Cross-tenant/ACL leak, deleted-content reappearance, high-risk wrong answer asserted, secret exposure | **Immediate app rollback (§2.1)**; page platform on-call + security | Status page + stakeholders within 15 min; post-incident review required |
| **SEV-2** | Eval/quality regression past baseline, elevated error/fallback rate, failed ingestion DLQ backlog | Roll back or hotfix; notify on-call | Update within 1 h |
| **SEV-3** | Degraded latency/cost, non-blocking scan findings | Track + fix in next release | Async note |
- The named **top risks** (ACL leakage, tenant isolation, deletion reappearance) and any **safety-boundary** breach are **SEV-1 by definition**.
- Every SEV-1/2 gets a written post-incident review; if a gate *should* have caught it, file a new hard-gate test (loop-engineering §3) — green ≠ correct (cf. GAP-S3).

---

## 3. CD path (no production secrets in repo)

Authentication is **GitHub OIDC → AWS IAM role assumption** — there are **no static AWS keys committed**.
A safe, manual, environment-gated skeleton lives at `.github/workflows/deploy.yml` (see §3.3).

### 3.1 Pipeline shape
```
release commit (all §1.1 gates GREEN)
  → assume AWS deploy role via OIDC (id-token: write; role from repo/env var, not a secret)
  → build + push images to ECR (immutable tags = git SHA / digest)
  → apply DB migrations (expand-only) against the target cluster
  → cdk deploy to STAGING → staging smoke
  → manual approval (GitHub Environment: production)
  → cdk deploy to PRODUCTION → prod smoke → record image digest + migration version (rollback target)
```

### 3.2 Secret handling
- AWS auth: OIDC web-identity, role ARN supplied as a **repo/environment variable** (`vars.AWS_DEPLOY_ROLE_ARN`), not a secret. The role's trust policy restricts it to this repo + `environment`.
- Data-plane secrets (DB creds, signing keys): **AWS Secrets Manager**, provisioned by CDK and injected into ECS as `secrets` (not env literals). Never in the repo (`.env` is gitignored; only `.env.example` placeholders are committed; enforced by `security-scan.yml`).

### 3.3 Safe skeleton (`deploy.yml`)
- `workflow_dispatch` only (never auto-runs on push).
- Job gated by a GitHub **Environment** (`staging` / `production`) → production requires a configured reviewer (manual approval).
- **Inert until configured:** a preflight step hard-fails with setup instructions if `vars.AWS_DEPLOY_ROLE_ARN` / `vars.AWS_REGION` are unset, so the skeleton cannot deploy anything in a fresh repo.
- `dry_run` input defaults to **true** → prints the plan without mutating AWS; a real deploy requires `dry_run=false` *and* the environment approval.

---

## 4. Trivy: when to flip from report-only to blocking

`deploy-checks.yml` runs Trivy at `exit-code: "0"` (report-only) with `ignore-unfixed: true` today, so a
new scanner doesn't block builds on a wall of pre-existing base-image CVEs. Flip to blocking deliberately:

1. **Triage** the first full report per image (api/web/worker): classify each HIGH/CRITICAL as *fixable* (bump base image / dep) or *accepted/unfixable*.
2. Add accepted findings to a committed **`.trivyignore`** (CVE id + justification + review date) — this is the allowlist, analogous to `.secrets.baseline`.
3. Bump base images / dependencies to clear the fixable HIGH/CRITICALs.
4. **Flip** `exit-code: "0"` → `"1"` in `deploy-checks.yml` (keep `ignore-unfixed: true`, `severity: HIGH,CRITICAL`). Now a *new, fixable* HIGH/CRITICAL blocks the build.
5. Re-review `.trivyignore` on a cadence (e.g., monthly) so accepted CVEs don't linger silently.

**Blocking criterion (target):** build fails on any **fixable HIGH or CRITICAL** not in `.trivyignore`. Do **not** flip before steps 1–3 (blind blocking just makes the pipeline red and trains people to bypass it).

---

## 5. Still open (tracked, not in this doc's scope)
- CD pipeline is a **skeleton** (`deploy.yml`) — wiring it to a real AWS account (OIDC role, ECR repos, environments) is an ops task, not a code change.
- **PR-003** (safety overlay not on the deployed path) and **PR-016/GAP-S3** (source-poisoning) remain open safety items — see `risk-register.md`. A release must not regress them.
- Standalone **incident runbook** + **SLO/SLA** (PR-005/P2-4) extend §2.4 with detection thresholds and error budgets.
