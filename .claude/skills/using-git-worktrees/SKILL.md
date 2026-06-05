---
name: using-git-worktrees
description: >
  Use WHEN starting implementation on a plan — creates an isolated branch and worktree
  so work cannot clobber the main branch or other parallel tasks.
  Triggers on: "start implementation", "create branch", "worktree", "isolate this work".
when_to_use: Use after plan-feature approval and before implement-slice or subagent-driven-development to create a clean isolated workspace.
when_not_to_use: Trivial single-file edits where isolation adds no value. No plan exists yet.
inputs: [approved plan file path, branch name (suggest <slug>-<date> if not provided)]
read_first: [docs/plans/<slug>.md, .claude/project-rules.md (test command required)]
outputs: An isolated git worktree at /tmp/agrim-work/<slug>/ on branch <branch-name>
hard_stops: [project-rules.md missing test command → ask before running setup, uncommitted changes on base → ask user to stash]
---

# using-git-worktrees

> Every plan gets its own branch and worktree. Work in isolation; merge when done.

## Goal
Create an isolated git worktree for this plan's branch so that implementation work is fully contained — no clobbering of the main branch, no interference between parallel tasks.

## Steps

**1. Suggest a branch name** if the user hasn't provided one:
```
<slug>-YYYYMMDD
e.g. admin-rbac-20260529
```

**2. Create the worktree and verify baseline:**
```bash
bash .claude/lib/setup.sh <branch-name> <plan-slug>
```
- The script creates `git worktree add -b <branch> /tmp/agrim-work/<slug>`, runs the test suite, and confirms the baseline is clean.
- If the test command is not in `project-rules.md`, stop and ask the user to fill it in first.
- If baseline tests fail, stop and ask the user to fix them on the main branch first.

**3. Announce the worktree path:**
> "Working in: /tmp/agrim-work/<slug>/ on branch <branch-name>. Baseline tests pass."

**4. Proceed with the plan** — all implementation work happens inside the worktree path.

## Listing Active Worktrees
```bash
git worktree list
```

## Handling Conflicts
If another worktree modifies the same file, resolve on the branch before merging:
```bash
cd /tmp/agrim-work/<slug>
git fetch origin
git rebase origin/<base-branch>
```

## Cleanup
When done (via `finishing-a-development-branch`):
```bash
git worktree remove /tmp/agrim-work/<slug>
git branch -d <branch-name>   # only after merge/PR
```

**REQUIRED NEXT SKILL:** Use `workflow/subagent-driven-development` or `core/implement-slice` to do the work. Use `workflow/finishing-a-development-branch` when tasks are complete.
