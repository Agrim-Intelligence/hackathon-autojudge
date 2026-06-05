---
name: finishing-a-development-branch
description: >
  Use WHEN all plan tasks are complete — offers PR, merge, keep, or discard, then cleans up the worktree.
  Triggers on: "tasks complete", "done with the plan", "finish the branch", "merge this", "open PR", "clean up worktree".
when_to_use: Use after subagent-driven-development (or implement-slice) finishes all plan tasks to close out the branch cleanly.
when_not_to_use: Tasks are not all complete yet. Use this only at the true end of a plan.
inputs: [docs/plans/<slug>.md (all tasks checked), worktree path, branch name]
read_first: [review.md (confirm no open Critical findings), release-check.md if exists]
outputs: PR URL, merge confirmation, or discard note. Worktree removed.
hard_stops: [any unchecked task in the plan → do not finish, open Critical finding in review.md → resolve first]
---

# finishing-a-development-branch

> All tasks done. Verify, offer choices, clean up.

## Goal
When all plan tasks are complete and reviewed, run the final checks and give the user four choices for what to do with the branch.

## Steps

**1. Verify completeness:**
- Confirm all tasks in the plan are checked off (`- [x]`)
- Confirm no open Critical findings in `review.md`
- If either fails: stop and report what is still open

**2. Run release-check (recommended):**
```bash
# Invoke core/review-change or delivery/release-check before merge/PR
```
If the user wants to skip: acknowledge the skip explicitly, proceed.

**3. Present the four options:**

> "All [N] tasks complete and reviewed. What would you like to do with branch `<branch-name>`?"
>
> 1. **Open a PR** — push branch to origin and open a pull request
> 2. **Merge to main** — merge locally (fast-forward or merge commit)  
> 3. **Keep the branch** — leave worktree as-is, no action
> 4. **Discard** — remove branch and worktree entirely

Await human choice.

**4. Execute the chosen action:**

*PR:*
```bash
cd <worktree-path>
git push -u origin <branch-name>
gh pr create --title "<plan goal>" --body "Plan: docs/plans/<slug>.md"
```

*Merge:*
```bash
cd <repo-root>
git merge --no-ff <branch-name> -m "feat: <plan goal>"
```
Hard stop: force-push to main/master → do not proceed, ask user.

*Keep:*
> "Branch `<branch-name>` kept. Worktree at `<path>`. Run `git worktree list` to see it."

*Discard:*
```bash
git worktree remove <worktree-path>
git branch -D <branch-name>
```
Confirm with user before running — this is destructive.

**5. Clean up the worktree** (for PR, Merge, and Discard):
```bash
git worktree remove <worktree-path>
# For PR/Merge: branch can be deleted after merge
# git branch -d <branch-name>
```

**6. Write `docs/summaries/<slug>.md`** — invoke `delivery/work-summary`.

## Gates
- All plan tasks `[x]` before any of the four options
- No open Critical findings
- Force-push to main/master requires explicit human confirmation

## Stop When
- Unchecked tasks remain → report which ones, do not proceed with finish
- Open Critical finding exists → resolve it first
- User chooses Discard → confirm explicitly ("This will delete the branch and all uncommitted work. Are you sure?")
