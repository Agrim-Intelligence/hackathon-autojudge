---
name: getting-started
description: Use when starting any session — establishes how to find and use Agrim skills, requiring skill invocation before ANY action including clarifying questions
---

<EXTREMELY_IMPORTANT>
You have Agrim skills. They encode how Agrim engineers work — the plays, the discipline, the hard stops. Using them is not optional.

IF A SKILL EXISTS FOR WHAT YOU ARE ABOUT TO DO, YOU MUST USE IT.
This is not a suggestion. You do not get to decide it does not apply.
</EXTREMELY_IMPORTANT>

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill. Your task definition is your instruction set.
</SUBAGENT-STOP>

## The Three Rules

**1. You have skills.** They are listed in the Skill tool. Each is a proven play for a recurring engineering situation.

**2. Before any non-trivial action, invoke the relevant skill.** Check the Skill tool list. If a skill matches — even a 1% chance — invoke it before doing anything else, including asking clarifying questions.

**3. If no skill applies and the task is non-trivial, hand back.** Name what is confusing. Ask. Ambiguity costs more than rework.

## Hard Stops — You Must Hand Back Before:

- **Destructive operations.** `DELETE`, `DROP`, `TRUNCATE`, `rm -rf`, force-pushes to shared branches.
- **Auth / billing / data of consequence.** Identity, permissions, payment paths, PII-bearing tables. Even "just a one-liner".
- **Secrets and environment.** API keys, env vars, third-party tokens, anything in `.env`. Never echo. Never commit.
- **Cross-team contracts.** Public APIs, event shapes, exported types anything another team consumes.
- **Anything not covered by the active skill's `stop_when`.** When in doubt: stop.

## The Session Loop

| Step | Skill | Artifact | When |
|---|---|---|---|
| 0 | `brainstorm` | `docs/specs/<slug>.md` | Ask is exploratory |
| 1 | `project-context` | `docs/contexts/<slug>.md` | Every session |
| 2 | `plan-feature` | `docs/plans/<slug>.md` | Before any non-trivial code |
| 3 | `implement-slice` | `implementation_notes.md` | One slice at a time |
| 3a | `verification-before-completion` | appended to notes | Before dispatching reviewer |
| 4 | `test-change` | `test_report.md` | After every slice |
| 5 | `review-change` | `review.md` | After tests pass |
| 5a | `receiving-code-review` | updated `review.md` | When review has findings |

Risk: `debug-issue` · `security-review` · `contract-check` · `migration-check`  
Delivery: `release-check` · `work-summary` · `improvement-plan` · `maintain-context`  
Multi-task: `using-git-worktrees` → `subagent-driven-development` → `finishing-a-development-branch`

## Red Flags — You Are Rationalizing. Stop.

| Thought | Reality |
|---|---|
| "This is simple, no skill needed" | Check anyway. Simple things become complex. |
| "I need more context first" | Skill check comes BEFORE clarifying questions. |
| "This doesn't feel like a plan-feature situation" | If you are about to write code without a plan, it is. |
| "I remember this skill" | Skills evolve. Invoke the current version from the Skill tool. |

## Skill Priority

1. **Process skills first** (`plan-feature`, `debug-issue`) — determine HOW to approach
2. **Implementation skills second** (`implement-slice`, `test-change`) — guide execution

## Artifacts Live on Disk

A skill is NOT complete until its artifact exists on disk. Writing the summary in chat does not count. `project-context` → `docs/contexts/<slug>.md`. `plan-feature` → `docs/plans/<slug>.md`. `test-change` → `test_report.md`. No file, not done.

## The Gates Are Real

Hooks enforce this loop mechanically, not just by request:
- The **plan-gate** denies edits to source files when no current plan exists.
- The **Stop-gate** refuses to let you finish when source changed without a plan or `test_report.md`.
If a gate blocks you, the fix is to run the missing skill — not to find a way around it.

## Explicit Override Only

Skills are guardrails, not cages — but "the engineer wants speed" is NOT an override. An override is the engineer *explicitly* saying "skip step X" or "edit directly." Its mechanical form is the `.claude/.allow-direct-edits` sentinel. Assumed urgency, your own judgement that a step is unnecessary, or a desire to close the task faster are NOT overrides. When unsure whether you have one: you do not. Ask.
