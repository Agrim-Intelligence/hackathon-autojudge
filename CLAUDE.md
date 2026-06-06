# AutoJudge — Project Rules

Operating rules for this repo. Read `docs/VISION.md` (principles) and `docs/ARCHITECTURE.md`
(how it works) first. These rules are binding; they encode decisions that protect fairness,
integrity, and the production deployment.

## What this is
Agrim AutoJudge: an evidence-graded ranker for hackathon submissions that hands judges a
shortlist. Python pipeline + two Streamlit services (dashboard, intake) + Postgres on Railway.

## Core invariants — do not break

### Scoring integrity
- **Never let a verifier report an ungrounded success.** Browser/API journeys count as `success`
  only with real page/endpoint evidence. Removing the grounding check is a regression.
- **Evidence kinds are a ceiling, not a suggestion.** A dimension reaches `verified` only when a
  verifier observed it (`functional_evidence = browser_ok or api_ok`; UX is browser-only). Don't
  let the LLM scorer claim above what the pipeline saw.
- **Unverifiable ⇒ route to judge, never penalise.** Mark `insufficient` + add a legible
  `judge_review_items` reason. This applies to credential-walled apps and non-web app types.
- **Verdict taxonomy**: `insufficient` (evaluable_weight < 50) · `below_threshold` (<40) ·
  `borderline` (40–65) · `shortlist` (≥65) · `quarantined` (integrity). Thresholds live in
  `rubric_scorer.py`; don't change them without re-running anchors.

### Anti-cheat (treat as security)
- **Sanitise every untrusted channel** before any reasoning model sees it: submission body,
  README, deck text, video transcript, live-page text. Adding a new untrusted input means adding
  a `sanitize()` call.
- **Guard fails secure.** On guard-LLM failure, withhold the text (quarantine placeholder, raised
  severity) — never pass raw candidate text through.
- **Auto-quarantine clear cheats.** Sophisticated prompt injection (severity ≥3) and timeline
  cheats (zero in-window commits + future-dated history) set `verdict = quarantined`. Enforcement
  is the last step before persist and must not be overwritten.
- **No execution of untrusted code.** The API prober calls **only candidate-declared endpoints**
  (GET/HEAD, or POST with a declared body); no other verbs, no link-following, hard timeouts +
  request caps. There is no sandbox — do not add code execution without an explicit security plan.

### Human decisions are sticky
- `record_total` must exclude human columns (`verdict_override`, `judge_notes`, `shortlist_state`,
  `finalized_by/at`) from its `ON CONFLICT DO UPDATE`. Re-scoring must never erase a judge's
  override or finalist pick.

### Intake field contract
- **Email is outreach metadata**, not a pipeline signal. It is intentionally collected for
  post-event communication. Never feed it to a reasoning agent or surface it on the judge
  dashboard. Its presence in the schema is deliberate — do not "clean it up" as dead.
- **CLI command / Notebook path are app-type classification hints**, not execution inputs. No
  verifier runs candidate code from these fields. UI labels must say so.
- **All candidate-authored text is sanitised before any reasoning LLM sees it** — submission
  body, README, deck, transcript, live-page text, **and declared journey steps + expected
  outcomes**. Declared journeys go through `guard.sanitize()` twice: at intake (before store)
  and at `browser_verifier` prompt construction for `source="stated"` journeys. Adding a new
  candidate-controlled text channel means adding a `sanitize()` call.
- **`submissions.deck_path`** is a transient local-FS reference written by the intake service.
  The canonical artifact is the blob in `submission_blobs`; the orchestrator re-materialises from
  it. Never rely on `deck_path` for a cross-service read.

## Calibration & CI
- Anchors (`rubric/anchors.py`) are markdown fixtures; their scores drift with model behaviour.
  When `anchor-smoke` fails on drift beyond `MAX_DRIFT`, **recalibrate `expected_total` to the
  observed centre with evidence in the commit message** — do not widen `MAX_DRIFT` to mask it, and
  do not recalibrate to hide a genuine code regression (confirm the drift is model-side first).
- The verification gate before any merge: `autojudge run-anchors` within tolerance, plus the
  change-specific checks. There is no unit-test suite or `ruff` configured — rely on anchors,
  import/AST checks, and targeted inline smoke tests.

## Git & deploy
- **Deploy = merge to `main`.** Railway auto-deploys `main` via its GitHub integration; there is no
  separate deploy step. Treat merging to `main` as shipping to production.
- Work identity: **`CGupta-agrim`**, remote `git@github-work:Agrim-Intelligence/hackathon-autojudge`.
  Use `gh auth switch --user CGupta-agrim` for org operations.
- Branch for changes; open a PR; let `anchor-smoke` pass before merge. Don't push to `main`
  directly.
- **Never commit secrets or `.env`.** API keys and `DATABASE_URL` live in Railway env / GitHub
  secrets only. Never print full secret values to logs.
- Production Postgres reads are fine for investigation; **writes to prod data and `railway ssh`
  into a prod container require explicit, per-action user authorization.**

## Conventions
- Edit existing files over adding new ones; no comments explaining *what*, only *why* when
  non-obvious; no defensive code for impossible internal cases; no backwards-compat shims when the
  code can just change.
- Keep the SQLite and Postgres backends at parity — a change to one is a change to both.
- Both Streamlit services run from one image dispatched by `AUTOJUDGE_ROLE`; a change to startup
  must work for `dashboard` and `intake`.

## Out of scope (explicit non-goals, this rollout)
Sandboxed code execution; automated mobile/hardware testing; multilingual intake/scoring;
per-category prize tracks; cross-submission plagiarism; a job queue (not needed at current scale).
