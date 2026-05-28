# Agrim AutoJudge — Next Steps: Host, Share, and Run

This is the **start-here guide** for getting AutoJudge live for the Agrim
team. v1.2 (current) runs as **two Streamlit services + one managed
Postgres**, all on Railway. Workers are **no longer continuous** — the
judges' dashboard triggers AI evaluation on demand from a button.

**Repo (private):** [Agrim-Intelligence/hackathon-autojudge](https://github.com/Agrim-Intelligence/hackathon-autojudge)

| If you are… | Read this section | Time |
| --- | --- | --- |
| **First-time deploy** (no terminal needed past Step 2) | [Part 1: Host on Railway](#part-1-host-on-railway-one-time-setup) | ~30 min |
| **Hackathon lead** — open intake, share links | [Part 2: Share with the team](#part-2-share-with-the-team) | ~15 min |
| **Judge** — review scores, click Evaluate, pick top 10 | [Part 3: Daily use (judges)](#part-3-daily-use-judges) | 5 min read |
| **Developer** — local changes, CI | [Part 4: Developer follow-ups](#part-4-developer-follow-ups) | as needed |

---

## What v1.2 looks like

```
Candidates ──► intake service  (Streamlit form, public URL)
                      │
                      ▼
              Railway Postgres  ◄─── shared backing store
                      ▲
                      │
Judges    ──► dashboard service (Streamlit + on-demand evaluator)
                      │   "Evaluate selected" button spawns the AI pipeline
                      ▼   in the background; statuses surface live in the table
              Repo-snapshot cache on the dashboard's /data volume
```

- **Postgres** holds every submission row, score, verifier-run, and the
  uploaded deck bytes (`submission_blobs` table). No file-share needed.
- **dashboard service** has a 10 GB Railway volume at `/data` for repo
  snapshot tarballs and Playwright screenshots produced *during evaluation*.
- **intake service** is filesystem-free — runs without any volume.
- **No worker process is running 24/7.** Evaluations only consume LLM /
  GitHub credits when a judge clicks the new **Evaluate selected**,
  **Evaluate all pending**, or **Evaluate all** button.

---

## Part 1: Host on Railway (one-time setup)

You need **one person with access to**:

1. The [Agrim-Intelligence](https://github.com/Agrim-Intelligence) GitHub org (to connect Railway to the repo).
2. A [Railway](https://railway.com) account (Hobby plan is fine — ~$5/mo Postgres + free service hours).
3. API keys: **Anthropic** (recommended), **Groq** (cheap fallback), plus a fine-grained **GitHub PAT** (Contents:Read, Metadata:Read).

The one-shot script does everything in Steps 2–4 below. If you'd rather
click through the UI, the same steps are written out manually in
[`DEPLOY.md`](DEPLOY.md).

### Step 1 — Create an empty Railway project (browser, 1 min)

1. Log in to [Railway](https://railway.com).
2. Click **+ New Project → Empty Project**. Name it `agrim-autojudge`.
3. Leave it empty for now — the script populates it.

### Step 2 — Install the Railway CLI on your laptop (5 min)

**macOS:**

```bash
brew install railway
```

**Linux / WSL:**

```bash
curl -fsSL https://railway.com/install.sh | sh
```

Then log in (browser will open):

```bash
railway login
```

### Step 3 — Link the repo to the project (1 min)

From the repo root on your laptop:

```bash
cd hackathon-autojudge
railway link
```

When prompted, pick the `agrim-autojudge` project you created in Step 1.

### Step 4 — Export your secrets and run the deploy script (10 min)

Set the secrets in your **current shell** (they never get written to disk):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export GROQ_API_KEY="gsk_..."                  # optional fallback
export GITHUB_TOKEN="github_pat_..."           # fine-grained, Contents:Read + Metadata:Read

# Pick judges' credentials (they'll use these to sign in to the dashboard).
export AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER="judges"
export AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS="$(openssl rand -base64 20)"
echo "Dashboard password: ${AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS}"   # save this!

# Optional: lock the intake form too. Leave empty for a fully public candidate form.
# export AUTOJUDGE_INTAKE_BASIC_AUTH_USER="candidates"
# export AUTOJUDGE_INTAKE_BASIC_AUTH_PASS="$(openssl rand -base64 16)"
```

Then run:

```bash
bash scripts/deploy_railway.sh
```

The script will, idempotently:

1. Add a **Postgres** plugin to your project.
2. Create the **dashboard** and **intake** services (or skip if they exist).
3. Push every env var listed above onto both services, and wire
   `DATABASE_URL` to the shared Postgres via a Railway Reference Variable.
4. `railway up` both services to build + deploy.

Re-running the script is safe — it only pushes changes.

### Step 5 — Attach a 10 GB volume to the dashboard service (2 min)

In the Railway dashboard, open the `dashboard` service and:

1. **Settings → Volumes → New Volume.**
2. Size: `10 GB`. Mount path: `/data`.
3. Confirm. Railway redeploys with the volume attached.

The intake service does **not** need a volume — leave it as is.

### Step 6 — Generate public URLs (1 min)

```bash
railway domain --service dashboard
railway domain --service intake
```

Each prints something like `dashboard-production-1234.up.railway.app` —
save both, they're what you share in Part 2.

### Step 7 — Bootstrap the calibration anchors (5 min)

Once both services say `healthy` in the Railway UI:

```bash
# Sanity-check the runtime (provider keys, Playwright, outbound HTTPS).
railway run --service dashboard autojudge doctor

# Run the three calibration anchors so the live system has a reference scale.
railway run --service dashboard autojudge run-anchors
```

The dashboard now has anchor totals on file. If the doctor command reports
"backend: postgres" you are good. **If you see "backend: sqlite"** the
`DATABASE_URL` reference variable did not propagate — re-run
`scripts/deploy_railway.sh`.

---

## Part 2: Share with the team

1. **Dashboard URL** (judges): paste into your team Slack along with the
   `AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER` / `AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS`
   you printed in Step 4. The dashboard is locked behind basic auth.
2. **Intake URL** (candidates): paste into your candidate Slack /
   announcement. By default this is fully public (anyone with the link can
   submit). Add basic auth via env vars on the intake service if you want
   to restrict it.
3. Send judges to [`HANDOFF.md`](HANDOFF.md) for a 5-minute orientation.

---

## Part 3: Daily use (judges)

Judges' workflow:

1. Open the dashboard URL, sign in.
2. The **Leaderboard** tab shows every submission. Each row has a `Run`
   checkbox on the left.
3. Tick the rows you want to (re)evaluate, then click **Evaluate selected**.
   Alternatives:
   - **Evaluate all pending** — runs everything still in `pending` or
     `failed` state (typical after a candidate batch lands).
   - **Evaluate all** — full re-score of everything (use after changing
     rubric weights or anchors).
4. Status flips to `running` while the AI agents work. Tick
   **Auto-refresh while running** to have the table re-poll every 5s.
5. When status hits `scored`, click into the submission, review evidence,
   adjust archetype / verdict / notes as needed.
6. **Export top-N as CSV** at the bottom of the leaderboard once your
   shortlist is finalised.

Evaluation cost shows in the per-submission detail view (precise when the
primary provider is Anthropic, heuristic otherwise).

---

## Part 4: Developer follow-ups

Local development still works with SQLite — leave `DATABASE_URL` unset in
your `.env` and the trace store falls back to a file at
`AUTOJUDGE_DB_PATH`. Local `autojudge run-anchors` and `streamlit run
dashboard/app.py` work unchanged.

To talk to the Railway Postgres from your laptop:

```bash
# Print the connection URL (don't share it!).
railway variables --service dashboard | grep DATABASE_URL
```

Then `psql "$(railway variables --service dashboard --get DATABASE_URL)"`.

### Common operations

```bash
# Watch live logs.
railway logs --service dashboard
railway logs --service intake

# Open a shell in the dashboard service (needs the Railway shell plugin or
# you can use `railway run --service dashboard bash`).
railway run --service dashboard bash

# Garbage-collect old repo snapshots (frees /data on the dashboard).
railway run --service dashboard autojudge gc

# Purge a spam / test submission.
railway run --service dashboard autojudge purge <submission_id> --yes
```

### Re-deploying after a code change

```bash
git push origin main
bash scripts/deploy_railway.sh
```

The script picks up the new code via `railway up` and redeploys both
services. Postgres data is untouched — only the running containers swap.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Dashboard shows "backend: sqlite" in `doctor` output | `DATABASE_URL` env var not propagating — re-run `scripts/deploy_railway.sh` and confirm `railway variables --service dashboard` prints a `${{Postgres.DATABASE_URL}}` reference. |
| `Healthcheck timed out` on first deploy | Streamlit takes ~30s to boot on first build because Playwright Chromium is unpacking. Watch logs; healthcheck recovers automatically. |
| `Dockerfile invalid: docker VOLUME ... is not supported` | Make sure you're on v1.2+ — the `VOLUME` directive was removed. Use Railway's volume UI to attach `/data` to the dashboard service. |
| Healthcheck never goes green; logs show `$PORT` as literal string | Start command must be wrapped in `bash -lc '...'`. Both `railway.dashboard.toml` and `railway.intake.toml` already do this; if you customised, restore the wrapper. |
| Dashboard table never updates while a submission is "running" | Tick **Auto-refresh while running** in the leaderboard header, or click **Refresh** manually. |
| Evaluation never finishes (stays `running`) | Check `railway logs --service dashboard`. The pipeline kills itself after `AUTOJUDGE_SUBMISSION_TIMEOUT_S` (default 900s); marks the submission `failed` if a timeout fires. |
| New deck PDF not visible after Evaluation | Confirm the row was submitted *after* the Postgres-backed intake (v1.2). Pre-v1.2 deck files only live on the intake's local filesystem and are not reachable from the dashboard service. |

---

## Appendix: Architecture quick-reference

```
┌────────────────┐        ┌────────────────────────────┐
│  intake        │ writes │ Postgres (Railway plugin)  │
│  (Streamlit)   │───────▶│  - submissions             │
│  no /data vol  │        │  - submission_blobs (deck) │
└────────────────┘        │  - verifier_runs           │
                          │  - scores / totals         │
                          └────────────────────────────┘
                                       ▲
                                       │ reads + writes
                          ┌────────────────────────────┐
                          │  dashboard (Streamlit)     │
                          │  spawns `autojudge run`    │
                          │  subprocesses on demand    │
                          │  /data = repo cache, etc.  │
                          └────────────────────────────┘
```

**Why this shape?**

- Railway volumes can't be attached to two services at once, but
  candidates need their own intake URL and judges need their own
  dashboard URL — so we share state via Postgres, not a shared disk.
- The dashboard is its own worker. Subprocesses inherit the same image
  and config, so no separate worker service is required and we burn
  LLM credit only when a judge clicks Evaluate.
- The 10 GB volume on the dashboard service holds *per-evaluation
  scratch state* (repo tarballs, screenshots). It can be wiped at any
  time; the canonical state is in Postgres.
