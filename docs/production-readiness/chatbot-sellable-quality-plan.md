# ChatBot Sellable Quality Improvement Plan

Status: Draft for implementation planning
Date: 2026-06-30
Owner: production-readiness / chatbot quality

Implementation note (2026-07-01): Phase 1 now includes contextual quick reply checks as scored
follow-up turns and a stack wrapper for staging scorecard runs. The deterministic ChatBot composer
has also been strengthened as the grounded fallback before the later `manufacturing-synthesis-v1`
profile: answerable turns render `結論`, `対象・前提`, `手順`, `数値基準`, `注意点`,
`判断に迷う条件`, and `根拠` without weakening source policy, ACL, or approved-evidence gates.

Implementation note (2026-07-01): Follow-up quick replies now avoid the ambiguous `details` button.
Displayed actions are limited to business transformations (`手順だけ見る`, `判断基準を表にする`,
`注意点を確認`) plus evidence confirmation, and follow-up turns reformat the previous grounded answer
instead of launching another RAG search.

## Purpose

The current staging ChatBot scorecard proves the product no longer fails basic grounded-answer and
refusal checks: `17/17 PASS` on the deterministic `hashing` + `extractive` profile. That is a good
regression floor, but it is not yet a sellable enterprise assistant experience.

This plan defines the next quality step: move from "correct enough for smoke" to "credible in a
customer demo and paid pilot" without weakening ACL, tenant isolation, approved-evidence rules, or
source exposure policies.

## Market Pattern

The strongest public enterprise RAG implementations do not rely on prompt tuning alone. They invest
in retrieval, ranking, metadata, permission-aware grounding, evaluation, and response composition.

- Microsoft Azure AI Search documents hybrid search as vector + full-text retrieval with Reciprocal
  Rank Fusion, and semantic ranker as a second-stage reranker over initial results.
- AWS Bedrock Knowledge Bases exposes metadata filters, query customization, prompt templates, and
  reranking for improving retrieved relevance.
- Anthropic's Contextual Retrieval adds document-level context to chunks and combines contextual
  embeddings, contextual BM25, and reranking to reduce retrieval failures.
- OpenAI File Search uses both vector and keyword retrieval over parsed/chunked files.

These patterns point to the same product lesson: first make the evidence selection excellent, then
make the answer useful.

References:

- Azure hybrid search: https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview
- Azure semantic ranker: https://learn.microsoft.com/en-us/azure/search/semantic-search-overview
- AWS Knowledge Bases query configuration: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-config.html
- AWS Bedrock reranking: https://docs.aws.amazon.com/bedrock/latest/userguide/rerank.html
- Anthropic Contextual Retrieval: https://www.anthropic.com/engineering/contextual-retrieval
- OpenAI File Search: https://developers.openai.com/api/docs/assistants/tools/file-search

## Current Baseline

What is already acceptable:

- `/chatbot` can use an enabled `collection_id` reference scope.
- Chat source exposure policy remains collection-wide and deny-by-default.
- Staging golden scenarios pass: `17/17`.
- Refusal/security controls pass: draft, pending-review, obsolete, out-of-scope, prompt injection.
- Demo seed now restores a clean 18-document `manuals` corpus.

What is still not sellable:

- The deterministic extractive answer style is too mechanical.
- The scenario set is small and demo-oriented.
- Retrieval is still not explainable enough when it fails.
- There is no second-stage semantic reranking.
- The answer format is not optimized for manufacturing workflows.
- The demo/staging profile is intentionally cheap and deterministic, not customer-grade.

## Principles

1. Safety stays fixed.
   ACL pre-filtering, tenant isolation, tombstone behavior, approved/effective evidence gates,
   draft/obsolete handling, and prompt-injection refusal are not tuning knobs.

2. Separate smoke quality from sellable quality.
   Keep `hashing` + `extractive` as the fast deterministic staging smoke profile. Add a separate
   demo-quality profile for paid-pilot readiness.

3. Retrieval before generation.
   Thin answers are often a retrieval/ranking/context problem. Improve candidate selection before
   increasing answer freedom.

4. Measure every improvement.
   Each phase needs an eval slice that can fail. Do not accept manual eyeballing as the release gate.

5. No opaque magic.
   A customer-facing answer must show citations and explain when evidence is insufficient. Internal
   debugging must show query plan, filters, candidate docs, rerank scores, and rejection reasons
   without logging raw private context.

## Target Experience

For manufacturing users, the answer should be structured and operational:

1. Direct answer
2. Conditions / numeric thresholds
3. Procedure or action steps
4. Safety or quality cautions
5. Evidence and document version
6. Unknowns or escalation path

Example target shape:

```text
結論: M8端子台は25 N·m、M16接地端子は95 N·mです。

条件:
- 対象: E-152標準モータ端子台
- 適用版: approved/effective のトルク標準

手順:
1. 校正済みトルクレンチを選定する。
2. 指定トルクで締結し、マーキングする。
3. ダブルチェック欄に記録する。

注意:
- 異音、焼損痕、ねじ山損傷がある場合は締結せず保全へエスカレーションする。

根拠:
- eq-motor-m8-torque
```

