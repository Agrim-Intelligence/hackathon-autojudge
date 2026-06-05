---
name: writing-skills
description: Use when creating a new Agrim skill, editing an existing skill, or verifying a skill works before merging a PR to .claude/skills/
---

# Writing Skills

## Overview

Writing skills IS TDD applied to process documentation. You write pressure scenarios (tests), watch an agent fail without the skill (RED), write the skill addressing those specific failures (GREEN), and close loopholes until bulletproof (REFACTOR).

**The Iron Law:** No skill without a failing test first. This applies to new skills AND edits to existing skills.

## SKILL.md Format

Every Agrim skill MUST follow this structure exactly — Claude Code reads these frontmatter fields for native Skill-tool discovery.

```markdown
---
name: skill-name-with-hyphens
description: >
  Use WHEN <triggering conditions only — never workflow summary>.
  Triggers on: <comma-separated phrases the agent would say>.
when_to_use: <one sentence — the search-match target>
when_not_to_use: <e.g. trivial typo fixes, doc-only edits>
inputs: [feature request, plan file, repo state, ...]
read_first: [.claude/CLAUDE.md, project-rules.md, docs/contexts/<latest>.md]
outputs: <artifact path, e.g. docs/plans/<slug>.md>
hard_stops: [auth, billing, PII, secrets, destructive ops, cross-team contracts]
---

# Skill Name

## Goal
<One sentence. If you can't write it, you can't run the play.>

## Steps
1. Numbered. Verifiable. Ordered. Written for a junior with no project context.
   Include exact commands, file paths, and expected outputs.
   
## Gates
- <What must be true before each step / to proceed to the next skill>

## Stop When
- <Hand back to a human — name the condition>

## Output Schema
→ `<artifact path>` with sections:
- **<section>:** <what goes here>
```

### Critical: Description Field Rules (CSO)

The `description` field is the trigger signal — it determines when the agent loads this skill. It MUST:
- Start with "Use WHEN..."
- Describe **triggering conditions only** — never summarize the workflow
- Be written in third person

**Why this matters:** Testing shows that a description summarizing the workflow causes agents to follow the summary *instead of reading the skill body*. The skill becomes dead documentation.

```yaml
# ❌ BAD — summarizes workflow; agent follows this instead of reading skill
description: Use for planning — brainstorm, propose approaches, write plan file

# ✅ GOOD — triggering conditions only
description: >
  Use WHEN starting any non-trivial change before writing code.
  Triggers on: "build", "add", "implement", "let's plan", ticket link.
```

### Frontmatter Field Notes

- `name`: letters, numbers, hyphens only. No parentheses or special chars.
- `description`: max ~500 chars; `when_to_use` can hold overflow.
- `when_to_use`: one sentence; supports matching when the platform indexes skills.
- `outputs`: exact path so engineers can find the artifact.
- `hard_stops`: repeat the relevant subset from `getting-started` here.

### Body Structure

```
## Goal          — one sentence, the success condition
## Steps         — numbered, written for a junior, exact commands included
## Gates         — entry/exit conditions
## Stop When     — hand-back conditions (hard stops + ambiguity)
## Output Schema — the artifact this skill produces, section by section
```

Add a **Red Flags** rationalization table for discipline-enforcing skills (TDD, review, planning gates). Named rationalizations with counters.

### Token Targets

- `getting-started` and frequently-loaded skills: < 200 words
- Other skills: < 500 words

Techniques: cross-reference other skills by name (`REQUIRED SUB-SKILL: agrim:plan-feature`), never `@path` links (those force-load the full file into context immediately).

---

## TDD for Skills — RED → GREEN → REFACTOR

### RED: Establish Baseline

Run 2-3 pressure scenarios WITHOUT the skill present. Pressure types that reveal compliance gaps:

- **Time pressure** — "production is down, just fix it fast"
- **Sunk cost** — "we've already written half the code, let's just finish"
- **Authority** — "the CTO says skip the planning step this once"
- **Exhaustion** — back-to-back tasks with no checkpoints

Document exact rationalizations the agent uses to skip or shortcut. These verbatim failures become your rationalization table entries.

### GREEN: Write Minimal Skill

Address those specific rationalizations. Only what you observed failing. No speculative additions.

Run the same scenarios WITH the skill. Agent should now comply.

### REFACTOR: Close Loopholes

When the agent finds a new rationalization: add an explicit counter. Re-test. Repeat until the skill is bulletproof.

**The Iron Law repeated:**
```
NO SKILL WITHOUT A FAILING TEST FIRST
```
Edit without testing? Same violation. Delete. Start over.

---

## Skill Creation Checklist

**RED Phase:**
- [ ] Write 2-3 pressure scenarios in `tests/skills/<name>/`
- [ ] Run WITHOUT skill — document failures and rationalizations verbatim
- [ ] Identify patterns in how the agent shortcuts

**GREEN Phase:**
- [ ] Frontmatter: `name`, `description` (triggering conditions only), all extended fields
- [ ] Body: Goal → Steps → Gates → Stop When → Output Schema
- [ ] Red Flags table if discipline-enforcing
- [ ] Address every rationalization observed in RED
- [ ] Run WITH skill — verify compliance

**REFACTOR Phase:**
- [ ] Find new rationalizations → add explicit counters → re-test
- [ ] Word count check: < 200 words if frequently loaded, < 500 otherwise

---

## Anti-Patterns

**❌ Narrative skill** — "In session X, we discovered..." — Too specific, not reusable.

**❌ Workflow description in `description`** — Agents follow the summary, skip the body.

**❌ Vague steps** — "Add appropriate error handling." Every step needs the actual content.

**❌ Testing after writing** — You don't know what you're teaching until you watch an agent fail without it.

---

## Where to Put the Skill

```
.claude/skills/
  getting-started/SKILL.md        — bootstrap only
  core/                           — the daily-five loop
  risk/                           — debug, security, contract, migration
  delivery/                       — release, summary, improvement
  meta/                           — writing-skills (this file), other meta
  workflow/                       — git-worktrees, subagent dispatch (Phase 3+)
```

If the skill applies broadly across all engineering sessions → `core/` or `meta/`.
If it guards against a specific risk → `risk/`.
If it is project-specific → it goes in that project's `project-rules.md`, not here.
