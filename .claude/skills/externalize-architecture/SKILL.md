---
name: externalize-architecture
description: >
  Use WHEN a repo has no architecture doc and project-context is producing invented context,
  OR when the architecture doc hasn't been refreshed in 90+ days.
  Triggers on: "create architecture doc", "capture architecture", "document the structure",
  "no context exists", "project-context is hallucinating", new repo setup.
when_to_use: Use before project-context on a new or undocumented repo. Refresh quarterly on mature repos. Run once; maintain with maintain-context.
when_not_to_use: Architecture doc at docs/contexts/architecture/README.md already exists and is recent (< 90 days). Use project-context instead.
inputs: [repo root, codebase, project-rules.md (partial OK), recent PRs or plans if any]
read_first: [.claude/project-rules.md, README.md, any existing docs/contexts/]
outputs: docs/contexts/architecture/README.md + docs/contexts/architecture/structure.md + docs/contexts/architecture/runtime.md
hard_stops: [project-rules.md has placeholder values → fix project-rules.md first, architecture contradicts in-flight plans → flag explicitly before saving]
---

# externalize-architecture

> Build the Layer 2 foundation that makes every session accurate. AI drafts; you approve.

## Goal
Produce `docs/contexts/architecture/README.md` and two part-docs (`structure.md`, `runtime.md`) through a structured conversation — so that `project-context` reads real architecture instead of inventing it.

**This is AI-authored under user approval.** The AI reads the codebase and drafts; the user approves shape changes. This is different from skills where the user authors the content. The AI proposes; you ratify.

## Pre-flight

1. **`project-rules.md` must be filled in.** Check for placeholder values (`<command>`, `<name>`, etc.). If found — stop. Fix `project-rules.md` first. Architecture must be consistent with the constraints and conventions defined there.
2. **Does `docs/contexts/architecture/` already exist?** If yes → this is a refresh. Frame questions as "what's changed" not "what do we have". If no → fresh capture.
3. **Headspace check.** "This is ~30-45 min. Ready, or should we pick another time?"

## Conversation — one or two questions at a time

### 1. The module pipeline
- What are the top-level modules/services/packages in this codebase? What does each one *do* (one sentence each)?
- How do they depend on each other? What is the direction of dependency?
- Where does a user request enter the system, and what path does it take to produce a result?

### 2. Directory structure
- What does the directory layout look like at the top two levels? What is each folder responsible for?
- "Where do I put a new file?" — what is the answer for each major file type?
- What's the rule about what must not mix? (e.g. "domain logic never imports from infra")

### 3. Runtime and data flow
- How does the primary data model flow through the system at runtime?
- Where are the validation and quality gates? What do they enforce?
- What are the key contracts that cross module boundaries?

### 4. Dev rules (the must-gate rules for this codebase)
- What rules does every diff *must* respect? (These live in `CLAUDE.md` and `project-rules.md` — the architecture front-door *links* to them, never duplicates.)
- Confirm the existing no-go zones in `project-rules.md` are consistent with what you just described.

### 5. Direction (where this architecture is heading)
- What architectural direction is intentionally being pursued next? (e.g. moving toward event-driven, extracting a service, consolidating a module)
- What is deliberately deferred and should not be done yet?

### 6. Stress tests
- "Show me one current code surface that violates this architecture. Does it? Should it?"
- "If a developer takes a shortcut tomorrow that contradicts what we just said — what does that shortcut look like? Is the architecture specific enough to catch it?"

## Synthesis — what to write

**`docs/contexts/architecture/README.md`** (the front-door — short; links the part-docs; doesn't absorb them):
```markdown
# Architecture · <repo name>

**Last updated:** YYYY-MM-DD
**Reviewed by:** <name>

## What this repo does
<1-2 sentences>

## The module pipeline
<Top-level data flow: module A → module B → module C>
<Each module: one-line purpose>

## Directory map
<Prose or bullet list: folder → responsibility>

## The dev rules
See `.claude/CLAUDE.md` and `.claude/project-rules.md` (no-go zones, conventions).
This doc links them — does not restate them.

## Details
- [Structure: modules, dependencies, directory layout](structure.md)
- [Runtime: data flow, quality gates, key contracts](runtime.md)

## Direction
<Where the architecture is heading. What's deferred.>
```

**`docs/contexts/architecture/structure.md`** — modules, dependencies, directory layout in detail.

**`docs/contexts/architecture/runtime.md`** — data flow at runtime, validation gates, cross-module contracts.

## Save

1. Write the three files to `docs/contexts/architecture/`.
2. Add `docs/contexts/architecture/README.md` to the `read_first` section of `.claude/project-rules.md` if not already there.
3. Record the architectural decisions surfaced: run `core/record-decision` for any non-obvious decision or constraint that emerged (e.g. "we chose X over Y because Z").

## Rules

- **AI-authored, user-approved.** Draft from codebase + conversation. Surface shape changes for the user to ratify. Don't unilaterally redefine the architecture.
- **Front-door links; it doesn't absorb.** Dev rules stay in CLAUDE.md and project-rules.md. Detail stays in the part-docs. The README is the map.
- **Examples over adjectives.** "Module-agnostic dependency injection where X never imports Y" beats "clean and extensible."
- **Architecture serves the code, not the reverse.** If what's described here contradicts what's actually in the repo — name that gap and decide: fix the code, or update the architecture.
- **Flag conflicts with in-flight plans.** If the new architecture contradicts active plans or open PRs, flag them explicitly before saving.
