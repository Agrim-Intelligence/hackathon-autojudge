---
name: work-summary
description: >
  Use WHEN a PR or feature is complete — produces the artifact a manager reads and future-you will thank you for.
  Triggers on: "end of PR", "summarise the work", "work summary", "what did we ship", "close out".
when_to_use: Use at end-of-PR (or end-of-day for long work) to produce a 60-second-readable summary of what changed, why, and what is next.
when_not_to_use: Work is not complete yet. Use work-in-progress notes instead.
inputs: [plan, implementation_notes.md, test_report.md, review.md, release_check.md if shipped]
read_first: [all the above artifacts for this slug]
outputs: docs/summaries/<slug>.md
hard_stops: [known issue or partial work → name it loudly, surprise invalidates the plan → flag before summarising]
---

# work-summary

> The artifact your manager actually reads. The trail future-you will thank you for.

## Goal
At end-of-PR, summarise what changed, why, what did not ship, and what is next — readable in 60 seconds by a non-author.

## Steps
1. State what was actually accomplished vs what the plan said. Be honest about delta.
2. List the artifacts produced (with links/paths).
3. List what was *not* done — explicitly, with a reason for each item.
4. List the surprises — things learned that weren't in the plan.
5. State what is next: next slice, open question owner, follow-up ticket.

## Gates
- Readable in under 60 seconds
- Every "not done" item has a reason
- "What is next" is actionable (a ticket, a name, a question) not aspirational
- References file paths, not just commit hashes

## Stop When
- You would be hiding a known issue or partial work → name it loudly before summarising
- A surprise from this work invalidates the plan → flag the invalidation first, then summarise

## Output Schema → `docs/summaries/<slug>.md`

```markdown
# summary · <slug> · <date>

## what shipped
<one paragraph>

## artifacts
- plan: docs/plans/<slug>.md
- implementation: <PR link or branch>
- review: review.md
- release: release_check.md (if applicable)

## what did NOT ship (and why)
- <thing> — <reason: punted / blocked / out-of-scope>

## surprises
- <thing learned> — <implication for next slice or skill>

## what is next
- <next slice / follow-up ticket / open question with owner>
```
