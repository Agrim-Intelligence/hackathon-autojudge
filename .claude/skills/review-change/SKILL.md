---
name: review-change
description: >
  Use WHEN a slice is implemented and tested — before marking work done or moving to the next slice.
  Triggers on: "review the change", "review this slice", "code review", "LGTM?", "ready to merge?".
when_to_use: Use after test-change to catch issues before they cascade. Dispatches a code-reviewer subagent.
when_not_to_use: No diff exists yet. Reviewing a plan (that's plan-feature's job).
inputs: [docs/plans/<slug>.md, implementation_notes.md, test_report.md, git diff]
read_first: [the plan (slice + risks sections), the diff, neighbouring files for style baseline, docs/decisions/design-watches.md (active watches)]
outputs: review.md
hard_stops: [diff much larger than the slice suggests → ask, diff includes hard-stop change without sign-off]
---

# review-change

> A second pair of eyes before the human. Dispatches the code-reviewer subagent.

## Goal
Review the slice's diff against the plan and produce `review.md` — via a dedicated `code-reviewer` subagent that works from precisely crafted context, not this session's history.

## How to Dispatch the Reviewer

Use the `Agent` tool with type `general-purpose` and the prompt from `.claude/agents/code-reviewer.md`.

Fill in the placeholders:
- `{DESCRIPTION}` — one paragraph summarising what this slice does
- `{PLAN_SLICE}` — the relevant slice entry from the plan file
- `{DIFF}` — `git diff` output (or the files changed if no git context)
- `{ACTIVE_WATCHES}` — the active entries from `docs/decisions/design-watches.md` (paste them, or "none" if empty)

The reviewer returns: Strengths → Issues (Critical/Important/Minor) → Assessment.

**After the reviewer returns:**
- Fix all Critical issues before proceeding to the next slice
- Fix Important issues before proceeding
- Note Minor issues for later
- Push back (with reasoning) if reviewer feedback is incorrect

## Seven-Pass Review (what the subagent runs)

1. **Plan trace.** For each changed line group, point at the plan item it serves. Flag orphans.
2. **House style.** Naming, imports, error shapes, formatting. Compare against neighbours.
3. **Tests.** Acceptance tests present? RED→GREEN cycle followed? Tests assert real behaviour?
4. **Side effects.** Migrations, env, public contracts, breaking changes — flagged in notes?
5. **Orphans.** Dead imports, unreachable branches, unused exports left by this slice.
6. **DRY.** Does the change duplicate a function/pattern that already exists? Point at the canonical version.
7. **Design-watch compliance.** For each active watch whose *applies-when* matches the diff, verify the rule holds. Violation = finding (Critical if it guards a shipped-incident class).

## Gates
- Every finding has a severity: `blocker` / `nit` / `praise`
- Every blocker cites file and line
- A "ready: yes/no" verdict at the top of the report

## Stop When
- The diff is much larger than the slice scope suggests → ask before reviewing further
- The diff includes a hard-stop change (auth, secrets, migrations) without explicit sign-off in the plan

## Output Schema → `review.md`

```markdown
# review · <slug> · slice <id>

## summary
<X> blockers · <Y> nits · <Z> praise items
ready: <yes / no>

## blockers
[B1] <path:line> — <issue> — <suggested fix>

## nits
[N1] <path:line> — <issue>

## praise
- <thing done well>

## plan trace (audit)
- A1 → <files/lines> ✓
- (orphan lines listed here)
```
