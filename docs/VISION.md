# AutoJudge — Vision

## What it is

Agrim AutoJudge ranks hackathon submissions by examining their **public surface** — the repo,
the live deployment, the deck, the demo video — and hands a few human judges a ranked, evidence-
backed shortlist. It is built to scale to an all-India hackathon where submissions are many and
varied (web apps, APIs, CLIs, notebooks, ML models, mobile, hardware) while the judging panel is
small.

AutoJudge is a **recommendation engine, not a verdict authority**. It does the legwork —
gathering evidence, grading dimensions, flagging integrity concerns — so humans spend their
scarce attention on real judgment calls, not triage.

## Who it serves

- **Judges** — get a single board they can filter, scan, and shortlist from, with the evidence
  for every score one glance away. They make the final call; AutoJudge makes it fast.
- **Candidates** — get a fair, consistent evaluation regardless of project type, and are never
  penalised for things the machine simply couldn't verify.
- **Organisers** — get throughput, an audit trail, and resistance to gaming.

## Principles (the system must not violate these)

1. **Evidence-graded, never fabricated.** Every dimension score carries an evidence kind —
   `verified` > `inferred` > `stated` > `insufficient`. A score may only claim `verified` when a
   verifier actually observed it. The browser/API verifiers may **never** report a functional
   success they did not ground in real page/endpoint evidence. A plausible-but-unobserved success
   is a bug, not a nicety.
2. **Route-to-judge, don't penalise.** When the machine cannot verify something (credential-walled
   app, a project type with no automated path, a claim needing human eyes), that dimension is
   marked `insufficient` and routed to `judge_review_items` with a **legible reason** — it does
   not silently drag the score down. Missing evidence is a gap for a human to close, not a verdict.
3. **Fairness across project types.** A research notebook and a polished web product are scored on
   different yardsticks (archetype- and app-type-aware weights), so neither is unfairly measured
   against the other's strengths.
4. **Anti-gaming is first-class.** Candidates have a prize incentive to manipulate. All untrusted
   inputs (README, deck, transcript, live-page text, the submission body) are sanitised before any
   reasoning model sees them; the guard fails **secure** (withholds untrusted text on failure, not
   open); clear cheats — sophisticated prompt injection, fabricated timelines — are auto-
   `quarantined`, not quietly scored.
5. **Humans decide winners.** AutoJudge ranks and recommends. Finalist/winner selection is a human
   action, captured with an audit trail. The auto-verdict is always preserved alongside any human
   override.
6. **Legibility over cleverness.** A judge should understand *why* a submission landed where it did
   without reading code. Reasons, flags, and evidence are surfaced in plain language.

## What it deliberately is not

- Not an arbitrary-code execution sandbox. AutoJudge verifies via safe HTTP probing and static
  inspection; it does not run untrusted candidate code.
- Not the final judge. It cannot disqualify or crown — only recommend and flag.
- Not a plagiarism detector or a multilingual platform (today). Those are explicit non-goals for
  the current rollout.

See `docs/ARCHITECTURE.md` for how these principles are realised, and the repo-root `CLAUDE.md`
for the operating rules that keep them true.
