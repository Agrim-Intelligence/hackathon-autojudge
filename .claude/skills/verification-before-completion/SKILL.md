---
name: verification-before-completion
description: >
  Use WHEN about to mark a task complete, declare done, or dispatch code-reviewer — 5-point gate
  verifying acceptance criterion, full suite, scope, DRY, and hard stops before review.
  Triggers on: "mark task done", "task complete", "ready for review", "done with slice",
  "checking in", "am I done", "verify done", before dispatching code-reviewer.
when_to_use: Use after all tests pass but before dispatching code-reviewer. Takes under 2 minutes. Prevents review of incomplete work.
when_not_to_use: The task is not yet at "tests passing" stage — finish implement-slice and test-change first.
inputs: [docs/plans/<slug>.md (the plan slice + acceptance criterion), the diff, test results]
read_first: [docs/plans/<slug>.md — find the exact slice and its acceptance criterion]
outputs: completion checklist appended to implementation_notes.md — PASS or FAIL with specifics
hard_stops: [do NOT dispatch code-reviewer while any checklist item FAILS — fix first]
---

# verification-before-completion

> Are you actually done? Check before you declare.

## Goal
A fast 5-point gate that confirms the implementation satisfies its plan acceptance criterion before the code-reviewer sees it. Prevents review of work that doesn't match the plan — the most common source of "Critical: spec compliance failure" findings.

## The 5-Point Checklist (run in order, stop on first FAIL)

**1. Acceptance criterion met**
Find the exact acceptance criterion from the plan slice (usually `should_<verb>_<noun>`). Is there a test in the suite with that name, currently passing? Name it.

- PASS: `tests/auth.test.ts::should_reject_unauthenticated_admin_calls` — GREEN ✓
- FAIL: no test named after the acceptance criterion, or the test is not green

**2. Full suite green**
Run ALL tests — not just the new ones. Zero regressions.

- PASS: `N tests passed, 0 failed` ✓
- FAIL: any test that was passing before is now failing → fix before review

**3. Scope clean**
Does the diff contain ONLY changes listed in the plan slice's scope? Open the plan, open the diff, compare.

- PASS: every changed file is listed in the plan's scope section ✓
- FAIL: a file was changed that's outside the plan scope → stop and ask if this was intentional

**4. DRY check**
Did this implementation introduce a function, utility, or data pattern that already exists in the codebase? Quick grep before declaring done.

```bash
grep -r "<key-function-name>" src/ | grep -v "the file you just wrote"
```

- PASS: nothing found, or you found it and reused the existing implementation ✓
- FAIL: you duplicated something → refactor to reuse the canonical version

**5. Hard stops clean**
Did the implementation unexpectedly touch auth, billing, PII, secrets, or cross-team contracts? Check the diff against the no-go zones in `project-rules.md`.

- PASS: no unexpected contact with hard-stop areas ✓
- FAIL: stop immediately. Do NOT dispatch review. Surface to human.

## Steps

1. Pull up the plan slice (find the exact acceptance criterion).
2. Run the 5 checks in order. Name the result (PASS/FAIL) for each.
3. If ALL 5 pass → append the completion note to `implementation_notes.md` and proceed to `core/review-change`.
4. If ANY fail → fix the failing item before re-running the checklist.

## Output → appended to `implementation_notes.md`

```markdown
## verification-before-completion · <slice ID> · <date>
1. Acceptance criterion: PASS — test: <test name> GREEN
2. Full suite: PASS — <N> tests, 0 failures
3. Scope clean: PASS — all changed files in plan scope
4. DRY check: PASS — grepped <term>, no duplicates found
5. Hard stops: PASS — no unexpected contact with no-go zones
→ Ready for review-change
```

If any item FAILS, list the failure and the fix applied before moving on.

## Rules

- **Fail = stop.** Fix the item. Re-run the checklist from the top.
- **Do not rationalize past a FAIL.** "It's close enough" is not a PASS.
- **Subagent implementers must run this** before returning their summary — it's the last step before dispatching the code-reviewer.
