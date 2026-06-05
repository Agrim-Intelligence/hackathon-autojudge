---
name: receiving-code-review
description: >
  Use WHEN review.md has come back with findings and you need to respond to them systematically.
  Triggers on: "review came back", "fix review findings", "respond to review", "address feedback",
  "review feedback", "code review response", after review-change produces review.md with open items.
when_to_use: Use after review-change or code-reviewer returns findings — before marking the task done.
when_not_to_use: review.md says "Ready: Yes" with no open findings — no response needed.
inputs: [review.md with findings, implementation_notes.md, the diff under review]
read_first: [review.md, docs/plans/<slug>.md (to verify findings against the plan)]
outputs: updated review.md (findings dispositioned) + code fixes committed
hard_stops: [never close out with unfixed Critical findings, never mark done while Important findings are silently unaddressed]
---

# receiving-code-review

> Fix Critical first. Disposition everything. Push back with evidence — not avoidance.

## Goal
Respond to every finding in `review.md` with a specific action (fix, defer with reason, or dispute with evidence). No silent skips. No vague "addressed" without specifics.

## Steps

**1. Triage — read all findings before touching anything.**
List by severity: Critical → Important → Minor. Count them. Name them. Don't start fixing until you know what you're dealing with.

**2. Fix ALL Critical findings before anything else.**
- Fix one at a time. Run the full test suite after each fix.
- If a Critical finding would require changing the plan scope → stop. Surface to human before fixing.
- Commit each Critical fix separately with a clear message: `fix: <finding-id> — <what changed>`

**3. For each Important finding — fix or explicitly defer.**
- Fix: same as Critical (commit + test).
- Defer: write the reason in `implementation_notes.md` open questions. "It was too hard" is not a reason. "Requires changing the contract with service X — flagged in contract-check for next PR" is.
- No silent skips. Every Important needs a disposition.

**4. For each Minor finding — decide.**
- Fix: do it.
- Log as tech debt: run `core/record-decision` — tag `pattern` or `architecture`, note the tradeoff.
- Accept: state the reasoning in your review response.

**5. Push back when the reviewer is wrong.**
Do not accept incorrect feedback to close the loop. Push back requires:
- The specific claim that's wrong (file:line)
- The evidence you're relying on (test name, spec reference, contract definition)
- A clear "this is correct because X" — not "I think it's fine"

If the dispute can't be resolved in one exchange → escalate to human.

**6. Update `review.md` with disposition on every finding.**

For each finding, add a disposition line:
```
[S1] severity:critical — fixed at commit abc1234 — test: should_reject_unauthenticated_calls
[S2] severity:important — deferred: requires contract-check with billing-service (see implementation_notes.md open Q3)
[S3] severity:minor — accepted: the duplication is intentional — isolated module that must not share state
[S4] severity:minor — disputed: the test DOES verify real behaviour — see test/auth.test.ts:L45 which mocks the network, not the handler
```

**7. Re-run review if Critical findings were present.**
After fixing all Critical and Important items → invoke `core/review-change` again. A clean re-review is the signal that the work is ready.

## Gates
- Every Critical finding is either fixed (with commit SHA) or escalated
- Every Important finding has a disposition (fixed or deferred with reason)
- review.md is updated with disposition lines for every finding
- If Critical findings were present → re-review run and clean

## Stop When
- A Critical finding would require scope change or contract change → stop, surface to human
- Disputed findings can't be resolved → escalate to human, don't unilaterally close

## Red Flags

| Thought | Reality |
|---|---|
| "I addressed it" (no specifics) | Disposition requires: what changed, where, how tested |
| "The reviewer doesn't understand the code" | Explain it. If they still disagree, escalate |
| "Minor findings don't need a response" | They need a decision, not necessarily a fix |
| "I'll fix it in the next PR" | That's a deferral — write the reason explicitly |
