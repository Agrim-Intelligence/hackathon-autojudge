---
name: subagent-driven-development
description: >
  Use WHEN executing a multi-task plan by dispatching subagents — run the plan, execute tasks autonomously,
  dispatch agents, subagent-driven, parallel tasks with review gates.
  Triggers on: "run the plan", "execute the plan", "dispatch agents", "subagent", "autonomous execution".
when_to_use: Use after a plan is approved and a worktree is set up to execute tasks one-at-a-time with automated review gates.
when_not_to_use: Single-task plan or single slice — use implement-slice directly. No worktree exists — set one up first.
inputs: [docs/plans/<slug>.md, worktree path from using-git-worktrees]
read_first: [docs/plans/<slug>.md (all tasks), .claude/agents/implementer.md, .claude/agents/code-reviewer.md]
outputs: Per-task: implementation_notes.md fragment + review.md fragment. Final: all tasks checked off.
hard_stops: [Critical review finding → surface to human before any further tasks, autonomy ceiling reached → human checkpoint]
---

# subagent-driven-development

> One subagent per task. Two-stage review between tasks. Human checkpoint every N tasks.

## Goal
Drive a multi-task plan to completion by dispatching a fresh `implementer` subagent per task, reviewing each result before proceeding, and surfacing to the human at configured checkpoints.

**Why fresh subagents:** Each implementer gets only the task it needs — no accumulated context from prior tasks. This prevents drift, keeps each agent focused, and makes failures isolated.

## Autonomy Ceiling

Default: surface to the human **every 3 tasks** and after any Critical review finding.

Override in `project-rules.md`:
```
## autonomy ceiling
tasks-between-checkpoints: 5
```

## Orchestration Loop

For each task in the plan (in order):

**Step 1 — Announce:**
> "Dispatching implementer for Task N: <task name>"

**Step 2 — Dispatch implementer subagent** (see `.claude/agents/implementer.md`):
- Fill `{TASK}` with the task block from the plan
- Fill `{WORKTREE_PATH}` with the path from `using-git-worktrees`
- Fill `{PROJECT_RULES}` with contents of `project-rules.md`
- Await result (synchronous — do not proceed until subagent returns)

**Step 3 — Capture diff from the worktree, then dispatch code-reviewer:**

Before dispatching, run this command to capture the diff. The worktree path must be explicit — never run git diff from the current session directory or you will diff the wrong tree:
```bash
TASK_DIFF=$(git -C "{WORKTREE_PATH}" diff origin/main...HEAD)
# If that is empty (implementer committed to a fresh branch):
TASK_DIFF=$(git -C "{WORKTREE_PATH}" diff HEAD~1)
```

Then dispatch code-reviewer (see `.claude/agents/code-reviewer.md`):
- Fill `{DESCRIPTION}` from implementer's summary
- Fill `{PLAN_SLICE}` from the task block
- Fill `{DIFF}` with the captured diff text above — never a git command, always the actual diff
- Await result

**Step 4 — Act on review findings:**
- **Critical:** STOP. Surface finding to human. Do not proceed until human approves fix.
- **Important:** Surface to human. Ask: "Fix now before proceeding, or log for later?" Await answer.
- **Minor:** Log in the task's review fragment. Continue.

**Step 5 — Mark task complete:** Check off `- [ ]` in the plan file → `- [x]`.

**Step 6 — Checkpoint (if N tasks complete or human requests):**
> "Checkpoint: Tasks 1–N complete. N+1 tasks remaining. Continue?"
> Summarise: what passed, any findings logged.
> Await human go/no-go before continuing.

**Step 7 — Repeat** for next task.

**Step 8 — All tasks complete:** Announce and invoke `workflow/finishing-a-development-branch`.

## Process Flow

```
For each task:
  dispatch implementer → await →
  dispatch code-reviewer → await →
  Critical? → STOP, surface →
  Important? → ask human →
  mark done →
  checkpoint? → ask human →
  next task
```

## Red Flags

| Thought | Reality |
|---|---|
| "This task is simple, skip review" | Every task gets reviewed. No exceptions. |
| "The last N tasks were fine, I'll batch review" | Each task reviewed individually. Bugs compound. |
| "The human said autonomous, so I'll never surface" | Critical findings always surface. Autonomy has a ceiling. |

**REQUIRED SUB-SKILL:** `workflow/using-git-worktrees` must have run first. Use `workflow/finishing-a-development-branch` when done.
