---
name: debug-issue
description: >
  Use WHEN investigating a bug or unexpected behaviour — before writing any fix.
  Triggers on: "bug", "broken", "not working", "error", "exception", "investigate", "why is X".
when_to_use: Use to diagnose a bug using hypothesis-first, test-reproduces-first discipline. Run before implement-slice for any fix.
when_not_to_use: The cause is already confirmed and a plan exists — go to implement-slice.
inputs: [bug report with steps/expected/actual, affected area or repro environment]
read_first: [docs/contexts/<latest>.md, files the bug appears to live in, existing tests near those files]
outputs: debug_report.md
hard_stops: [bug is in a no-go zone → escalate, fix requires schema/contract change → exit to plan-feature, 30 min no repro → write up and ask]
---

# debug-issue

> Reproduce as a test before fixing. Hypothesis-first.

## Goal
Take a reported bug and produce: a reproducing test (RED), a fix (GREEN), a one-paragraph explanation, and a prevention note.

## Steps
1. Restate the bug. Confirm steps and expected vs actual.
2. Form a *single* hypothesis. Write it down.
3. Write a test that fails *for the hypothesised reason*. Run it. Confirm RED.
4. If red for the wrong reason → revise hypothesis, go to step 2.
5. Apply the minimum fix. Run the test. Confirm GREEN.
6. Run the full suite. Confirm nothing else broke.
7. Write `debug_report.md`.

**The Iron Law for bugs:** No fix without a reproducing test first. If the test is hard to write, the bug is harder to fix — that is the signal, not the problem.

## Gates
- There is a named reproducing test in the repo, currently passing
- The fix is smaller than the test
- A one-sentence prevention note exists

## Stop When
- The bug is in a no-go zone → escalate
- The fix would require schema or contract changes → exit to `plan-feature`, do not expand
- You cannot reproduce after 30 minutes → write up what you tried and ask the user

## Output Schema → `debug_report.md`

```markdown
# debug · <slug>

## report
<verbatim ticket / quote>

## repro
<exact steps the test takes>

## hypothesis
<one sentence>

## root cause
<one paragraph, plain English>

## fix
<file:line summary>

## test
<test name in repo>

## prevention
<one sentence: lint rule? skill update? doc? type? property test?>
```
