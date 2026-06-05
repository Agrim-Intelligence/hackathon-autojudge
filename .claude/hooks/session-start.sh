#!/usr/bin/env bash
# Agrim SDLC — SessionStart hook
# Injects the getting-started bootstrap into every new Claude Code session
# so skills auto-trigger without requiring slash commands.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
GETTING_STARTED="${SCRIPT_DIR}/../skills/getting-started/SKILL.md"

skill_content=$(cat "${GETTING_STARTED}" 2>&1 || echo "Error reading getting-started skill")

# --- install self-check -------------------------------------------------------
# Catch silent degradation in host repos (hook fired but harness mis-wired).
# Never blocks: only prepends a loud warning line to the injected context.
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-${REPO_ROOT}}"
warnings=""
rules="${PROJECT_DIR}/.claude/project-rules.md"
settings="${PROJECT_DIR}/.claude/settings.json"
if [ ! -f "$rules" ]; then
    warnings="${warnings} project-rules.md missing (copy project-rules.template.md → project-rules.md);"
elif grep -qE '(^|[[:space:]])<[a-z][^>]*>([[:space:]]|$)' "$rules" 2>/dev/null; then
    warnings="${warnings} project-rules.md still has <placeholders> — fill it in;"
fi
if [ -f "$settings" ] && ! grep -q 'skillOverrides' "$settings" 2>/dev/null; then
    warnings="${warnings} settings.json missing skillOverrides — platform built-ins may shadow Agrim skills;"
fi
if [ -n "$warnings" ]; then
    skill_content="⚠ Agrim harness misconfigured:${warnings}"$'\n\n'"${skill_content}"
fi

# JSON-escape: each substitution is a single pass (fast, no loops)
escape_for_json() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

escaped=$(escape_for_json "$skill_content")

session_context="<EXTREMELY_IMPORTANT>\nYou have Agrim skills.\n\n**Below is your getting-started guide. Read it now, before doing anything else.**\n\n${escaped}\n</EXTREMELY_IMPORTANT>"

# Claude Code expects hookSpecificOutput.additionalContext
# Uses printf instead of heredoc — bash 5.3+ heredoc hang workaround
printf '{\n  "hookSpecificOutput": {\n    "hookEventName": "SessionStart",\n    "additionalContext": "%s"\n  }\n}\n' "$session_context"

exit 0
