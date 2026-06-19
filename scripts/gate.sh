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
  local protected='^(tests/security/|tests/manufacturing/test_.*gate.*|scripts/gate\.sh$)'
  local changed
  if git rev-parse HEAD >/dev/null 2>&1; then
    changed="$( { git diff --name-only HEAD; git diff --name-only --cached; } | sort -u )"
  else
    # No commits yet: nothing is "modified", invariant not yet enforceable.
    echo "no commits yet — separation guard inactive (becomes active after first commit)"; return 0
  fi
  local gate_files src_files
  gate_files="$(printf '%s\n' "$changed" | grep -E "$protected" || true)"
  src_files="$(printf '%s\n' "$changed" | grep -E '^src/' || true)"
  if [ -n "$gate_files" ] && [ -n "$src_files" ]; then
    echo "BLOCK: gate/test files changed together with src/ — separation violated." >&2
    echo "Gate changes must be a separate, human-reviewed commit. Touched gate files:" >&2
    printf '%s\n' "$gate_files" >&2
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
