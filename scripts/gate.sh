#!/usr/bin/env bash
#
# raku-rag loop-engineering gate — the single "No" the loop checks.
# See docs/loop-engineering.md.
#
# Usage:
#   scripts/gate.sh [a|all|separation]
#     a           Tier A hard gates only (zero-tolerance). DEFAULT. ~milliseconds, stdlib.
#     all         Full test suite (Tier A + integration + unit).
#     separation  Invariant check (§5): block gate/test edits mixed with src/ edits.
#
# Exit codes: 0 = green, 1 = test failure (Tier A HALT), 3 = separation violation.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="src"

MODE="${1:-a}"

banner() { printf '\n======== %s ========\n' "$1"; }

run_tier_a() {
  banner "Tier A — hard gates (zero tolerance)"
  # 001 security hard gates (top-level dir = repo root so `tests.helpers` imports resolve).
  python3 -m unittest discover -s tests/security -t . -p 'test_*.py' -q
  # 002 manufacturing hard gates — included automatically once they exist.
  if [ -d tests/manufacturing ]; then
    if ls tests/manufacturing/test_*gate*.py tests/manufacturing/test_*.py >/dev/null 2>&1; then
      python3 -m unittest discover -s tests/manufacturing -t . -p 'test_*.py' -q
    fi
  fi
  echo "Tier A: GREEN"
}

run_all() {
  banner "Full suite (Tier A + integration + unit)"
  python3 -m unittest discover -s tests -t . -p 'test_*.py' -q
  echo "Full suite: GREEN"
}

# Invariant 5: verification/generation separation.
# A single change must not edit a protected gate/test file AND src/ together
# (that is the "edit the test to make it pass" reward-hack smell).
run_separation() {
  banner "Separation invariant (§5)"
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "not a git repo — separation guard inactive"; return 0
  fi
  # The protected set = the 001 security gates, the 6 named 002 hard-gate test files, the unit gate
  # tests, and this gate script itself. (Not every test_*.py — only the hard gates; new feature tests
  # are free to land with their impl.)
  local protected='^(tests/security/|tests/manufacturing/unit/|tests/manufacturing/test_(safety_gate|obsolete_draft_evidence|draft_only|acl_mapping|no_train|audit_coverage)\.py|scripts/gate\.sh$)'
  if ! git rev-parse HEAD >/dev/null 2>&1; then
    # No commits yet: nothing is "modified", invariant not yet enforceable.
    echo "no commits yet — separation guard inactive (becomes active after first commit)"; return 0
  fi
  # §5: flag only the reward-hack shape — MODIFYING an already-committed protected gate/test alongside
  # src/ (consistent with CI). Adding a NEW hard-gate test is allowed.
  local mod_protected src_changed
  mod_protected="$( { git diff --name-only --diff-filter=M HEAD; git diff --name-only --cached --diff-filter=M HEAD; } | sort -u | grep -E "$protected" || true)"
  src_changed="$( { git diff --name-only HEAD; git diff --name-only --cached; } | sort -u | grep -E '^src/' || true)"
  if [ -n "$mod_protected" ] && [ -n "$src_changed" ]; then
    echo "BLOCK: an existing hard-gate/test file was MODIFIED together with src/ — §5 separation violated." >&2
    echo "Gate changes must be a separate, independently-reviewed commit. Modified protected files:" >&2
    printf '%s\n' "$mod_protected" >&2
    return 3
  fi
  echo "separation OK"
}

case "$MODE" in
  a)          run_tier_a ;;
  all)        run_tier_a; run_all ;;
  separation) run_separation ;;
  *) echo "unknown mode: $MODE (use: a | all | separation)" >&2; exit 2 ;;
esac
