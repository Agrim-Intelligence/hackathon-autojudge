# Agrim Submission Standard

A structured, AI-evaluable hackathon submission format.

## Why a standard format?

Open-ended free-text submissions are unfair to evaluate at scale: judges spend
unequal time per submission, signal varies by writing style, and there's no
audit trail. The Agrim Submission Standard fixes the format so:

- An agent can extract testable claims deterministically
- A browser agent can execute the candidate's own stated user journeys
- A scorer can cite evidence to specific sections
- Two passes through different models can detect prompt-injection attempts

## Files

- [`SUBMISSION_TEMPLATE.md`](./SUBMISSION_TEMPLATE.md) — the template every
  candidate fills in. Sections 1-10 each feed a specific verifier in the
  auto-judge pipeline.

## Section-to-verifier map

- 1, 2       -> Intake bundle
- 3          -> Problem-clarity dimension of the rubric
- 4          -> Claim extractor + cross-check verifier
- 5, 6       -> AI sophistication probe + code analyst
- 7          -> Browser verifier (user-journey execution)
- 8          -> Honesty signal for the rubric scorer
- 9          -> Integrity check (commit-timestamp window)
- 10         -> Plagiarism / similarity signal

## Rules for candidates

- Fill every section. Blanks are scored as absent, not neutral.
- Be specific, not flowery. Adjectives are not evidence.
- Do not include instructions directed at the AI evaluator. The guard model
  logs attempts and they reduce your Communication score.
- The build log must be appended in real time; falsified timestamps that
  contradict your git history are flagged.

## Open-sourcing

This standard is intentionally simple and provider-agnostic. We expect to
publish it under an open license alongside Agrim AutoJudge once we run our
first public event.