## Target Architecture

The customer-grade path should become:

```text
user question
  -> query planner
  -> metadata/entity extraction
  -> hybrid retrieval
       vector candidates
       lexical/BM25 candidates
       metadata-filtered exact candidates
  -> reciprocal rank fusion
  -> semantic reranker
  -> citation/safety filter
  -> manufacturing answer composer
  -> grounded answer or handoff
```

Profiles:

- `stg-smoke`: hashing embedding, extractive answer, no paid calls, deterministic.
- `demo-quality`: multilingual production embedding, reranker, structured answer composer, citations
  required.
- `production-quality`: same as demo-quality plus tenant customer corpus, observability, cost budget,
  and human-approved rollout.

Live provider activation, paid reindexing, or production promotion requires explicit human approval.

## Phased Plan

### Phase 0: Freeze The Current Floor

Goal: preserve the current passing behavior while building the stronger path.

Deliverables:

- Keep `scripts/demo/chatbot_golden_scorecard.sh` at `17/17 PASS` for `stg-smoke`.
- Add profile labels to scorecard output: embedding provider, reranker, answer profile, dataset
  version.
- Keep issue 0050 as resolved baseline evidence.

Acceptance:

- `scripts/gate.sh all`
- `scripts/gate.sh separation`
- Staging scorecard remains `17/17`.

### Phase 1: Expand Evaluation From 17 To 120+ Scenarios

Goal: make the quality bar representative enough to guide product decisions.

Scenario slices:

- Grounded lookup: 30
- Procedures: 30
- Troubleshooting: 25
- Safety refusal: 20
- Ambiguous questions / clarification: 15
- Draft, obsolete, conflicting, and deleted evidence: 20
- Prompt injection / source poisoning: 10

Runner improvements:

- [x] Separate retrieval failures from answer composition failures.
- [x] Record expected document IDs, acceptable sibling document IDs, required terms, forbidden terms,
  citation count, section presence, and latency.
- [x] Persist run summary with dataset/profile version.
- [x] Add a "customer-demo readiness" summary separate from CI hard gates.
- [x] Score contextual quick replies as separate follow-up turns.
- [x] Add a staging stack wrapper for one-command scorecard execution after deploy.
- [ ] Expand from the 37-scenario seed set to 120+ scenarios with SME review.
- [ ] Add retrieval-only diagnostics (`recall@10`, MRR, candidate rejection reasons).

Acceptance:

- [x] Deterministic local run supports the expanded dataset.
- [ ] Staging `stg-smoke` passes all safety/refusal scenarios and maintains current 17-scenario subset.
- [x] New larger dataset can fail without blocking Tier A until thresholds are approved.
- [ ] Quick reply follow-ups pass the representative smoke/v2 checks on staging.

### Phase 2: Contextual Chunking And Metadata Enrichment

Goal: make each chunk retrievable as a manufacturing unit, not just as isolated text.

Add chunk context:

- `document_title`
- `document_kind`
- `section_path`
- `equipment_id`
- `line_id` / `factory_id` where available
- `procedure_step`
- `approval_status`
- `effective_date`
- `superseded_by`
- `safety_category`
- `source_sync_freshness`

Implementation notes:

- Prefer deterministic enrichment from document metadata and parser structure.
- For LLM-generated contextual summaries, store as draft/index metadata and gate behind profile and
  no-train/provider policy.
- Reindex only through existing ingestion/reindex paths so tombstone and registry invariants remain
  intact.

Acceptance:

- Retrieval eval shows higher exact document hit rate on equipment/procedure/quality scenarios.
- Existing ACL/tombstone/tenant tests pass.
- Citation payloads still do not expose raw hidden context beyond allowed citation text.

### Phase 3: Query Planner And Hybrid Retrieval

Goal: make the system understand what kind of evidence it should look for.

Planner output:

- intent: lookup, procedure, troubleshooting, safety refusal, comparison, clarification
- entities: equipment IDs, alarm codes, document IDs, process names, standards, numeric thresholds
- filters: collection, document kind, approval state, effective-only, optional source/date bounds
- query rewrites: Japanese lexical terms, synonyms, exact identifiers

Retrieval changes:

- Retrieve broadly from vector and lexical candidates.
- Add exact identifier boosts for equipment IDs, document IDs, alarm codes, and standard IDs.
- Fuse vector and lexical candidates with RRF or equivalent deterministic fusion.
- Preserve ACL/tenant/tombstone filtering before any candidate can reach answers or citations.

Acceptance:

- Retrieval-only eval reports `recall@10`, `precision@10`, `MRR`, and exact-ID hit rate.
- Current 17 stg scenarios continue to pass.
- Safety refusal scenarios cannot be converted into answerable scenarios by query rewriting.

