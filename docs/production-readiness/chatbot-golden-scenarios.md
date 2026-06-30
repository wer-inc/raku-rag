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
- The v2 readiness dataset also checks expected/acceptable citation IDs, required answer sections,
  ambiguity/clarification behavior, profile labels, and failure attribution.

## Run Locally

Start the local demo stack, then run:

```bash
bash scripts/demo/chatbot_golden_scorecard.sh --ensure-policy
```

The runner mints a local dev token through `WEB_BASE/api/dev-token` when no token is supplied.

## Run The Expanded Readiness Dataset

The default scorecard remains the 17-scenario staging smoke floor. The first customer-demo readiness
dataset is separate and intentionally stricter:

```bash
bash scripts/demo/chatbot_golden_scorecard.sh \
  --dataset scripts/demo/chatbot_quality_v2_scenarios.json \
  --profile-name demo-quality-target \
  --embedding-provider hashing \
  --answer-profile extractive-mvp \
  --reranker none \
  --output /tmp/chatbot-quality-v2-result.json \
  --ensure-policy
```

As of phase 1, `chatbot_quality_v2` has 37 scenarios across grounded lookup, high-risk procedures,
troubleshooting, safety refusal, ambiguity/clarification, and prompt-injection controls. It is not a
Tier A hard gate yet; it is the measurement surface for making thin answers visible before tightening
release thresholds.

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

On 2026-06-30, staging deploy
[`28436589691`](https://github.com/wer-inc/raku-rag/actions/runs/28436589691) at head `8874795`
with a temporary `tenant_admin + sales_demo` user produced:

- 17 total scenarios
- 17 passed / 0 failed
- refusal/security controls: 5/5 passed
- answerable rate: 0.706
- citation hit rate for answer scenarios: 1.000
- thin answer count: 1 by the summary threshold, with all per-scenario citation, required-term, and
  minimum-length checks passing
- seeded `manuals` inventory visible through `/v1/manufacturing/documents`: 18 live documents

This is the current minimum staging quality bar for the deterministic `hashing` + `extractive`
profile. Regressions should be treated as either retrieval/indexing/source-policy failures or
extractive completeness failures before changing safety rules.

## Phase 1 Readiness Harness

The runner now supports `chatbot-golden-scenarios/v2` datasets. New fields are additive so the smoke
dataset remains valid:

- `dataset_id`, `dataset_version`, `evaluation_stage`, and `default_profile` label a run.
- `expected_document_ids` and `acceptable_document_ids` distinguish canonical from acceptable
  citations.
- `required_sections` checks answer composition, for example `結論`, `手順`, `注意`, `根拠`,
  `原因`, or `対策`.
- `expected_behavior=clarification` catches ambiguous questions that should ask a follow-up instead
  of guessing.
- JSON output includes readiness thresholds, profile metadata, failure kinds, refusal pass rate,
  clarification pass rate, expected citation hit rate, and completeness rate without storing raw
  retrieved context.

## 2026-06-30 Fix Notes

The first remediation keeps ACL, approval/effective evidence, and chatbot source policy checks in
place. It changes only retrieval/generation quality:

- `HashingEmbeddingProvider.model_version` moved to `hashing-bow-v2` so CJK bigram tokenizer changes
  force re-embedding during migrate+seed instead of being skipped by diff-sync.
- Postgres lexical retrieval now lets the shared Japanese-aware scorer evaluate tenant/RLS-live
  chunks instead of pre-filtering with a CJK-weak `to_tsvector` predicate.
- `extractive-mvp` now expands procedure/troubleshooting/threshold questions over the best evidence
  document, which keeps required steps and countermeasures without mixing in nearby unrelated docs.
- Demo seeding now grants demo ACL first, purges every live document in the seeded collection through
  the existing deletion service, then re-ingests the curated corpus. This prevents stale URL-sync/debug
  documents from polluting retrieval.
- `ProductionSystem.ingest_document` now re-indexes a duplicate upload when the registry document is
  tombstoned, so same-checksum demo re-seeds restore deleted documents instead of returning the old
  succeeded ingestion run.

Local in-memory reproduction against `scripts/demo/demo_docs.json` passed all 12 answer scenarios
after the fix, with expected citations and required terms present. The live staging score above
verifies Postgres state, re-embedding, ACL grants, source policy persistence, and seed cleanup
together.

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
