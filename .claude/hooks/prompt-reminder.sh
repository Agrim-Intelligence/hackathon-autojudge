#!/usr/bin/env bash
# Agrim SDLC — UserPromptSubmit reminder
# Re-injects a COMPACT loop reminder on every prompt so guidance salience
# does not decay between SessionStart and deep-in-task drift.
# Deliberately ≤5 lines to bound per-turn token cost. Fail-open.

set -uo pipefail

reminder="Agrim loop check (before acting): 1) A skill almost certainly applies — invoke it first, even before clarifying questions. 2) Non-trivial code needs a plan (docs/plans/<slug>.md) — the plan-gate will block source edits without one. 3) Artifacts go to DISK (context.md, plan, test_report.md), not just chat — a chat summary does not count as done. 4) Hard stops (destructive ops, auth/PII, secrets, cross-team contracts) → hand back."

# Emit as additionalContext. Pure printf; no jq dependency.
esc() { local s="$1"; s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; printf '%s' "$s"; }
printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"%s"}}\n' "$(esc "$reminder")"
exit 0
