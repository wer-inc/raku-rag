# Pilot Demo Script

Use this script for sales engineering demos after the paid-pilot gate is green. Keep it fixed so the
demo proves the product's safety boundaries instead of becoming an improvised chat session.

## Setup

Required before the demo:

- Release commit recorded in `docs/production-readiness/evidence/local-gates.md`.
- Pilot corpus reindexed with the approved production embedding provider.
- Cognito test users for at least two tenants or tenant-like scopes.
- `scripts/prod-smoke.sh` completed with zero skips.
- SME-approved safety corpus loaded for high-risk examples.

## Storyline

1. **Grounded answer**
   - Ask a normal maintenance or quality question.
   - Show answer text, citations, source/version, and freshness.

2. **High-risk refusal**
   - Ask a question involving guard bypass, energized equipment, chemical spill, crane lift, or
     lockout/tagout evasion.
   - Show refusal or safe abstention and the safety reason.

3. **Obsolete or draft evidence**
   - Ask a question where an obsolete or draft document is retrievable.
   - Show that it is not used as primary evidence for a high-risk assertion.

4. **Structured CSV/XLSX aggregation**
   - Ask an aggregate/ranking/latest-value question over the pilot CSV/XLSX corpus.
   - Show `route="structured_tool"` and spreadsheet citation fields.

5. **Cross-tenant denial**
   - Switch to a user without access.
   - Ask the same grounded question and show no answer/citation leakage.

6. **Deletion non-reappearance**
   - Use a prepared deleted/tombstoned document probe.
   - Show search and answer do not return deleted content.

## Demo Rules

- Do not paste raw customer secrets or production tokens into the browser.
- Do not open Langfuse traces that contain raw context; use sanitized trace views only.
- Do not run new connector syncs during the customer call.
- Do not change model, guardrail, ACL, or datasource settings during the call.
- If a safety or ACL demo fails, stop the demo and open an incident review.

