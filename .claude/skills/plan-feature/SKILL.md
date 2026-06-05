---
name: plan-feature
description: >
  Use WHEN starting any non-trivial change, feature, or ticket — before writing any code.
  Triggers on: "build", "add", "implement", "let's plan", ticket link, Jira URL, "I want to".
when_to_use: Use before writing any code for a non-trivial change — turns a one-line ask into a reviewed, bite-sized plan.
when_not_to_use: Trivial typo fixes, doc-only edits, one-line config changes where the intent is unambiguous.
inputs: [feature request or ticket, docs/contexts/<latest>.md, .claude/project-rules.md]
read_first: [docs/contexts/<latest>.md, files most likely affected per context, docs/contexts/architecture/README.md if present, docs/decisions/design-watches.md (active watches), docs/decisions/<current YYYY-MM>.md if present]
outputs: docs/plans/<slug>.md
hard_stops: [auth, billing, PII, secrets, destructive ops, cross-team contracts, missing context.md]
---

# plan-feature

> Turn a one-line ask into a reviewable plan. No code without a plan.

## Goal
Take a feature request and produce a plan a human can approve *before* any code is written.

<HARD-GATE>
Do NOT write code, scaffold, or implement anything until you have presented a design and the user has approved it. This applies to every request regardless of perceived simplicity.
</HARD-GATE>

## Phase 1: Brainstorm (explore intent first)

Before writing the plan, understand what you are building.

**Note:** If the ask is exploratory (unclear scope, competing approaches not yet evaluated, or the question is "what should we build?"), run `core/brainstorm` first — it produces `docs/specs/<slug>.md` which you read at step 1 here. Use `plan-feature` directly when you know what to build and need a plan.

1. **Check context.** Read `docs/contexts/<latest>.md`. If it doesn't exist, run `core/project-context` first. If `docs/specs/<slug>.md` exists for this ask, read it — it replaces the clarifying question phase.
1a. **Alignment audit.** Read the active watches in `docs/decisions/design-watches.md`, the architecture doc (`docs/contexts/architecture/README.md`), and the current-month decision log. Then:
   - For each active design-watch whose *applies-when* matches this ask, the plan MUST honour it — carry it into the relevant slice or hard rule.
   - If this ask **contradicts** a recorded decision or the architecture doc, do NOT silently proceed and do NOT silently "update" the higher tier. **Surface the drift:** name the source (ADR date / architecture section), quote its stated position, describe the divergence, and propose both reconciliation directions — (a) change the plan to comply, or (b) supersede the prior decision with a new `record-decision` entry. Let the engineer choose.
2. **Restate the ask.** In your own words, one paragraph. Flag every ambiguity.
3. **Ask clarifying questions.** One question at a time. Prefer multiple-choice when possible.
   - Focus on: purpose, constraints, success criteria, who else is affected.
4. **Name what this plan is NOT doing.** Before proposing approaches, explicitly list 3+ things this plan will not do and why. Scope boundary first — approaches second.
   - Weak: "we'll keep it simple" — Strong: "this plan does NOT add role-based filtering, does NOT touch the billing module, does NOT change the API surface"
5. **Surface the hard rules.** State at least one `MUST NEVER` and one `MUST ALWAYS` constraint for this feature. Principles are not constraints. If you can't name a constraint, the scope is not understood.
   - Weak: "should be intuitive" — Strong: "MUST NEVER write to the auth table directly; MUST ALWAYS validate input at the service boundary"
6. **Security gate (conditional).** Does this plan touch auth, billing, PII, public-facing endpoints, or external inputs?
   - YES → add a `## security-requirements` section to the plan (not a post-hoc review — pre-implementation requirements). State: who can call this, what inputs are trusted, what data must not leave the system, how it fails safely. Tag the plan: `REQUIRES: security-review after implementation`.
   - NO → proceed.
7. **Propose 2-3 approaches** with trade-offs and your recommendation.
8. **Get approval** on the chosen direction before writing the plan document.

