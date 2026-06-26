#!/usr/bin/env bash
#
# PostToolUse hook — auto-run the Tier-A verification gate after a Python edit.
#
# Wired from .claude/settings.json (PostToolUse: Edit|Write|MultiEdit).
# Enforces docs/loop-engineering.md §5 (verification/generation separation):
# the harness, not the model, checks the "No" after every source change.
#
# Behaviour:
#   - Reads the hook payload (JSON) on stdin, extracts tool_input.file_path.
#   - Only fires for *.py files under src/ or tests/ (skips md/ts/json/etc).
#   - Runs `scripts/gate.sh a` (Tier A, stdlib, fast).
#   - Green  -> exit 0, silent.
#   - Red    -> print the failure on stderr, exit 2 (fed back to Claude as a block).
#   - Missing gate / python / unparsable input -> exit 0 (never break the harness).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Extract the edited file path from the hook JSON on stdin. Fail open on any error.
# NB: use `-c` (not `python3 - <<HEREDOC`) so the JSON on stdin reaches sys.stdin
# instead of being shadowed by the heredoc program text.
file_path="$(python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print(""); sys.exit(0)
ti = data.get("tool_input") or {}
print(ti.get("file_path") or "")
' 2>/dev/null || true)"

# Only gate Python sources under src/ or tests/.
case "$file_path" in
  *.py) ;;
  *) exit 0 ;;
esac
case "$file_path" in
  *"/src/"*|*"/tests/"*|"$ROOT/src/"*|"$ROOT/tests/"*) ;;
  src/*|tests/*) ;;
  *) exit 0 ;;
esac

# Need the gate and python to do anything useful.
[ -x "$ROOT/scripts/gate.sh" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

out="$("$ROOT/scripts/gate.sh" a 2>&1)"
status=$?

if [ "$status" -eq 0 ]; then
  exit 0
fi

# Tier A is red — surface it to Claude as a blocking finding.
{
  echo "Tier-A gate FAILED after editing ${file_path}."
  echo "Fix before continuing (docs/loop-engineering.md §1, §5). Output:"
  echo "----"
  echo "$out" | tail -n 40
} >&2
exit 2
