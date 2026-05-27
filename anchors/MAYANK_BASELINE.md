# Mayank — v1.1 Baseline Reference

This file documents the Mayank submission's baseline before and after the
v1.1 Shortlist-Generator reframing. It is the canonical reference for
regression testing the rubric scorer changes (deterministic `evidence_kind`,
`judge_review_items` routing, snapshot cache, cost ceilings).

## v1.0 (pre-reframing) baseline

Run at `2026-05-26T05:48:27Z` (the final v1.0-fixes pass before this
reframing). The total below was produced by Mayank's actual submission
artifacts (repo + free-form notes; no live URL, deck, or video) running
through the pre-v1.1 pipeline.

| Dimension                | raw  | weighted | evidence_kind | notes                                |
| ------------------------ | ---- | -------- | ------------- | ------------------------------------ |
| problem_clarity          | 7.5  | 7.5      | stated        | OK                                   |
| solution_depth           | 6.0  | 15.0     | inferred      | OK                                   |
| ai_sophistication        | 3.0  | 6.0      | inferred      | OK; flagged thin-wrapper             |
| functional_correctness   | 5.5  | 13.75    | **verified**  | **wrong — browser was skipped**      |
| ux_polish                | null | null     | insufficient  | OK                                   |
| communication            | 6.5  | 6.5      | stated        | OK                                   |
| **TOTAL**                |      | **54.17 / 90 evaluable weight, normalised** |||

Verdict (computed under v1.1 thresholds): **borderline** (40 ≤ 54.17 < 65).

## v1.1 expected baseline

Two structural changes are applied to the same artifacts:

1. **Deterministic `evidence_kind` clamping** (`agents/rubric_scorer.py`):
   - `functional_correctness` was mislabelled `verified` by the v1.0 LLM
     even though the browser verifier was skipped. v1.1 clamps this to
     `inferred` (browser had no successful journey, but the repo + cross-
     check provided indirect signal). The numeric score is unchanged.
   - All other dimensions stayed at-or-below their v1.1 ceilings already.
2. **Custom-integration descope** (`prompts/rubric_scorer.md`,
   `prompts/cross_check.md`): claims like Mayank's "Slack slash-command
   flow" now route to `judge_review_items` instead of dragging the
   functional score down. Expected effect: functional_correctness ticks
   up by 0–1.0 point (5.5 → ~5.5–6.5).

**Predicted v1.1 total: 54–58.** Total stays close to v1.0 because the
mislabelled `verified` had no numeric impact; the only mover is the
descope rule which mildly *raises* the score.

## How to refresh this baseline

After upgrading to v1.1, the operator runs:

```bash
autojudge doctor                                  # confirms env + Chromium + token
autojudge run 20260525-040054-mayank-singh-tomar  # ~3-5 min with snapshot cache cold
autojudge inspect 20260525-040054-mayank-singh-tomar
```

Then updates the "v1.1 actual" line below with the observed total.

| Run date | Total  | Verdict     | Notes                              |
| -------- | ------ | ----------- | ---------------------------------- |
| (v1.0)   | 54.17  | borderline  | Pre-reframing baseline             |
| (v1.1)   | _TBD_  | _TBD_       | First run after Shortlist reframe  |

## What changes in the trace store

- `totals.verdict` populated (v1.0 rows had `NULL`; the migration default
  back-fills `borderline` for legacy rows — v1.1 *runs* compute it from
  total + evaluable_weight).
- `totals.judge_review_items_json` populated with credential-walled claims
  the scorer or cross-check flagged.
- `verifier_runs` adds a synthetic `repo_snapshot` row recording the
  tarball SHA + size for audit.
- `scores.evidence_kind` reflects the deterministic ceiling, not the
  LLM-proposed kind.
- `totals.integrity_flags_json` may include `cost_ceiling: ...` entries
  if any agent exceeded its per-submission LLM-call budget.