Anti-pattern — *"This is too simple to need a design":* Every request goes through this. A design can be three sentences. Skipping it is how unexamined assumptions cause rework.

## Phase 2: Write the Plan

6. List affected files, contracts, data shapes, and third parties.
7. Break the chosen path into 1-N slices. One acceptance criterion per slice.
8. Write acceptance criteria as test names: `should_<verb>_<noun>`.
9. List risks with mitigations (or explicit "accepted").
10. List open questions that block implementation.
11. **Self-review the plan before presenting it** (4-point, mirrors `brainstorm`):
    - **Scope** — focused enough for one plan? If it spans independent subsystems, decompose.
    - **Consistency** — do any sections contradict each other?
    - **Alignment** — does it pass the step 1a audit (no unsurfaced drift, all matching watches honoured)?
    - **Verification** — does every slice have a named acceptance test, and is "how we'll know it works" concrete?
    Fix what fails *before* showing the engineer.
    > Iteration is normal. A plan touching multiple existing surfaces should expect several review rounds — the architectural problems surface in rounds 2-3, not round 1. Do not rush to "ship it" to save time.
12. Write `docs/plans/<slug>.md` per the output schema.
13. **Do NOT include code in the plan.** The plan describes *what*; `implement-slice` handles *how*.

## Gates
- Plan contains no code (pseudo-code also not allowed)
- "What this plan is NOT" section names at least 3 explicit out-of-scope items
- "Hard rules" section has at least one MUST NEVER and one MUST ALWAYS — not soft principles
- If plan touches auth/billing/PII/public endpoints → security-requirements section present with REQUIRES tag
- Every slice has exactly one named acceptance test
- Every risk has a mitigation or is explicitly accepted
- Open questions section is present (even if empty, state "none")
- **`docs/plans/<slug>.md` is written to disk.** Not complete until the file exists — a chat summary does not count. (The plan-gate hook reads this file to unblock source edits.)

## Stop When
- The ask is ambiguous and a guess would mislead the team → ask first
- The change crosses team boundaries without sign-off → ping the other team
- The work touches a no-go zone from `project-rules.md`
- Auth, billing, PII, or secrets are involved → escalate before planning

## Execution Handoff (after plan is written and approved)

After saving `docs/plans/<slug>.md`, offer two execution paths:

> "Plan saved to `docs/plans/<slug>.md`. Two ways to execute:
>
> **1. Subagent-driven (recommended for multi-task plans)**
> Creates an isolated git worktree, dispatches a fresh implementer subagent per task,
> two-stage review gate between tasks, human checkpoint every 3 tasks.
> Invoke: `workflow/using-git-worktrees` → `workflow/subagent-driven-development`
>
> **2. Inline execution**
> Work through slices in this session using `core/implement-slice` → `core/test-change` → `core/review-change`.
> Good for single-slice plans or when you want to stay in the current session.
>
> Which approach?"

Await human choice. Then invoke the appropriate next skill.

## Output Schema → `docs/plans/<slug>.md`

```markdown
# plan · <slug> · <date>

## goal
<one paragraph>

## what this plan is NOT doing
- <thing> — <why explicitly out of scope>
- <thing> — <why explicitly out of scope>
- <thing> — <why explicitly out of scope>

## hard rules
- MUST NEVER: <specific constraint, not a soft principle>
- MUST ALWAYS: <specific constraint, not a soft principle>

## scope
- <file path or area> · <what changes there>

## affected contracts
- API: <route> · <breaking? Y/N>
- event: <name> · <breaking? Y/N>

## implementation paths considered
- A: <name> — <tradeoff in one sentence>
- B: <name> — <tradeoff in one sentence>

## chosen path
<A or B>, because <2 sentences>.

## slices
- A1 · should_<verb>_<noun> — <one-line outcome>
- A2 · should_<verb>_<noun> — <one-line outcome>

## risks
- <risk> → <mitigation or "accepted">

## open questions
1. <numbered question that blocks implementation — or state "none">
```
