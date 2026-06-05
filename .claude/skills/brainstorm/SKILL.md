---
name: brainstorm
description: >
  Use WHEN the ask is exploratory — unclear scope, competing approaches not yet evaluated,
  or the question is "what should we build?" not "how do we build X?".
  Triggers on: "brainstorm", "explore options", "think through", "unclear what to build",
  "discovery", "let's discuss approaches", "what's the best way to", "help me figure out".
when_to_use: Use when you need to explore design space before committing to a plan. Produces a committed spec; plan-feature reads it.
when_not_to_use: You already know what to build — use plan-feature directly. Brainstorm is for discovery, not planning.
inputs: [exploratory ask or problem statement, docs/contexts/<latest>.md]
read_first: [docs/contexts/<latest>.md, docs/specs/ (check for prior related specs)]
outputs: docs/specs/<slug>.md
hard_stops: [do NOT invoke plan-feature or write any code until user has approved the spec]
---

# brainstorm

> Explore before committing. Spec before planning. Discovery is doing.

## Goal
Turn an unclear ask into a clear, committed spec that `plan-feature` can read as its primary input — through structured conversation, not premature planning.

<HARD-GATE>
Do NOT invoke plan-feature, write code, scaffold, or implement ANYTHING until:
1. The spec document exists at docs/specs/<slug>.md
2. The user has explicitly approved it
This applies to every request, regardless of perceived simplicity.
</HARD-GATE>

## Pre-flight

1. Read `docs/contexts/<latest>.md`. If it doesn't exist, run `core/project-context` first.
2. **Scope check (before asking any questions):** does the request describe multiple independent subsystems or outcomes? If yes — help decompose into sub-projects first. Don't ask detailed questions about details of a project that hasn't been scoped yet.
3. Check `docs/specs/` — is there a prior spec for a related ask? If yes, frame as a refresh, not a fresh start.

## Conversation — one or two questions at a time

### 1. Purpose
- What problem is this solving? Not the feature — the human pain.
- Who has this problem and what do they do today instead?

### 2. Constraints and success criteria
- What does "done" look like? What's the smallest thing that's worth shipping?
- What must this NOT do, touch, or break?
- What's the time/effort budget?

### 3. Approaches
- Propose 2-3 different approaches with trade-offs and your recommendation.
- Lead with your recommended option and explain why.

### 4. Design
- Present the chosen design in sections. Ask after each: "Does this look right?"
- Focus on: what the user does → what the system does → what the output is.

## Spec self-review (run before asking user to approve)

After writing the draft, check:
1. **Placeholder scan:** any "TBD", "TODO", vague sections? Fix inline.
2. **Internal consistency:** do any sections contradict each other?
3. **Scope:** is this focused enough for a single plan, or needs decomposition?
4. **Ambiguity:** any requirement that can be interpreted two ways? Pick one explicitly.

Fix all issues inline. No need to re-review after fixing.

## User review gate

After the self-review passes:
> "Spec written at `docs/specs/<slug>.md`. Please review it before I write the implementation plan — especially the 'what this is NOT' section."

Wait for the user's response. If they request changes, make them and re-run the spec self-review. Only hand to `plan-feature` once the user approves.

## Steps

1. Pre-flight (scope check + prior specs check).
2. Ask clarifying questions one at a time (purpose → constraints → approaches).
3. Present design in sections, get section-by-section approval.
4. Write `docs/specs/<slug>.md` (see output schema).
5. Run spec self-review (4-point check above). Fix inline.
6. User review gate — wait for explicit approval.
7. Invoke `core/plan-feature` (reads the spec as its primary input).

## Gates
- User has explicitly approved the spec before plan-feature is invoked
- "What this is NOT" section has at least 2 explicit out-of-scope items
- Hard rules section has at least one MUST NEVER

## Stop When
- The scope is so large it needs decomposition first → stop, decompose, then brainstorm the first sub-project
- The ask is already well-specified → redirect to `plan-feature` directly

## Output Schema → `docs/specs/<slug>.md`

```markdown
# spec · <slug> · <date>

## the ask (restated)
<one paragraph — what we think we're building, in the user's terms>

## approaches considered
- A: <name> — <tradeoff in one sentence>
- B: <name> — <tradeoff in one sentence>

## chosen approach
<A or B>, because <2 sentences>

## design
<How it works — what the user does, what the system does, what the output is>

## what this is NOT
- <explicit out-of-scope item, with reason>
- <explicit out-of-scope item, with reason>

## hard rules
- MUST NEVER: <specific constraint>
- MUST ALWAYS: <specific constraint>

## open questions before planning
1. <question that blocks planning — or "none">

## status
draft / approved on <date>
```
