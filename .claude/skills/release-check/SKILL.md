---
name: release-check
description: >
  Use WHEN a change is about to be shipped to production — the final pre-flight gate.
  Triggers on: "ready to ship", "deploy", "release", "merge to main", "go live", "pre-flight".
when_to_use: Use immediately before shipping any non-trivial change to production. Run after review-change.
when_not_to_use: Change not being shipped yet. Draft PR or WIP.
inputs: [the PR or set of PRs about to ship, plan + implementation_notes + test_report + review.md]
read_first: [the plan, review.md, any feature flags the change toggles, on-call rota]
outputs: release_check.md
hard_stops: [any checklist item fails → do NOT ship, migration involved but migration-check not run → run it first, contract change with unnotified consumers → halt]
---

# release-check

> The pre-flight checklist. Run before anything goes to prod.

## Goal
Confirm a change is genuinely ready to ship, and produce `release_check.md` — the artifact a release captain reads.

## Steps
1. Run the eleven-point checklist. Each item: `pass` / `fail` / `n/a` + one line.
2. Identify the canary path: who / what / where gets it first, and the verification metric.
3. Identify the rollback path: exact steps, timing (target ≤ 5 min).
4. Confirm the right people are notified (on-call, dependent teams).
5. State the release window (now / scheduled / off-peak).

## Eleven-Point Checklist
1. Tests green — full suite, not just affected files
2. Type / lint clean
3. Plan trace clean (no orphan diff lines)
4. `review.md` says ready
5. Feature flag set correctly (default-off for risky changes)
6. Migrations sequenced; backfills started
7. Dashboards / alerts present for new surfaces
8. On-call notified
9. Dependent teams notified (if contract changed)
10. Rollback path written and tested in staging
11. Release notes / changelog updated

## Gates
- Every checklist item has `pass` / `fail` / `n/a` + reason
- Rollback path includes timing ("≤ 5 min")
- Canary path includes a named verification metric

## Stop When
- Any item is `fail` → do NOT ship, fix and re-run this skill
- Migration involved but `migration-check` was not run → run it first
- Contract change but consumers were not notified → halt

## Output Schema → `release_check.md`

```markdown
# release check · <slug>

## checklist
1. tests · <pass/fail/n-a> · <one line>
2. type/lint · <pass/fail/n-a> · <one line>
3. plan trace · <pass/fail/n-a> · <one line>
4. review ready · <pass/fail/n-a> · <one line>
5. feature flag · <pass/fail/n-a> · <one line>
6. migrations · <pass/fail/n-a> · <one line>
7. dashboards · <pass/fail/n-a> · <one line>
8. on-call notified · <pass/fail/n-a> · <one line>
9. dependent teams · <pass/fail/n-a> · <one line>
10. rollback tested · <pass/fail/n-a> · <one line>
11. release notes · <pass/fail/n-a> · <one line>

## canary
- target: <who/what>
- verify: <metric, expected range>
- timing: <how long before full rollout>

## rollback
- steps: <ordered list>
- max time to rollback: <X minutes>

## notifications
- on-call: <who, when>
- dependent teams: <list>

## go/no-go
<go / no-go> — <one sentence>
```
