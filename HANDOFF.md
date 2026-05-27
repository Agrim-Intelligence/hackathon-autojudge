# Agrim AutoJudge — Internal Pilot Handoff

Welcome to the MVP. This page is the single source of truth for the 3-5
internal judges. If anything is unclear, ping `@chetan` on Slack.

## Live URLs

| Surface | URL | Auth |
| --- | --- | --- |
| Judges dashboard | https://TODO-dashboard.up.railway.app | Basic auth, creds below |
| Candidate intake | https://TODO-intake.up.railway.app | Basic auth (or open during hackathon window) |
| Worker healthz | https://TODO-worker.up.railway.app/healthz | No auth (status only) |

> Fill these in once Railway issues the public domains. Replace the
> `TODO-*` host with the actual `*.up.railway.app` name from Railway →
> Service → Settings → Networking.

## Credentials

The basic-auth credentials live in **1Password → Engineering → Agrim
AutoJudge MVP**. If you need them re-issued, ask `@chetan`.

The shared username flows into the override audit trail (`overridden_by`
column on `totals`). Until Cloudflare Access is wired up in Phase 2, we
identify a specific judge from out-of-band context (Slack message,
calendar invite) when reading the audit log.

## What the judges do

1. Open the dashboard URL above.
2. Sign in with the basic-auth credentials.
3. The left rail lists submissions ordered by total score (descending).
   Shortlisted submissions are marked with a `verdict_effective` of
   `shortlist`; auto-judge recommendations are in the `verdict` column.
4. Click a submission to expand. Skim:
   - **Verdict** badge at the top.
   - **Judge review items**: claims the auto-judge couldn't verify
     (credential walls, custom integrations, etc.) that you should
     verify out-of-band before trusting.
   - **Per-dimension scores**: read the `summary` text for the why.
   - **Integrity flags**: if anything is red, the auto-judge thinks the
     submission is suspect.
5. Use the **Override** panel (right side) to:
   - Set your verdict (`shortlist` / `borderline` / `below_threshold` /
     `insufficient`).
   - Optionally change the archetype (e.g. you think this is a
     `dev_tool`, not a `product`).
   - Add a one-line note explaining the override.
   - Choose **Save overrides** (persist without re-running) or
     **Save & re-run** (persist + kick a fresh score using the new
     archetype). **Clear override** wipes your edits.
6. Once you've reviewed all submissions, the top 10 by
   `verdict_effective + total_score` are the shortlist.

## What to file as feedback

Anything that surprised you — UI glitches, scoring weirdness, missed
verification — open a GitHub Issue on
[Agrim-Intelligence/hackathon-autojudge](https://github.com/Agrim-Intelligence/hackathon-autojudge/issues)
with screenshots and the submission ID. We'll triage daily.

Specific bug classes we want you to flag:

- A submission scored "high" but the `judge_review_items` show no real
  evidence behind the score. → over-credit bug, file as
  `severity:high`.
- A submission scored "low" but the live URL clearly works and the repo
  is real. → under-credit bug.
- A submission's verdict_effective doesn't match what you saved (race
  condition?). → file with the full URL and timestamp.

## Operating tips

- Re-runs are slow (~3 min for an average submission). Don't refresh the
  page during one — the trace store handles concurrent writes but the
  Streamlit cache will be confusing.
- The leaderboard is computed at read time, so a re-score immediately
  reflects in the order without a manual refresh of the worker.
- The worker pulls pending submissions every 60 seconds. If a candidate
  submits while you're reviewing, you'll see them appear in the left
  rail within ~3 minutes.

## Known caveats for v1.1

- Anchors run as a calibration set on each batch. After upgrading the
  rubric prompts or models you may see `DRIFT` warnings in `autojudge
  doctor` — that's the recalibration signal, not a regression.
- The `submission_timeout` defaults to 15 minutes per submission. If a
  submission is unusually large or the candidate's deploy is flaky, the
  worker will mark it `FAILED` cleanly rather than hanging the queue.
- Cost ceilings (`AGENT_BUDGETS`) are observational only in v1.1. We
  log overruns to integrity flags but don't kill the run. Watch the
  worker logs if Anthropic costs spike.

## Phase 2 roadmap

What we're explicitly NOT doing in this pilot:

- Cloudflare Access SSO (see DEPLOY.md Appendix A).
- Per-judge attribution.
- PR-gated anchor-smoke CI (the workflow file is in `.github/workflows/`
  but not yet pushed — pending an OAuth token refresh).
- Postgres swap (still on SQLite + a Railway volume).
- Multilingual intake (Hindi / Tamil / Bengali submissions).
- Worker pool (single-worker right now).

See [RUNBOOK.md](RUNBOOK.md) for ops runbook and [DEPLOY.md](DEPLOY.md)
for the deploy walkthrough.
