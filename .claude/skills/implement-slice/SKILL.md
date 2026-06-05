---
name: implement-slice
description: >
  Use WHEN executing one slice from an approved plan — after plan-feature, before test-change.
  Triggers on: "implement slice", "let's build it", "start the work", slice ID reference.
when_to_use: Use to execute exactly one slice from an approved plan file. Not before a plan exists.
when_not_to_use: No approved plan exists (run plan-feature first). Multiple slices at once.
inputs: [plan file path, slice ID, implementation_notes.md if continuing a prior slice]
read_first: [docs/plans/<slug>.md, every file the plan says will change, neighbouring code for style]
outputs: implementation_notes.md
hard_stops: [auth, billing, PII, secrets, destructive ops, cross-team contracts, scope expansion beyond plan]
---

# implement-slice

> Execute one vertical slice of the plan. Surgical edits only.

## Goal
Implement exactly one slice from `docs/plans/<slug>.md`. Produce a diff and `implementation_notes.md`. Nothing else.

## Steps
1. Identify the named slice and its acceptance test name.
2. **DRY check before writing.** Search the codebase for similar implementations: `grep -r "<key-term>" src/`. If something does 70%+ of what you need, reuse it — don't rewrite it. Note the result: "grepped `<term>`, reused `<path>:<func>`" or "grepped `<term>`, nothing found — proceeding."
3. Make the minimum changes required to satisfy that acceptance criterion.
4. For each changed file, state what changed and *why* in one line.
5. Do not touch files outside the slice's listed scope. If you must, **stop and ask**.
6. Match house style: imports, naming, error shapes, formatting. Run the formatter.
7. Remove imports/vars/functions YOUR changes made dead. Leave pre-existing dead code alone — mention it.
8. Run `core/verification-before-completion` before writing `implementation_notes.md`.
9. Write `implementation_notes.md` per the output schema.

## Gates
- Every changed line traces to a line in the plan
- No drive-by refactors or style improvements on untouched code
- No changes outside the slice's stated scope
- Formatter run; type check clean (if applicable)
- Only orphan removals are ones your changes caused

## Stop When
- The slice would require changing a file the plan did not list → report and re-plan, do not expand
- A hard stop is hit (destructive op, auth, secrets, cross-team contract)
- You would need speculative abstractions to make it "extensible" → deliver the minimal version
- You discover the plan was wrong → stop, report, re-plan before continuing

## Output Schema → `implementation_notes.md`

```markdown
# implementation · <slug> · slice <id>

## slice
<id> — <acceptance test name>

## changes
- <path> (+<lines> / -<lines>)
  <one-line reason>

## NOT changed (intentionally)
- <thing> — <next slice / out of scope / open question>

## verify
```bash
<the exact commands to verify this slice works>
```

## orphans removed
- <import/var/func> in <path> — caused by this change

## orphans noticed but NOT removed
- <thing> in <path> — pre-existing, mentioned per house rules
```
