# Decision Record: Retroactive-Spec Backlog (spec-less shipped features)

**Date**: 2026-06-26
**Status**: Accepted (backlog registered; specs deferred)
**Context source**: design-vs-implementation drift scan (2026-06-26) + `/speckit-analyze` on 002.

## Context

This project is Spec Kit–based, but during the loop-engineering phase several features shipped on
`develop` **with no Spec Kit design artifact** (no `specs/NNN-*`). Spec Kit is spec→code by design and
has no first-class code→spec reverse command, so these features have design recorded only in code,
ADRs, and `MEMORY.md` — not in a spec. This record registers them and the catch-up plan so the gap is
**tracked and decided**, not silently ignored.

CLAUDE.md "Beyond the 002/015 baseline" already acknowledges several of these as "NOT reflected" in the
SPECKIT block. This record makes the **retroactive-spec decision** explicit.

## Spec-less features (confirmed shipped, no spec)

| Feature | Evidence (as-built) | Spec status |
|---|---|---|
| **kintone connector** | `src/raku_rag/services/datasource_sync.py`; memory `datasource-connectors-e2e` | 0 spec hits — **no design** |
| **Live quality & safety scorecard** | 品質・KPI screen; `scripts/demo/quality_scorecard.sh`; memory `poc-demo-package` | 0 spec hits — **no design** |
| **Google Drive OAuth connector** | 3-legged OAuth datasource (memory `gdrive-oauth-connector-worktree`) | only a screen name in `specs/full-saas/screens.manifest.json` — **no design** |

Related (design exists but predates as-built, lower priority): datasource connector SSRF hardening &
trust/approval policy (memory `ssrf-connector-preship-gate`, `datasource-trust-policy-review`),
OpenAI embedding opt-in (#31), CJK-bigram retrieval, AWS CDK deploy topology.

## Decision

1. Adopt **Pattern A (retroactive spec)** for the three spec-less features when they are spec'd:
   `/speckit-specify` describing **as-built behaviour** → `/speckit-plan` → `/speckit-tasks`, with
   generated tasks marked `[x]` and annotated "retroactive: implementation preceded spec".
2. **Defer** the actual spec authoring (not blocking any current work; the prod-readiness ledger is the
   active SSOT). Pick up when a feature's design needs to be reviewed, extended, or sold/audited.
3. **Priority order** when picked up: (1) datasource connectors incl. kintone + SSRF/trust policy
   (safety-relevant, multi-connector), (2) quality & safety scorecard, (3) Google Drive OAuth.
4. The numbered specs (001–014) remain **historical design records**; they are not being retro-fitted
   to every later code change. Current SSOT for in-flight work stays `specs/prod-readiness/ledger.json`.

## Consequences

- The drift is now visible and owned, not lost.
- "All tasks `[x]` + gate green" still does not mean "fully spec'd" — this record is the pointer to
  what lacks a spec.
- No code changes; no gate impact.
