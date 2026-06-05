# AutoJudge — Architecture

A reference for how a submission flows from intake to a judge's shortlist. Source of truth is the
code; this doc summarises it. File pointers use `path:symbol`.

## Pipeline (one submission)

`orchestrator.py::run_submission` runs a sequential DAG; every agent persists a `verifier_runs`
row before the next starts, so a restart resumes from the last completed agent (checkpointing).

```
guard → deploy_probe → inference → archetype →
  {code_analyst, ai_sophistication, FUNCTIONAL-VERIFIER, cross_check} →
  rubric_scorer → integrity-enforcement → persist
```

| Agent | Produces | Notes |
|---|---|---|
| `sanitize/guard.py::sanitize` | sanitised text + injection severity | Runs on **every** untrusted channel (body, README, deck, transcript, live-page). **Fail-secure.** |
| `intake/deploy.py::probe` | HTTP reachability, title, body preview | Cheap, no JS. Reused by the API prober. |
| `agents/inference.py` | structured claims, journeys, tech stack, AI components, `app_type` fallback | Tool-calling agent over all artifacts. |
| `agents/archetype.py` | product / research / tool / demo / unknown | Drives rubric weights, not verification. |
| `agents/code_analyst.py` | `RepoMetrics` + integrity flags | **Static GitHub API only — never executes code.** Commit-window / timeline checks live here. |
| `agents/ai_sophistication.py` | agentic-pattern evidence | Repo-agnostic. |
| **FUNCTIONAL VERIFIER (app-type dispatch)** | functional/UX evidence | See below. |
| `agents/cross_check.py` | deck/video/repo/live consistency, judge-review items | |
| `agents/rubric_scorer.py::score` | per-dimension `RubricScore` + verdict | Evidence-clamped (see below). |
| `orchestrator.py::_apply_integrity_enforcement` | `quarantined` override + cause flags | Last mutation before persist. |

### App-type verification dispatch (P1)

The functional verifier is chosen by `app_type` (declared at intake, else inferred), at
`orchestrator.py` (~the `app_type ==` branch):

- `web` → `agents/browser_verifier.py::verify` — Playwright; waits for SPA hydration before
  snapshotting; **grounds** any claimed journey success in real page evidence; uses candidate
  **declared journeys** when present, else inferred. Sets `auth_blocked` when credential-walled.
- `api` → `agents/api_prober.py::verify_api` — deterministic HTTP (no LLM). Calls **only declared
  endpoints**; GET/HEAD always, POST only with a declared `sample_body`; other verbs rejected;
  timeouts + request cap; best-effort bearer auth from `test_credentials`. Emits `api_ok`.
- `cli | notebook | ml_model | mobile | hardware | other` → **no functional verifier**; functional/
  UX route to `judge_review_items` with the legible reason `app_type=<t> not machine-verifiable
  without execution`.

### Scoring & fairness

- **Evidence ceiling** (`rubric_scorer.py`): a dimension can only reach `verified` if a verifier
  observed it. `functional_evidence = browser_ok OR api_ok`. UX is browser-only. The scorer cannot
  inflate past what the pipeline actually saw.
- **Weights/caps** (`rubric/weights.py::profile_for(archetype, *, has_functional_evidence)`): base
  weights sum to 100; archetype redistributes (e.g. research shifts UX→Depth); when there is no
  functional evidence, `functional` is capped and routed to judges.
- **Verdict** (`rubric_scorer.py`): `evaluable_weight < 50` → `insufficient`; `≥ 65` → `shortlist`;
  `≥ 40` → `borderline`; else `below_threshold`. `quarantined` is set by integrity enforcement and
  is never overwritten.
- **Calibration**: three markdown anchors (`rubric/anchors.py`) re-scored by `run-anchors`; drift
  beyond `MAX_DRIFT` (10) fails CI and is recalibrated to the observed centre, not masked.

## Data model (`trace/schema.py`)

| Table | Key columns |
|---|---|
| `submissions` | `id, candidate_*, repo_url, live_url, video_url, deck_path, archetype, app_type, status, is_anchor, extras_json, submission_md_raw` |
| `submission_blobs` | deck PDFs etc. (`submission_id, name, data`) — lets the 2 services share artifacts without a shared FS |
| `verifier_runs` | one row per agent run: `agent, output_json, cost_usd, error` — also the resume checkpoint log |
| `scores` | per-dimension: `dimension, raw_score, weighted_score, evidence_kind, rationale, cap_*` |
| `totals` | `total_score, verdict, evaluable_weight, normalized, integrity_flags_json, judge_review_items_json, verdict_override, judge_notes, overridden_by/at, shortlist_state, finalized_by, finalized_at_shortlist` |

Two interchangeable backends behind one protocol: **SQLite** (default, `trace/store.py`) and
**Postgres** (`trace/postgres_store.py`, used in production so both Railway services share state).
`extras_json` carries the type-specific artifact inputs (`api_endpoints`, `cli_command`,
`notebook_path`, `declared_journeys`, `test_credentials`).

**Stickiness:** `record_total` excludes the human columns (`verdict_override`, `judge_notes`,
`shortlist_state`, …) from its `ON CONFLICT DO UPDATE`, so re-scoring never erases a judge's
override or finalist pick.

## Judge workbench (`dashboard/app.py`)

One global board, designed so judges **decide without drilling into individual submissions**:

- Filter/sort bar pushes straight into `store.leaderboard(app_types, verdict, status,
  has_live_url, finalist_only, search, sort)` — no Python-side re-filtering.
- Each row surfaces app_type, total, effective verdict, the six dimension score chips,
  evaluable weight, quarantine/integrity badge, review-item count, live-URL indicator, and
  current shortlist state.
- Inline **Mark finalist / Mark winner / Clear** buttons call `store.set_finalist(id, state,
  finalized_by)`; judge identity comes from the Cloudflare-Access header / `$USER`. The detail
  view remains as an optional audit trail.

## Resilience & ops

- **Resume**: `completed_agent_outputs` + `_rebuild_from_cache` skip already-run agents on restart.
- **Requeue**: `reset_stale_running` returns stuck `running` rows to `pending` with bounded retries
  (`autojudge_max_restart_retries`) before dead-lettering — survives Railway restarts mid-run.
- **Topology**: two Streamlit services (dashboard + intake) + managed Postgres on Railway, both
  built from one image dispatched by `AUTOJUDGE_ROLE` (`railway.toml`, `scripts/start.sh`).
- **Deploy**: merge to `main` → Railway auto-deploys via its GitHub integration. CI `anchor-smoke`
  gates PRs on calibration drift.

## CLI (`cli.py`)

`ingest-flexible`, `run`, `run-batch`, `run-anchors`, `leaderboard`, `inspect`, `export-top`
(supports `--app-type` / `--finalist-only`), `gc`, `purge`, `doctor`, `serve-healthz`.
