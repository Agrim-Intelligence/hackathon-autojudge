# Agrim AutoJudge v1.1 — Runbook

Operator playbook for the Shortlist Generator. Top to bottom on judging day. Anything in `monospace` is a literal command.

**Mental model.** AutoJudge ranks submissions on the automatable public surface and surfaces everything else (credential-walled UIs, third-party integrations, hardware demos) as `judge_review_items`. The output is a **ranked shortlist with curated evidence packs**, not a final score. Human judges pick winners from the shortlist.

## 0. Setup (one-time)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium
cp .env.example .env
```

Fill `.env` with the keys you have. Required for v1.1:

- `ANTHROPIC_API_KEY` — recommended primary (enables prompt caching + tool-calling).
- `GROQ_API_KEY` — recommended fallback (free).
- `GITHUB_TOKEN` — **strongly recommended.** Unauthenticated GitHub allows 60 requests/hour per IP; the pipeline downloads one repo snapshot per submission plus a handful of metrics calls, which exceeds the unauthenticated limit on any real batch. Provision a fine-grained PAT with **Contents:Read** and **Metadata:Read** at github.com/settings/personal-access-tokens, paste the token into `.env`. Without it the pipeline raises `GitHubRateLimitError` immediately on the first 403 instead of letting PyGithub silently freeze for 9 minutes.

Optional: `GEMINI_API_KEY`, `OPENROUTER_API_KEY` — if you want to route through those providers, set them and switch `AUTOJUDGE_PRIMARY_PROVIDER`.

## 1. Health-check the runtime

Every time you change `.env`, restart any Streamlit processes (they cache env at boot). The CLI re-reads `.env` on every invocation.

```bash
autojudge doctor
```

`doctor` now checks:

- Resolved provider / model / API-key matrix.
- `GITHUB_TOKEN` presence.
- Playwright Chromium binary in the OS cache (warns when missing).
- Free disk space on `AUTOJUDGE_DATA_DIR` (snapshot cache + screenshots eat ~50-100 MB per submission).
- Anchor drift (on-file totals vs `anchors.py` expected — read-only, no re-run).

`doctor` exits non-zero only on hard failures (no primary API key, disk < 1 GB). Warnings are surfaced but the pipeline can still run.

## 2. Two .env recipes (no run-mode flag in code)

Provider routing is purely env-driven. Pick the recipe that fits your goal — there is no `--mode prod` switch.

### Free dev / smoke testing

```
AUTOJUDGE_PRIMARY_PROVIDER=groq
AUTOJUDGE_FALLBACK_PROVIDER=
```

Notes: Groq does not support prompt caching or native tool calls, so the Inference Agent uses its single-shot fallback path. Cost figures in the dashboard are heuristic. You may hit free-tier rate limits on large batches; the orchestrator paces requests by 2.5s automatically when provider=groq.

### Production judging (recommended)

```
AUTOJUDGE_PRIMARY_PROVIDER=anthropic
AUTOJUDGE_FALLBACK_PROVIDER=groq
```

Notes: Anthropic native SDK is used; static prompt blocks (rubric definitions, agent system prompts) get `cache_control: ephemeral` markers and ride the 5-min cache. The Inference Agent uses the tools API with up to 8 calls per submission. Costs are API-reported (precise) using `cache_creation_input_tokens` / `cache_read_input_tokens`.

## 3. Distribute the candidate message

Send `CANDIDATE_MESSAGE.md` to participants. It points them at the intake form. v1.1 messaging:

> Submit your repo or live URL. Anything else (deck, video, free-form context) is optional. AutoJudge produces a shortlist; human judges pick the winners. Things requiring your credentials become judge-review items and won't penalise your score — call them out in your free-form notes.

Set a deadline.

## 4. Stand up the intake form

```bash
source .venv/bin/activate
streamlit run src/autojudge/intake/form.py --server.port 8501
```

LAN access: add `--server.address 0.0.0.0`.

The form accepts any of: repo URL, live URL, video URL, deck PDF, free-form context. At least one artifact required. Watch incoming submissions with:

```bash
autojudge leaderboard
```

If a candidate prefers CLI:

```bash
autojudge ingest-flexible --name "Their Name" \
  --repo https://github.com/... --live https://...