### Phase 4: Reranker

Goal: improve top evidence quality after broad retrieval.

Options:

- Bedrock rerank profile for AWS-hosted deployments.
- Cohere Rerank profile if provider policy allows it.
- Local/open-source reranker for offline or restricted customer environments.

Rollout:

- Add reranker interface and provider-policy controls.
- Retrieve top 30-50 candidates, rerank to top 5-8.
- Persist rerank score and reason metadata for diagnostics.
- Fail closed or fall back by profile; do not silently bypass provider-policy restrictions.

Acceptance:

- Reranker A/B on expanded eval improves MRR and required-citation hit rate.
- p95 latency stays within the demo-quality budget.
- Provider policy and no-train gates are covered by tests.

### Phase 5: Manufacturing Answer Composer

Goal: move from extractive snippets to a useful operational response while staying grounded.

Composer requirements:

- Fixed section schema: answer, conditions, steps, cautions, evidence, escalation.
- Every factual claim must map to cited evidence.
- High-risk procedures require approved/effective primary evidence.
- Conflicting evidence must produce warning or handoff.
- Missing key evidence must ask for clarification or hand off.

Implementation:

- Keep extractive composer as deterministic fallback.
- Use the current deterministic fallback to render operational sections:
  `結論`, `対象・前提`, `手順`, `数値基準`, `注意点`, `判断に迷う条件`, `根拠`.
- Add `manufacturing-synthesis-v1` profile for demo-quality.
- Generate structured answer JSON first, then render for UI.
- Add answer-template version to response metadata.

Acceptance:

- Expanded answer eval checks section presence and required facts.
- No unsupported facts in sampled SME review.
- Existing refusal and prompt-injection checks stay green.

### Phase 6: Product UI And Operator Feedback

Goal: make quality visible and improvable during demos and pilots.

UI changes:

- Show concise citation cards with document status, effective date, and section.
- Show "根拠不足" reasons that explain what evidence is missing.
- Add thumbs up/down with reason categories: wrong source, missing step, too vague, unsafe, outdated.
- Add admin diagnostics view for query plan and candidate/rerank summary without raw sensitive context.

Acceptance:

- Playwright smoke covers happy path, refusal path, and feedback submission.
- Feedback creates an audit-safe record tied to correlation ID and scenario/user.

### Phase 7: Paid Pilot Readiness

Goal: make the system defensible for a real customer corpus.

Requirements:

- Customer-specific eval set approved by SME.
- Data freshness and connector sync status included in answer diagnostics.
- Cost and latency dashboards by profile.
- Rollback plan from `production-quality` to `stg-smoke`/extractive fallback.
- Security review for provider policy, no-train, and logging.

Acceptance:

- Customer pilot scorecard meets approved thresholds.
- Production deployment is explicitly approved.
- Rollback tested.

## Quality Gates

Minimum target for demo-quality:

- Safety/refusal: 100 percent pass
- Contextual quick replies: 100 percent pass for the representative smoke set
- Required citation hit rate: 98 percent or better
- Required term/completeness pass rate: 90 percent or better
- Retrieval recall@10: 95 percent or better on approved answerable questions
- MRR: no regression from baseline
- p95 latency: under 8 seconds for synthesis profile, under 2 seconds for smoke profile
- Unsupported claim rate in sampled review: 0 critical issues

These are starting thresholds. They should be tightened after the expanded dataset is stable.

## Risks

- Reranker/provider cost can surprise demos. Mitigation: budget profile and cached evaluation runs.
- Better generation can introduce unsupported claims. Mitigation: structured composer, citation
  validation, sampled SME review.
- Metadata enrichment can leak sensitive labels if shown directly. Mitigation: internal diagnostics
  only unless fields are explicitly approved for citation display.
- Expanded eval can become stale. Mitigation: dataset versioning and SME review cadence.
- Provider-specific behavior can hide regressions. Mitigation: keep deterministic smoke profile and
  profile-specific baselines.

## Scope Exclusions

- Weakening ACL, tenant isolation, tombstone, source exposure, or approved-evidence safety gates.
- Making browser code the security boundary.
- Logging raw retrieved context, secrets, tokens, PII, or internal auth headers.
- Paid provider activation, billed reindexing, or production promotion without explicit approval.
- Treating Playwright UI smoke as answer-quality proof.

## Immediate Next Tasks

1. Create `chatbot_quality_v2` expanded scenario dataset and runner schema.
2. Expand `chatbot_quality_v2` from 37 seeded scenarios to 120+ SME-reviewed scenarios.
3. Add retrieval diagnostics to the scorecard output.
4. Add contextual chunk metadata for the curated demo corpus.
5. Implement query planner for manufacturing entities and intents.
6. Add reranker interface behind provider policy.
7. Add `manufacturing-synthesis-v1` structured answer composer profile.
8. Run A/B scorecards: `stg-smoke` vs `demo-quality`.
