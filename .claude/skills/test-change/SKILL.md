---
name: test-change
description: >
  Use WHEN tests need to be written for a completed slice — write tests, run tests, test the change.
  Triggers on: "write tests", "run tests", "test this", "test the slice", "make tests pass", RED GREEN, TDD.
when_to_use: Use after implement-slice to write and run tests that prove the acceptance criteria. Write test first, watch it fail, then implement.
when_not_to_use: No implementation exists yet (implement-slice first). Trivial config-only changes.
inputs: [docs/plans/<slug>.md, slice ID, implementation_notes.md, project-rules.md test command]
read_first: [plan's acceptance criteria for this slice, existing test files near changed files, test runner config]
outputs: test_report.md
hard_stops: [test requires seeding production data → ask, test touches third-party service without mock → ask]
---

# test-change

> Write the tests that prove the slice. RED first, then GREEN.

## Goal
For the implemented slice, write tests that turn plan acceptance criteria from "claims" into "facts."

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

**For new code:** Write the test, watch it fail, write minimal code to pass. If you wrote code before the test, delete it and start over.

**For legacy code (existing files not newly created):** Apply RED→GREEN when modifying existing logic. Do not delete legacy tests or working code to force the cycle. Document any pre-existing coverage gaps in `test_report.md`.

## RED → GREEN → REFACTOR

**RED — Write the failing test:**
1. For each acceptance criterion on this slice, write a named test.
2. For each risk in the plan that is testable on this slice, write a test.
3. Cover edge cases: empty, null, boundary, off-by-one.
4. Run the test. Verify it **fails for the right reason** — not a setup error.

**GREEN — Write minimal code to pass:**
5. Implement only what makes the test pass. No extras.
6. Run the test. Verify it passes.

**REFACTOR — Clean up:**
7. Remove duplication introduced by step 5. Re-run. Still green.
8. Run the full test suite. No regressions.

## Gates
- One named test per acceptance criterion
- New tests fail meaningfully when the change is reverted (sanity check)
- No test depends on test-order
- No asserting on log output as the only signal
- Full suite still green after refactor
- **`test_report.md` is written to disk.** Not complete until the file exists — a chat summary does not count. (The Stop-gate hook reads this file.)

## Stop When
- A test would require seeding production-shaped data → ask
- A test would touch a third-party service without a mock → ask
- An acceptance criterion cannot be expressed as a test → re-plan

## Red Flags — You Are Rationalizing. Stop.

| Thought | Reality |
|---|---|
| "Too simple to need a test" | Simple code breaks. The test takes 30 seconds. |
| "I'll write tests after" | Tests-after prove the code works. Tests-first prove the code does the right thing. |
| "Tests after achieve the same goals" | They don't. Tests-first define intent. Tests-after verify implementation. |
| "I already manually tested it" | Manual tests don't run in CI. Write the test. |

## Output Schema → `test_report.md`

```markdown
# tests · <slug> · slice <id>

## added
- <test name> · <file> · <one-line what it asserts>

## results
<test cmd output trimmed to: total · pass · fail · new>

## acceptance trace
- A<id> · <criterion> · <test name> · <pass/fail>

## still red (and why)
- <test name> · <reason: known, blocked, out-of-scope>

## sanity check
- reverted change locally → <which tests went red>
```