```

`--context <path>` accepts any text file as free-form notes; everything else is optional.

## 5. Calibrate against anchors (post-upgrade especially)

Before the real batch, run the three calibration anchors. This shakes out API-key issues, confirms scoring lands in the expected range under the active provider, and validates the Shortlist-Generator framing.

```bash
autojudge run-anchors
```

Expected totals are tolerant-aware (insufficient_evidence dimensions normalised out). After the v1.1 reframing, the first anchor run on a fresh codebase is expected to drift a few points — that's not a regression, that's the structural change. `MAX_DRIFT` is set to 10 to absorb this; tighten to 8 after the first clean pass.

If any anchor drifts beyond `MAX_DRIFT`, the command exits non-zero and you should review prompts before proceeding.

## 6. Run the batch

```bash
autojudge run-batch
```

Pipeline per submission:

```
guard -> deploy_probe -> repo_snapshot -> inference (tool-calling)
      -> archetype -> code_analyst -> ai_sophistication
      -> browser_verifier -> cross_check -> rubric_scorer -> persist
```

Latency budget (post-snapshot-cache):

- 30-90s per submission without live URL (Inference Agent + 3 verifier LLM calls, repo file reads off disk)
- 3-7 min per submission with live URL (browser verifier dominates)

If a submission errors out, the orchestrator writes a synthetic `verifier_runs` row tagged `agent='orchestrator'` with the full traceback, marks the submission `failed`, and continues with the next one. Re-run a single submission with:

```bash
autojudge run <submission_id>
```

Re-runs are nearly free — the repo snapshot is reused, only LLM costs are incurred.

## 7. Stand up the judges' dashboard

```bash
source .venv/bin/activate
streamlit run dashboard/app.py --server.port 8502
```

The dashboard shows:

- Active provider, fallback, caching/tools capabilities.
- Shortlist with `verdict` badges (shortlist / borderline / below_threshold / insufficient), `judge_review_items` count, `evaluable_weight`, and `normalized` flags.
- Per-submission cost (precise when provider=anthropic, heuristic otherwise).
- Per-dimension provenance badges (stated / inferred / verified / insufficient) — deterministically clamped to pipeline state.
- **Judge-review items panel** (the central UX of the Shortlist Generator): claims AutoJudge could not verify, with reasons, ready for the deliberation meeting.
- Gaps Flagged panel — combines Inference Agent gaps + scorer integrity flags.
- Full agent trace including the Inference Agent's tool calls and outputs.
- Archetype override + re-score guidance.

## 8. Export the shortlist for deliberation

```bash
autojudge export-top --n 10 --out data/top10.json
```

The artifact has candidate name, total score, verdict, archetype, integrity flags, **and `judge_review_items`** — bring it to the human deliberation meeting. Each top-N entry carries everything the judges need to verify offline.

## 9. After judging

Archive `data/traces.db` and `data/submissions/`. The `repo_cache/snapshot.tar.gz` tarballs can be deleted to save space — they are not part of the audit trail. Everything else (verifier_runs, scores, totals, judge_review_items, judge overrides) is in the SQLite db.

To trim disk between hackathons:

```bash
autojudge gc                 # evicts snapshots older than AUTOJUDGE_SNAPSHOT_TTL_DAYS
autojudge gc --dry-run       # preview without deleting
autojudge purge <id> --yes   # nuke a single test/spam submission (DB rows + on-disk artifacts)
```

## 10. Judge overrides (dashboard)

Each submission page in the dashboard has an Override panel with three controls:

- **Archetype override** — flips the archetype. Read by the next pipeline run; an explicit re-run is needed for the weights to change.
- **Verdict override** — marks the submission `shortlist` / `borderline` / `below_threshold` / `insufficient` regardless of the auto-score. The auto-judge's recommendation is preserved in the trace.
- **Judge notes** — free-form rationale. Surfaces in `autojudge inspect`, in `autojudge export-top` JSON, and in the leaderboard's Notes column.

Buttons:

- **Save overrides** — persists archetype + verdict + notes. No re-run.
- **Save & re-run** — persists then spawns `autojudge run <id>` in the background. Tail `data/submissions/<id>/last_run.log` for live progress.
- **Clear override** — wipes verdict + notes + auditor identity. Archetype is preserved.

Overrides survive a full pipeline re-run. The `record_total()` path explicitly does not touch the override columns on conflict, so a `Save & re-run` keeps the human verdict pinned even if the auto-judge changes its mind. Auditor identity comes from Cloudflare Access (`Cf-Access-Authenticated-User-Email` header) when the dashboard sits behind it; otherwise the local `$USER`.

In the leaderboard and `autojudge inspect`, an overridden verdict is shown with a trailing `*`. The CLI also prints the auto-judge's original recommendation right next to the override.

## 11. Operating on Railway

See [`DEPLOY.md`](DEPLOY.md) for the first-time deploy. Day-to-day operations:

- **Redeploys mid-batch.** Any submission whose pipeline was running when the worker container restarted gets auto-reset from `running` → `failed` on the next worker startup. The trace records `error='restart_during_run'`. Re-queue them with `autojudge run <id>` or `autojudge run-batch`.
- **Submission timeouts.** A submission that exceeds `AUTOJUDGE_SUBMISSION_TIMEOUT_S` (default 900s) short-circuits at the browser verifier with a `submission_timeout` integrity flag. The submission still scores on whatever reports were produced. Bump the env var if your live URLs are slow but functional.
- **Bulk re-score after a prompt fix.** From any service shell: `sqlite3 /data/traces.db "UPDATE submissions SET status='pending'"` then `autojudge run-batch`. Judge overrides survive the re-run.
- **Tightening `MAX_DRIFT`.** Once anchors have run cleanly on the deployed image, lower `MAX_DRIFT` in `src/autojudge/rubric/anchors.py` from 10 back to 8. Commit, push, and the anchor-smoke workflow gates future PRs at the tighter threshold.
- **Reading worker logs.** Railway → worker service → Logs. For a specific submission, tail `/data/submissions/<id>/last_run.log` — the dashboard's `Save & re-run` button writes there too.
- **Reading SQLite directly.** Railway shell on any service: `sqlite3 /data/traces.db`. Common queries:

  ```sql
  SELECT id, status, archetype, verdict, verdict_override
    FROM submissions
    LEFT JOIN totals ON submissions.id = totals.submission_id
    ORDER BY total_score DESC NULLS LAST;
  ```

- **Disk pressure.** `autojudge doctor` warns when the snapshot cache > 1 GB; `autojudge gc` evicts entries older than the TTL. On the Hobby plan's 10 GB volume, plan to gc weekly or after every batch.

---

## What is out of scope for v1.1 (deferred)

These are intentionally NOT in v1.1. We do not claim them at GTM.

- Gap Probe (asking candidate clarifying questions via email/Slack)
- Plagiarism / similarity search vs public GitHub
- Sandboxed code execution for non-deployed submissions
- Non-English submissions (Hindi etc.)
- Multi-tenant college account isolation
- Postgres trace store (interface is ready; Phase 2 swaps in the backend)
- Worker pool / concurrent submissions (Phase 2)
- GitHub App on Agrim org (Phase 2; PAT works for v1.x)
- **Loom transcript support** — Loom share-page scraping was unreliable. v1.x supports YouTube only. Other hosts return an explicit "unsupported" path; the cross-check verifier notes the absence rather than failing.

## Troubleshooting

- **`API key for provider 'X' not set`** — `.env` not loaded. Run `autojudge doctor` to confirm. If Streamlit was started before you edited `.env`, restart it.
- **`Payload too large` on Groq** — expected on large repos. The client auto-halves context and retries, then falls back to the configured fallback provider.
- **`GitHubRateLimitError`** — set `GITHUB_TOKEN` in `.env`. The pipeline now fails fast (within ~10 seconds) instead of letting PyGithub silently freeze for 9 minutes.
- **Snapshot download failed** — non-fatal. Agents fall back to per-call REST reads; the trace shows `agent='repo_snapshot'` with an error. Common causes: GitHub 403 (set token), network blip, very large repo (>500 MB).
- **Playwright launch fails** — run `playwright install chromium`. v1.1 uses `channel='chromium'` so the full bundled Chromium is the target (works regardless of whether the headless_shell binary is installed). `autojudge doctor` checks the OS cache directly.
- **Browser verifier always times out** — candidate's live URL may be down or rate-limiting our user agent. Check the `deploy_probe` row in `verifier_runs` for the HTTP status code.
- **Anchor drift after upgrade** — expected once. Re-run, recalibrate `expected_total` in `src/autojudge/rubric/anchors.py`, then tighten `MAX_DRIFT` from 10 back to 8.
- **Submission stuck in `failed`** — re-run with `autojudge run <id>`. Open the dashboard's agent trace and look for the row with `agent='orchestrator'` — it contains the full traceback of where the pipeline blew up.
- **Long browser verifier runs** — lower `AUTOJUDGE_BROWSER_MAX_STEPS` from 12 to 8 in `.env`.
- **`cost_ceiling` integrity flag** — an agent exceeded its per-submission LLM-call budget. Inspect the trace; usually a sign of a runaway tool-call loop or a pathological live URL. Not fatal in Phase 1 (observation only); Phase 2 will enforce hard caps.

## Post-v1.1 roadmap

- v1.2: Gap Probe (clarifying questions), Loom support, sandboxed code execution, multi-tenant college isolation.
- v2.0: Phase 2 architecture — Postgres trace store, worker pool + queue, GitHub App, containerised judge runtime, fairness instrumentation, model drift playbook. Pre-all-India rollout.
