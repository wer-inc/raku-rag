#!/usr/bin/env bash
# Stage-guard regression assertions for the CDK app (issues 0088 + the prod profile guard work).
#
# These are the invariants that make a prod deploy safe REGARDLESS of which optional providers the
# dispatcher happened to select. They are asserted by synthesizing real templates, so they fail here
# instead of in front of a customer:
#
#   1. stage=prod ALWAYS carries RAKU_RUNTIME_PROFILE=production (issue 0088). Every production
#      backstop is keyed on that profile — output guardrail, LLM semantic danger classifier, Secrets
#      Manager secret store, embedding backstop — so a prod stack without it is silently unguarded.
#   2. stage=prod + any real generator (bedrock/openai/gemini) requires a Bedrock guardrail id+version.
#      The guardrail is ApplyGuardrail over the answer text, hence vendor-independent.
#   3. stage=prod refuses the hashing embedder (it degrades retrieval silently).
#   4. The known-good stg profile and the default (dev) synth keep working.
#
# Usage: bash infra/cdk/scripts/assert-stage-guards.sh   (run from anywhere; no AWS access needed)
set -euo pipefail

cd "$(dirname "$0")/.."

PROD_BASE=(--context stage=prod --context frontendHosting=aws-nextjs --context authMode=cognito
  --context domainName=guard-assert.example.com --context minimalSpec=false
  --context embeddingProvider=openai)
GUARDRAIL=(--context bedrockGuardrailId=aaaaaaaaaaaa --context bedrockGuardrailVersion=1)

pass=0
fail=0

report() { # report <ok|ng> <case>
  if [ "$1" = "ok" ]; then
    pass=$((pass + 1))
    printf 'PASS  %s\n' "$2"
  else
    fail=$((fail + 1))
    printf 'FAIL  %s\n' "$2"
  fi
}

synth() { npx cdk synth "$@" 2>/dev/null; }

# synth_must_pass <case> [--expect-production-profile] -- <context args...>
synth_must_pass() {
  local case_name="$1"; shift
  local expect_profile=0
  if [ "${1:-}" = "--expect-production-profile" ]; then expect_profile=1; shift; fi
  [ "${1:-}" = "--" ] && shift
  local template
  if ! template="$(synth "$@")"; then
    report ng "${case_name} (synth failed but should have succeeded)"
    return
  fi
  # Assert the VALUE, not just the key: CFN renders container env as `- Name: X` / `  Value: y`.
  if [ "${expect_profile}" = "1" ] &&
    ! printf '%s' "${template}" |
      grep -A1 "Name: RAKU_RUNTIME_PROFILE" | grep -q "Value: production"; then
    report ng "${case_name} (template has no RAKU_RUNTIME_PROFILE=production — issue 0088)"
    return
  fi
  report ok "${case_name}"
}

# synth_must_fail <case> -- <context args...>
synth_must_fail() {
  local case_name="$1"; shift
  [ "${1:-}" = "--" ] && shift
  if synth "$@" >/dev/null; then
    report ng "${case_name} (synth succeeded but should have been rejected)"
  else
    report ok "${case_name}"
  fi
}

echo "== stage guard assertions =="

synth_must_pass "prod + bedrock + guardrail carries the production profile" \
  --expect-production-profile -- "${PROD_BASE[@]}" --context answerLlm=bedrock "${GUARDRAIL[@]}"

synth_must_pass "prod + openai LLM + guardrail carries the production profile" \
  --expect-production-profile -- "${PROD_BASE[@]}" --context answerLlm=openai "${GUARDRAIL[@]}"

# The 0088 core regression: no real LLM, no visual providers — the old condition left this stack on
# the deterministic profile, which returns NO output guardrail.
synth_must_pass "prod + extractive still carries the production profile (0088)" \
  --expect-production-profile -- "${PROD_BASE[@]}" --context answerLlm=extractive

synth_must_fail "prod + openai LLM without a guardrail is rejected (0088)" \
  -- "${PROD_BASE[@]}" --context answerLlm=openai

synth_must_fail "prod + gemini without a guardrail is rejected (0088)" \
  -- "${PROD_BASE[@]}" --context answerLlm=gemini

synth_must_fail "prod + bedrock without a guardrail is rejected" \
  -- "${PROD_BASE[@]}" --context answerLlm=bedrock

synth_must_fail "prod with the hashing embedder is rejected" \
  -- --context stage=prod --context frontendHosting=aws-nextjs --context authMode=cognito \
  --context domainName=guard-assert.example.com --context minimalSpec=false \
  --context answerLlm=bedrock "${GUARDRAIL[@]}"

synth_must_pass "stg known-good profile still synthesizes" \
  --expect-production-profile -- --context stage=stg --context frontendHosting=aws-nextjs \
  --context authMode=cognito --context embeddingProvider=openai --context answerLlm=bedrock \
  --context structuredIngest=true --context ingestVision=bedrock --context httpsFront=cloudfront \
  "${GUARDRAIL[@]}"

synth_must_pass "default (dev) synth still works" --

# issue 0089: the migrate-seed task must default to schema-only on prod and demo-seeding elsewhere.
assert_run_seed() { # assert_run_seed <case> <expected 0|1> -- <context args...>
  local case_name="$1" expected="$2"; shift 2
  [ "${1:-}" = "--" ] && shift
  local template actual
  if ! template="$(synth "$@")"; then
    report ng "${case_name} (synth failed)"
    return
  fi
  actual="$(printf '%s' "${template}" | grep -A1 "Name: RUN_SEED" | grep "Value:" | head -1 |
    tr -d ' "' | cut -d: -f2)"
  if [ "${actual}" = "${expected}" ]; then
    report ok "${case_name}"
  else
    report ng "${case_name} (RUN_SEED='${actual}', expected '${expected}' — issue 0089)"
  fi
}

assert_run_seed "prod migrate-seed task defaults to RUN_SEED=0 (0089)" 0 \
  -- "${PROD_BASE[@]}" --context answerLlm=bedrock "${GUARDRAIL[@]}"

assert_run_seed "sales migrate-seed task keeps RUN_SEED=1 (0089)" 1 \
  -- --context stage=sales --context frontendHosting=aws-nextjs

echo "== ${pass} passed, ${fail} failed =="
[ "${fail}" = "0" ]
