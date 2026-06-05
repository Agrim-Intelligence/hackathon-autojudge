#!/usr/bin/env bash
# Agrim SDLC — Stop gate
# Refuses to let the agent stop when SOURCE changed without the loop's artifacts.
#   - source changed but no recent plan        → block
#   - source changed but no recent test_report → block (strict) / note (warn)
#
# Same two principles as plan-gate.sh: FAIL-OPEN and DELIBERATE OVERRIDE.
# Extra guard: respect stop_hook_active so we never loop forever.

set -uo pipefail

allow() { exit 0; }

block() {
  # Force the agent to continue. stdout JSON, exit 0.
  local reason="$1"
  printf '{"decision":"block","reason":%s}\n' "$(json_string "$reason")"
  exit 0
}

json_string() {
  local s="$1"
  s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; s="${s//$'\n'/\\n}"; s="${s//$'\t'/\\t}"
  printf '"%s"' "$s"
}

command -v jq >/dev/null 2>&1 || allow
command -v git >/dev/null 2>&1 || allow

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"

input="$(cat)" || allow
# Loop guard: if we already blocked this turn, let the agent stop.
[ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)" = "true" ] && allow

# Deliberate override short-circuits the whole gate.
[ -f "$PROJECT_DIR/.claude/.allow-direct-edits" ] && allow

# Not a git repo (or git errors) → fail-open.
git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || allow

# --- config -------------------------------------------------------------------
PLAN_FRESHNESS_HOURS=24
TDD_GATE="warn"   # off | warn | strict
SOURCE_EXTS="js jsx ts tsx py go rb rs java kt swift c cc cpp h hpp cs php scala ex exs"
# shellcheck disable=SC1091
[ -f "$PROJECT_DIR/.claude/sdlc-gates.conf" ] && . "$PROJECT_DIR/.claude/sdlc-gates.conf" 2>/dev/null

[ "$TDD_GATE" = "off" ] && tdd_off=1 || tdd_off=0

# --- did source change? -------------------------------------------------------
# Use diff/ls-files (not status --porcelain + awk $NF) so paths with spaces stay intact.
changed="$( {
  git -C "$PROJECT_DIR" diff --name-only 2>/dev/null
  git -C "$PROJECT_DIR" diff --cached --name-only 2>/dev/null
  git -C "$PROJECT_DIR" ls-files --others --exclude-standard 2>/dev/null
} | sort -u )" || allow
source_changed=0
test_changed=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  case "$f" in docs/*|.claude/*) continue ;; esac
  ext="${f##*.}"
  for e in $SOURCE_EXTS; do
    if [ "$ext" = "$e" ]; then
      source_changed=1
      case "$f" in *test*|*spec*|*Test*|*Spec*|*_test.*|*.test.*|*.spec.*) test_changed=1 ;; esac
    fi
  done
done <<< "$changed"

[ "$source_changed" -eq 1 ] || allow

# --- gate 1: plan must exist --------------------------------------------------
plan_recent=""
[ -d "$PROJECT_DIR/docs/plans" ] && plan_recent="$(find "$PROJECT_DIR/docs/plans" -maxdepth 1 -name '*.md' -mmin "-$((PLAN_FRESHNESS_HOURS*60))" 2>/dev/null | head -n1)"
if [ -z "$plan_recent" ]; then
  block "Source files changed but there is no current plan (docs/plans/<slug>.md). Run the plan-feature skill, or set the override sentinel if the engineer approved direct work. Do not stop yet."
fi

# --- gate 2: tests (warn/strict) ----------------------------------------------
if [ "$tdd_off" -eq 0 ]; then
  report=""
  [ -f "$PROJECT_DIR/test_report.md" ] && report="$(find "$PROJECT_DIR" -maxdepth 1 -name 'test_report.md' -mmin "-$((PLAN_FRESHNESS_HOURS*60))" 2>/dev/null)"
  if [ -z "$report" ] && [ "$test_changed" -eq 0 ]; then
    if [ "$TDD_GATE" = "strict" ]; then
      block "Source changed but no test_report.md and no test files touched. Run the test-change skill (RED → GREEN) and write test_report.md before stopping."
    else
      # warn: surface but allow stop.
      printf '%s\n' "Agrim note: source changed without a test_report.md — consider running test-change." >&2
      allow
    fi
  fi
fi

allow
