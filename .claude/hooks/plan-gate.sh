#!/usr/bin/env bash
# Agrim SDLC — PreToolUse gate (Edit|Write|MultiEdit|NotebookEdit)
# Denies edits to SOURCE files when no current plan exists.
#
# Two safety principles, non-negotiable:
#   1. FAIL-OPEN. Any error, missing dep, or unparseable input → exit 0 (allow).
#      A broken gate must never brick a repo; it degrades to advisory.
#   2. DELIBERATE OVERRIDE. `.claude/.allow-direct-edits` is the mechanical
#      form of "user said go ahead" — an explicit act, not an assumption.
#
# Decision order: artifact/meta path → override sentinel → non-source file →
#                 recent plan exists → otherwise DENY.

set -uo pipefail

# --- fail-open helpers --------------------------------------------------------
allow() { exit 0; }   # no JSON = default permission flow (does not force-allow deny rules)

deny() {
  # $1 = reason. Emit PreToolUse deny via stdout JSON (exit 0).
  local reason="$1"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":%s}}\n' \
    "$(json_string "$reason")"
  exit 0
}

# Minimal JSON string encoder (so a reason with quotes/newlines stays valid).
json_string() {
  local s="$1"
  s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; s="${s//$'\n'/\\n}"; s="${s//$'\t'/\\t}"
  printf '"%s"' "$s"
}

# jq is required to parse stdin reliably. Absent → fail-open.
command -v jq >/dev/null 2>&1 || allow

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"

# --- read input ---------------------------------------------------------------
input="$(cat)" || allow
file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)" || allow
[ -n "$file_path" ] || allow

# --- config (defaults + optional override file) -------------------------------
# Machine-readable knobs live in .claude/sdlc-gates.conf (shell KEY=val).
# project-rules.md documents them for humans.
PLAN_FRESHNESS_HOURS=24
SOURCE_EXTS="js jsx ts tsx py go rb rs java kt swift c cc cpp h hpp cs php scala ex exs"
# shellcheck disable=SC1091
[ -f "$PROJECT_DIR/.claude/sdlc-gates.conf" ] && . "$PROJECT_DIR/.claude/sdlc-gates.conf" 2>/dev/null

# --- normalize path -----------------------------------------------------------
rel="${file_path#"$PROJECT_DIR"/}"

# 1. Always allow artifact / meta writes (never block writing the plan itself).
case "$rel" in
  docs/*|.claude/*|*/docs/*) allow ;;
esac
case "$rel" in
  *.md|*.markdown|*.txt|*.json|*.yaml|*.yml|*.toml|*.ini|*.cfg|*.lock) allow ;;
esac

# 2. Deliberate override sentinel.
[ -f "$PROJECT_DIR/.claude/.allow-direct-edits" ] && allow

# 3. Only gate SOURCE files. Anything else → allow.
ext="${rel##*.}"
is_source=0
for e in $SOURCE_EXTS; do [ "$ext" = "$e" ] && is_source=1 && break; done
[ "$is_source" -eq 1 ] || allow

# 4. Allow if a recent plan exists.
if [ -d "$PROJECT_DIR/docs/plans" ]; then
  recent="$(find "$PROJECT_DIR/docs/plans" -maxdepth 1 -name '*.md' -mmin "-$((PLAN_FRESHNESS_HOURS*60))" 2>/dev/null | head -n1)"
  [ -n "$recent" ] && allow
fi

# 5. No plan → deny with an actionable reason.
deny "No current plan for this change. Run the plan-feature skill to produce docs/plans/<slug>.md before editing source ($rel). If this is a trivial fix or the engineer has explicitly approved direct edits, run: touch .claude/.allow-direct-edits"
