# project-rules.md · TEMPLATE

> One file per repo. Local truth. Read by every skill. Keep it tight.
>
> **This is the template.** Copy it to `.claude/project-rules.md` in your repo and replace every `<placeholder>`. The skills read `project-rules.md` (not this file).

---

## test command
```bash
# how do tests run? (e.g. npm test · pytest · go test ./...)
<command>
```

## linter / formatter / type-check
```bash
<commands>
```

## read first
The skills will read these before doing anything substantive.
- `README.md`
- `docs/contexts/architecture/README.md`  # if does not exist then run externalize-architecture
- `<other key doc>`

## public contracts
Where this repo exposes a contract another team or service consumes:
- HTTP: `<path or OpenAPI ref>`
- events: `<path or schema ref>`
- exported types: `<package boundary>`

## conventions
- naming: <one line>
- imports: <one line>
- error shapes: <one line>
- file structure: <one line>

## no-go zones
The skills must STOP and ask before touching these:
- `<path or area>` — <reason>

## owners
- repo owner: <name>
- on-call: <rotation link>
- ai-skills lead: <name>

## autonomy ceiling
tasks-between-checkpoints: <N>

## sdlc-gates
The hooks enforce the loop mechanically. Tune them in `.claude/sdlc-gates.conf`
(shell `KEY=value`; optional — sensible defaults apply if absent):
- `SOURCE_EXTS` — space-separated extensions the gates treat as source (default covers common languages).
- `PLAN_FRESHNESS_HOURS` — how recent a `docs/plans/*.md` must be to satisfy the plan-gate (default `24`).
- `TDD_GATE` — `off` | `warn` | `strict` (default `warn`). `strict` blocks completion when source changed without `test_report.md`.

**Override:** `touch .claude/.allow-direct-edits` is the deliberate, explicit
"the engineer approved direct edits" signal — it short-circuits the plan-gate
and Stop-gate. Remove it when done. Assumed urgency is NOT an override.

## design-watches
Repo-specific, always-on review gates born from real incidents live in
`docs/decisions/design-watches.md` (capped ~10-12, prunable). They grow
naturally: when `record-decision` captures a lesson that must gate every future
plan/review here AND a linter can't catch it, it appends a watch. See
`docs/decisions/README.md` for the lesson router and the format.