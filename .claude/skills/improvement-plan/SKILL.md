---
name: improvement-plan
description: >
  Use WHEN a lesson has repeated twice — to update a skill file so the system gets smarter instead of repeating the same correction.
  Triggers on: "fix the skill", "improvement plan", "lesson repeats", "skill update", "update SKILL.md", "this keeps happening".
when_to_use: Use when the same model behaviour correction has been needed twice in one week. Produces a PR-ready skill diff.
when_not_to_use: First time a lesson comes up. Use only on the second occurrence — once is an incident, twice is a pattern.
inputs: [the skill file to change, 2+ concrete examples of where it failed or under-served]
read_first: [the current skill file, relevant Slack/PR threads, prior improvement-plans on the same skill]
outputs: docs/improvements/<skill>-<date>.md
hard_stops: [proposal would weaken a stop_when or hard stop → escalate instead, proposal is really a new skill → open a separate doc]
---

# improvement-plan

> When a lesson repeats twice, it is a skill update. This is how the system gets smarter.

## Goal
Produce a PR-ready proposal to update one skill file in `.claude/skills/` based on observed friction — so the lesson is encoded, not re-taught.

## Steps
1. Name the skill and the observed problem in one paragraph.
2. Provide 2+ concrete examples (links, file refs, or repro descriptions).
3. State the proposed change: exact lines added / removed / edited. Show a diff.
4. State what NOT to change, and why — especially any hard stops or stop_when clauses.
5. State the expected impact: which behaviour in the skill changes after the update.
6. State how we will know the change worked: which metric, behaviour, or time window.
7. Link any prior improvement-plans on the same skill.

## Gates
- Proposal covers one PR, one skill
- The diff is shown (not just described)
- "How we will know it worked" is concrete, not vibes
- Prior improvement-plans on the same skill are linked

## Stop When
- The proposal would weaken a `stop_when` clause or hard stop → escalate to skills lead instead
- The proposal is really a new skill, not an edit → open a separate doc, do not embed it here

## Output Schema → `docs/improvements/<skill>-<date>.md`

```markdown
# improvement · <skill> · <date>

## observed problem
<one paragraph>

## examples
- <link / file:line> — <what happened>
- <link / file:line> — <what happened>

## proposed change
```diff
- <old line>
+ <new line>
```

## what NOT to change
- <thing> — <why>

## expected impact
<which step in the skill behaves differently after this change>

## how we will know it worked
<metric / behaviour / time window>

## prior improvements on this skill
- <link or "none">
```
