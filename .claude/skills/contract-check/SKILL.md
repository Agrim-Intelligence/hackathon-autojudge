---
name: contract-check
description: >
  Use WHEN a diff changes public APIs, event shapes, exported types, CLI flags, or env vars.
  Triggers on: "breaking change", "API change", "contract", "consumers", "exported type", "event shape", "route change".
when_to_use: Use when any change could affect consumers of a public interface — detect breaking changes before they reach other teams.
when_not_to_use: Internal refactor with no exported surface. No change to public contracts.
inputs: [git diff, public contract surfaces from project-rules.md]
read_first: [project-rules.md public contracts section, OpenAPI/GraphQL/protobuf schema, exported types from package boundaries]
outputs: contract_diff.md
hard_stops: [consumer ownership unclear → ask before proceeding, cross-org contract → escalate to eng lead]
---

# contract-check

> Detect breaking changes to public APIs, event shapes, and exported types before the consumers do.

## Goal
Given a diff, produce `contract_diff.md` listing every public contract changed, every consumer affected, and whether each change is safe or breaking.

## Steps
1. Identify contracts in the diff: HTTP routes, event shapes, exported types, CLI flags, env vars.
2. For each: classify as `added` / `removed` / `changed-safe` / `changed-breaking`.
3. For each `removed` or `changed-breaking`: list the consumers (repos, services, teams).
4. For each consumer: state the action required (notify, version bump, migrate-then-remove).
5. Propose a versioning / deprecation strategy if any breaking change remains unresolved.

## Gates
- Every contract change is classified
- Every breaking change has a named consumer list (or "no known consumers — confirmed by grep")
- Every breaking change has a rollout plan (versioned, notified, or migrate-first)

## Stop When
- Consumer ownership is unclear → ask before proceeding
- The contract is cross-org → escalate to eng lead before any further work

## Output Schema → `contract_diff.md`

```markdown
# contract diff · <slug>

## summary
<N> changes · <M> breaking · ready: <yes / no>

## changes
- <kind>: <name>
  classification: <added / removed / changed-safe / changed-breaking>
  consumers: <list or "none — confirmed by grep">
  action: <notify / version-bump / migrate-then-remove>

## rollout
<paragraph: order, timing, deprecation window>
```
