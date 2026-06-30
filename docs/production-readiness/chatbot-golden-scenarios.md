# ChatBot Golden Scenario Evaluation

This is the release-facing quality loop for the internal authenticated ChatBot. UI smoke proves that
the page can be used; this scenario suite proves whether the bot answers the right things, refuses
the unsafe things, and avoids thin answers.

## What It Checks

- Reference scope is collection-wide (`collection_id=manuals`) and uses the same internal policy as
  the product UI: `chat-internal:manuals`.
- Grounded lookup answers include required facts and at least one expected citation.
- Approved high-risk procedures answer only when approved/effective evidence is cited.
- Troubleshooting answers include enough concrete cause/action facts to be useful.
- Draft, pending-review, obsolete, out-of-scope, and prompt-injection requests refuse or hand off.
- Thin answers are detected with `min_answer_chars` and `required_terms`.

## Run Locally

Start the local demo stack, then run:

```bash
bash scripts/demo/chatbot_golden_scorecard.sh --ensure-policy
```

The runner mints a local dev token through `WEB_BASE/api/dev-token` when no token is supplied.

## Run Against Staging

Issue a Cognito token with the existing smoke helper, then point the runner at the deployed API:

```bash
export RAKU_PROD_BASE_URL='http://rakura-awsne-zv0jkvgr3ezv-1129748567.ap-northeast-1.elb.amazonaws.com/v1'
export RAKU_PROD_BEARER_TOKEN="$(STACK=RakuRag-stg RAKU_SMOKE_USERNAME='...' RAKU_SMOKE_PASSWORD='...' bash scripts/aws/issue-smoke-token.sh)"
bash scripts/demo/chatbot_golden_scorecard.sh --ensure-policy
```

For the seeded demo KB, the smoke user must have `sales_demo` so ACL grants allow reads, and
`tenant_admin` or another source-policy role when using `--ensure-policy`.

Do not paste tokens into logs. The runner prints only scenario summaries and failure reasons, not raw
retrieved context or credentials.

## Current Staging Baseline

On 2026-06-30, staging with a temporary `tenant_admin + sales_demo` user produced:

- 17 total scenarios
- 7 passed / 10 failed
- refusal/security controls: 5/5 passed
- answerable rate: 0.529
- citation hit rate for answer scenarios: 0.750
- thin answer count: 2 by the summary threshold, with 8 answer scenarios failing their per-scenario
  completeness thresholds

This means the immediate quality problem is not authentication or the page. It is answer quality and
coverage: some expected documents are not retrieved, and many retrieved answers omit required facts.

## 2026-06-30 Fix Notes

The first remediation keeps ACL, approval/effective evidence, and chatbot source policy checks in
place. It changes only retrieval/generation quality:

- `HashingEmbeddingProvider.model_version` moved to `hashing-bow-v2` so CJK bigram tokenizer changes
  force re-embedding during migrate+seed instead of being skipped by diff-sync.
- Postgres lexical retrieval now lets the shared Japanese-aware scorer evaluate tenant/RLS-live
  chunks instead of pre-filtering with a CJK-weak `to_tsvector` predicate.
- `extractive-mvp` now expands procedure/troubleshooting/threshold questions over the best evidence
  document, which keeps required steps and countermeasures without mixing in nearby unrelated docs.

Local in-memory reproduction against `scripts/demo/demo_docs.json` passed all 12 answer scenarios
after the fix, with expected citations and required terms present. The live staging score must still
be measured after deploy because it verifies Postgres state, re-embedding, ACL grants, and policy
persistence together.

## Interpreting Results

- `answerable_rate` low with missing citations usually means retrieval/indexing/source policy setup
  needs attention.
- `answer too thin` means retrieval may be working, but the answer generator/prompt/profile is not
  producing enough usable content.
- `missing expected facts/terms` points to either retrieval miss or incomplete generation. Compare
  `/v1/search` or the answer trace before changing prompts.
- Refusal scenario failures are safety regressions. Fix policy/retrieval/grounding before improving
  style.

This scorecard is not Tier A. It belongs in staging/demo quality checks and release readiness because
it calls live HTTP APIs and may use live providers depending on the deployed profile.
