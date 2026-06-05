---
name: migration-check
description: >
  Use WHEN a change includes a database schema change, data migration, or model/table modification.
  Triggers on: "migration", "schema change", "ALTER TABLE", "new column", "backfill", "DDL", "data migration".
when_to_use: Use before shipping any DB schema or data migration — covers forward path, backfill, rollback, and canary.
when_not_to_use: No DB or schema change in the diff.
inputs: [migration files (DDL/framework/scripts), data domain (table name, est. row count, hot path?)]
read_first: [the migration files, model/schema definitions, prior migrations in the same area]
outputs: migration_plan.md
hard_stops: [migration locks hot table beyond project threshold → ask, rollback would lose data → eng lead sign-off required, change to billing or auth table → escalate]
---

# migration-check

> For any DB change: forward path, backfill, rollback, canary read-write.

## Goal
Take a proposed schema or data migration and produce `migration_plan.md` — covering forward, backfill, rollback, and the canary path.

## Steps
1. State the goal of the migration in one sentence.
2. **Forward path**: exact order of operations. Reversible? Idempotent?
3. **Backfill**: needed? Strategy (batched? throttled?). Estimated time.
4. **Rollback**: exact steps. Data-preserving or destructive?
5. **Canary**: which one row / one tenant / one shard you will touch first.
6. **App compatibility**: does the app handle both old and new shape during rollout?
7. **Lock impact**: blocking operations? Estimated lock window? Off-peak required?

## Gates
- Every step in the forward path is reversible OR explicitly marked one-way with justification
- A backfill plan exists for every non-nullable column addition
- Rollback steps are written out, not "we will figure it out"
- "App handles both shapes" is confirmed true for the full duration of rollout

## Stop When
- The migration would lock a hot table beyond the project's stated threshold → ask
- Rollback would lose data → require eng lead sign-off in writing before proceeding
- The change is to a table with active billing or auth records → escalate

## Output Schema → `migration_plan.md`

```markdown
# migration · <slug>

## goal
<one sentence>

## forward
1. <step>
2. <step>

## backfill
- needed: <yes/no>
- strategy: <batch size, throttle, est. duration>

## rollback
1. <step>

## canary
- first target: <one row / tenant / shard>
- verify: <how you confirm it worked>

## compatibility
- app handles old shape: <until when>
- app handles new shape: <from when>

## locks & timing
- locks: <yes/no, which tables, est. duration>
- recommended window: <peak / off-peak>
```
