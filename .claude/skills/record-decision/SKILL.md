---
name: record-decision
description: >
  Use WHEN a non-obvious architectural, design, or engineering decision is made during a session —
  to capture the reasoning before it's lost. Append-only.
  Triggers on: "record this decision", "let me capture why", "we decided to", "ADR",
  "architecture decision", "why did we choose X", "document this choice".
when_to_use: Use at any point in a session — during brainstorm, implementation, or review — when a decision is made that future engineers should understand, not just see.
when_not_to_use: Trivial decisions with obvious rationale. Decisions already captured in a plan or review artifact.
inputs: [the decision just made, the context that prompted it, alternatives that were considered]
read_first: [docs/decisions/YYYY-MM.md if it exists (for context; don't repeat an existing entry)]
outputs: appends one entry to docs/decisions/YYYY-MM.md
hard_stops: [never edit past entries — append only, never delete]
---

# record-decision

> Capture the WHY before it's lost. One entry, one decision, append-only.

## Goal
Append a single decision entry to `docs/decisions/YYYY-MM.md`. The decision log is the answer to "why is this code the way it is?" — the artifact that prevents juniors from re-making wrong choices and seniors from re-debating settled questions.

## When decisions deserve capturing

**Capture when:**
- The decision is non-obvious — a future developer could reasonably choose differently
- Alternatives were considered and rejected (and the rejection reasons matter)
- The decision has architectural implications (affects module structure, data flow, contracts, patterns)
- A security, performance, or reliability tradeoff was made
- A `project-rules.md` no-go zone was established or revised

**Don't capture:**
- "We used the standard library function for this" — obvious
- "We named the variable X" — trivial
- Anything already fully documented in the plan or review artifacts

## Steps

1. **Identify the decision.** One sentence: "We decided to [X] rather than [Y]."
2. **State the context.** Why did this question come up? What was the prompt?
3. **List rejected alternatives.** Name each one and the reason it was rejected. Specifics only — "Y was too complex" is weak; "Y would require crossing the no-go zone in auth/" is workable.
4. **State affected areas.** Which files, modules, or contracts does this decision touch?
5. **Tag it.** One or more of: `architecture`, `security`, `contract`, `pattern`, `performance`, `tooling`.
6. **Check for duplicates.** If `docs/decisions/YYYY-MM.md` exists, skim the last 5 entries. If this decision is already captured — don't add a duplicate. You can add a "see also" to an existing entry.
7. **Append.** Write the entry at the bottom of the current month's file. Never edit past entries.
8. **Run the lesson router.** Every captured decision is screened for "is this also an always-on gate?" Walk the four questions (full text in `docs/decisions/README.md`):
   1. **Linter/CI/type-checker can enforce it?** → don't write prose; recommend the mechanical gate. Done.
   2. **The skill/process itself is wrong (would misfire in any repo)?** → recommend `improvement-plan`. Done.
   3. **Just rationale worth re-reading?** → the ADR you just wrote is enough. Done. *(Most decisions stop here.)*
   4. **Must gate every future plan/review *in this repo*, judgment-only, repo-specific?** → **also append a design-watch** to `docs/decisions/design-watches.md` (next step).

## Routing to a design-watch (only when router Q4 is YES)

1. **Cap check first.** Count active watches in `design-watches.md`. If at ~10-12, you may NOT add a 13th — first retire one whose *retire-when* condition is met, or promote one to a mechanical gate. Surface this to the engineer; do not silently exceed the cap.
2. **Number it.** Next `DW-NN`.
3. **Name the retire-when.** A watch with no retirement condition is a permanent tax — refuse to add one. State the structural fix or CI gate that would make this watch redundant.
4. **Cross-reference the ADR** you just wrote.
5. **Append** to the active section of `design-watches.md` per the schema below.

### Design-watch schema → appends to `docs/decisions/design-watches.md`

```markdown
### DW-<NN> · <one-line rule>
- **Rule:** <what to verify before approving a plan/diff>
- **Applies when:** <trigger — "plan touches X" / "diff changes Y">
- **Why:** <incident — PR/date + what it cost> (→ ADR <YYYY-MM-DD>)
- **Not mechanical because:** <why a linter/CI can't catch this>
- **Retire when:** <the structural fix or CI gate that subsumes this watch>
- **Status:** active
```

## Output schema → appends to `docs/decisions/YYYY-MM.md`

```markdown
## YYYY-MM-DD — <decision title, one sentence>

**Decision:** <what was decided>

**Context:** <what prompted this — the problem or question that made this decision necessary>

**Alternatives rejected:**
- <alt 1> — <why rejected>
- <alt 2> — <why rejected>

**Affected areas:** <file paths, module names, or contract names>

**Tags:** `architecture` / `security` / `contract` / `pattern` / `performance` / `tooling`
```

## Bootstrapping the decision log

If `docs/decisions/` doesn't exist, create it with the `README.md` that documents both
stores and the lesson router (see the shipped `docs/decisions/README.md` for the canonical
content), plus an empty `design-watches.md`. Then create the first month file
`docs/decisions/YYYY-MM.md` and append.

```bash
grep -r "Tags:.*security" docs/decisions/     # find all security decisions
grep -rn "Status: active" docs/decisions/design-watches.md  # list active watches
```

## Rules

- **Append-only.** Past entries are audit trail. Never edit. If a past decision is superseded — add a new entry referencing the old one.
- **One entry per decision.** Don't bundle multiple decisions into one entry.
- **The user owns the words.** The AI drafts the entry; the engineer confirms the wording is accurate before saving.
- **project-context reads this.** The most recent month's decision log is read by `project-context` as a "read first" source. Accurate entries improve session quality for the whole team.
