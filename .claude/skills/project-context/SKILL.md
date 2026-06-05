---
name: project-context
description: >
  Use WHEN starting a new session, switching repos, or about to begin any
  non-trivial task — before writing a plan or touching code.
  Triggers on: "new session", "new repo", "before we start", "what's the structure".
when_to_use: Use before any task that requires understanding the repo — always the first skill in a session.
when_not_to_use: Already ran this session and the task hasn't changed scope.
inputs: [repo root, project-rules.md, read-first docs, optional one-line task description]
read_first: [.claude/project-rules.md, README.md]
outputs: docs/contexts/<slug>.md
hard_stops: [missing project-rules.md → ask, no README and no entry point → ask]
---

# project-context

> Build the shared ground truth this session will run on. Run first, every time.

## Goal
Produce a concise, repo-grounded `docs/contexts/<slug>.md` that every other skill in the loop can rely on — instead of the model inventing architecture.

## Steps
1. Read `.claude/project-rules.md`. Note the test command, no-go zones, and "read first" list.
2. **Architecture check:** does `docs/contexts/architecture/README.md` exist?
   - YES → read it and include the module pipeline in the architecture section of the output.
   - NO → note at the bottom of the context file: "⚠ Architecture doc missing — run `core/externalize-architecture` to build the Layer 2 foundation for this repo."
3. **Decision log check:** does `docs/decisions/<current YYYY-MM>.md` exist?
   - YES → read it; surface any decisions relevant to the current task in the "relevant to current task" section.
   - **Design-watch check:** does `docs/decisions/design-watches.md` have active entries? If so, list any whose *applies-when* could match the current task in the "active design-watches" section of the output — so the plan honours them from the start.
4. Walk the top-level repo structure. Identify entry points, primary modules, the test runner.
5. Read each "read first" doc from `project-rules.md`. Summarise in 2-3 bullets each.
6. If a user task was provided, identify the 3-7 files most likely involved.
7. Write the context file per the output schema. Keep it under 200 lines.
8. Surface anything ambiguous as numbered questions at the end of the file.

## Gates
- Every claim about architecture traces to a real file path — no invention
- "Read first" docs were actually read, not paraphrased from memory
- File is under 200 lines
- No-go zones restated verbatim from `project-rules.md`
- **`docs/contexts/<slug>.md` is written to disk.** Not complete until the file exists — a chat summary does not count.

## Stop When
- `.claude/project-rules.md` is missing → ask which file to use, or whether to author one
- The repo has no README and no obvious entry point → ask the user
- "Read first" docs listed in project rules do not exist → flag and ask

## Output Schema → `docs/contexts/<slug>.md`

```markdown
# context · <repo name> · <date>

## what this repo does
<3 sentences>

## architecture, in 5 bullets
- <module> · <one-line purpose>

## test runner & commands
- run all: `<cmd>`
- run one: `<cmd>`

## conventions (from project-rules.md)
- <verbatim>

## no-go zones (from project-rules.md)
- <verbatim>

## relevant to current task
- <file path> · <why it matters>

## active design-watches (if any match this task)
- DW-<NN> · <rule> — <why it applies here>

## open questions
1. <numbered question>
```
