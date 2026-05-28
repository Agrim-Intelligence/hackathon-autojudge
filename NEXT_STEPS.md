# Agrim AutoJudge — Next Steps: Host, Share, and Run

This is the **start-here guide** for getting AutoJudge live and into the
hands of the Agrim team. You do not need to read the whole codebase to
deploy or judge submissions.

**Repo (private):** [Agrim-Intelligence/hackathon-autojudge](https://github.com/Agrim-Intelligence/hackathon-autojudge)

| If you are… | Read this section | Time |
| --- | --- | --- |
| **Ops / infra** — first-time deploy | [Part 1: Host on Railway](#part-1-host-on-railway-one-time-setup) | ~45 min |
| **Hackathon lead** — open intake, share links | [Part 2: Share with the team](#part-2-share-with-the-team) | ~15 min |
| **Judge** — review scores, pick top 10 | [Part 3: Daily use (judges)](#part-3-daily-use-judges) | 5 min read |
| **Developer** — local changes, CI | [Part 4: Developer follow-ups](#part-4-developer-follow-ups) | as needed |

Deep dives live elsewhere:

- [`DEPLOY.md`](DEPLOY.md) — full deploy reference (architecture, env matrix, rollback)
- [`HANDOFF.md`](HANDOFF.md) — judge-facing page (fill in URLs after deploy)
- [`RUNBOOK.md`](RUNBOOK.md) — day-of operations, redeploys, GC, logs

---

## Where we are today

| Item | Status |
| --- | --- |
| Code on GitHub (`main`) | ✅ pushed |
| Basic auth for dashboard + intake | ✅ in code |
| Dockerfile + Railway template | ✅ committed |
| Anchor calibration (local) | ✅ recalibrated for v1.1 |
| Railway project live | ⬜ **you do this next** |
| URLs shared with judges | ⬜ after Railway deploy |
| CI workflow on GitHub | ⬜ optional; see [Part 4](#part-4-developer-follow-ups) |

---

## Part 1: Host on Railway (one-time setup)

You need **one person with access to**:

1. The [Agrim-Intelligence](https://github.com/Agrim-Intelligence) GitHub org (to connect Railway to the repo)
2. A [Railway](https://railway.app) account (Hobby plan is enough)
3. API keys: **Anthropic** (recommended) and/or **Groq** (cheap fallback), plus a **GitHub PAT** for reading candidate repos

No terminal is strictly required — everything below can be done in browser
tabs. A developer can help with the shell steps at the end.

### Step 1 — Create the Railway project (5 min)

1. Go to [railway.app/new](https://railway.app/new).
2. Choose **Deploy from GitHub repo**.
3. If prompted, install the **Railway GitHub App** on the `Agrim-Intelligence`
   org and grant access to **`hackathon-autojudge`** only.
4. Select `Agrim-Intelligence/hackathon-autojudge`.
5. Railway detects the `Dockerfile` and starts a first deploy — **rename this
   service to `dashboard`** (Settings → General → Service name).

### Step 2 — Add a shared disk (2 min)

All three services share one database and one snapshot cache.

1. Project → **Volumes** → **New Volume**
2. Name: `autojudge-data`
3. Mount path: `/data`
4. Size: **10 GB**
5. Attach this volume to the `dashboard` service (Settings → Volumes → Attach)

### Step 3 — Create three services from the same repo (15 min)

You need **three services**, all pointing at the same GitHub repo and
Dockerfile. Only the **start command** differs.

#### Service A — `dashboard` (judges)

Already created in Step 1. Set:

- **Settings → Deploy → Start command:** (must use `bash -lc` so `$PORT` expands)
  ```
  bash -lc 'streamlit run dashboard/app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true'
  ```
- **Settings → Deploy → Healthcheck path:** `/_stcore/health`
- **Settings → Networking → Generate domain** → copy the URL (e.g.
  `https://dashboard-production-xxxx.up.railway.app`)
- **Settings → Volumes** → attach `autojudge-data` at `/data`

#### Service B — `intake` (candidates)

1. Project → **New** → **GitHub Repo** → same `hackathon-autojudge` repo.
2. Rename service to `intake`.
3. **Start command:**
   ```
   bash -lc 'streamlit run src/autojudge/intake/form.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true'
   ```
4. **Healthcheck path:** `/_stcore/health`
5. **Generate domain** → copy URL.
6. Attach volume `autojudge-data` at `/data`.

#### Service C — `worker` (background scoring)

1. **New** → same repo again → rename to `worker`.
2. **Start command:**
   ```
   bash -lc 'autojudge serve-healthz --port 8500 & while true; do autojudge run-batch || true; sleep 60; done'
   ```
3. **Healthcheck path:** `/healthz`
4. **Networking:** expose port **8500** (Settings → Networking → TCP proxy
   or public domain on 8500).
5. Attach volume `autojudge-data` at `/data`.
6. Copy the worker URL (for health checks only — judges never open this).

> **Tip:** If Railway asks for a root directory or build command, leave
> defaults — the `Dockerfile` at repo root is the build.

### Step 4 — Set environment variables (10 min)

Open **Variables** on each service. You can use Railway's **Shared Variables**
at project level so you paste once and all three services inherit.

**Required on all three services:**

| Variable | Example / notes |
| --- | --- |
| `AUTOJUDGE_PRIMARY_PROVIDER` | `anthropic` |
| `AUTOJUDGE_FALLBACK_PROVIDER` | `groq` (leave blank = no fallback) |
| `ANTHROPIC_API_KEY` | from Anthropic console |
| `GROQ_API_KEY` | from Groq console (optional fallback) |
| `GITHUB_TOKEN` | fine-grained PAT with `Contents:Read` on submission repos |
| `AUTOJUDGE_DATA_DIR` | `/data` |
| `AUTOJUDGE_DB_PATH` | `/data/traces.db` |
| `AUTOJUDGE_SUBMISSION_TIMEOUT_S` | `900` |
| `AUTOJUDGE_SNAPSHOT_TTL_DAYS` | `14` |

**Dashboard only** (locks the judge UI):

| Variable | Value |
| --- | --- |
| `AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER` | `agrim-judge` |
| `AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS` | strong random password (24+ chars) |

**Intake only** (candidate form):

| Variable | Value |
| --- | --- |
| `AUTOJUDGE_INTAKE_BASIC_AUTH_USER` | `agrim-intake` *(or leave both empty to open intake during hackathon)* |
| `AUTOJUDGE_INTAKE_BASIC_AUTH_PASS` | strong random password |

Generate passwords: `openssl rand -base64 24` (or use 1Password generator).

After saving variables, Railway redeploys automatically. Wait until all three
services show **Active**.

### Step 5 — Bootstrap the database (5 min, needs Railway Shell)

This seeds calibration anchors and proves Playwright works on Linux.

1. Open **worker** → **Settings** → **Shell** (or Deployments → three dots → Shell).
2. Run these commands one at a time:

   ```bash
   autojudge doctor
   autojudge run-anchors
   autojudge run 20260525-040054-mayank-singh-tomar
   ```

3. **Success looks like:**
   - `doctor` — green on provider, GitHub token, Chromium, disk
   - `run-anchors` — three anchors, no `DRIFT` beyond tolerance
   - Mayank run — finishes with a total score and `verdict` (canonical regression)

If Mayank's **UX polish** row is still blank, check `doctor`'s live-URL
probe and worker logs — usually the candidate deploy was down, not a code bug.

### Step 6 — Smoke test (2 min)

From your laptop (replace URLs):

```bash
DASHBOARD_URL=https://your-dashboard.up.railway.app \
INTAKE_URL=https://your-intake.up.railway.app \
WORKER_URL=https://your-worker.up.railway.app \
./scripts/smoke_railway.sh
```

All three lines should print `OK`. Then open the dashboard URL in a browser,
sign in with the basic-auth credentials, and confirm you see the leaderboard.

### Step 7 — Fill in HANDOFF.md and commit

Edit [`HANDOFF.md`](HANDOFF.md): replace the three `TODO-*` URLs with your
Railway domains. Commit and push so the repo documents the live endpoints.

**You are now hosted.** Railway auto-redeploys on every push to `main`.

---

## Part 2: Share with the team

### What to put in 1Password (or a shared vault)

Create a vault entry: **Agrim AutoJudge MVP**

| Field | Value |
| --- | --- |
| Dashboard URL | `https://…dashboard….up.railway.app` |
| Dashboard username | `agrim-judge` |
| Dashboard password | *(from Step 4)* |
| Intake URL | `https://…intake….up.railway.app` |
| Intake username / password | *(only if intake is locked)* |
| GitHub repo | `https://github.com/Agrim-Intelligence/hackathon-autojudge` |

Do **not** paste API keys into Slack. Keys live only in Railway Variables.

### Slack message template (copy-paste)

```
🚀 Agrim AutoJudge is live for the internal hackathon pilot.

📊 Judges dashboard (review scores + shortlist):
   <dashboard URL>
   Login: see 1Password → "Agrim AutoJudge MVP"

📝 Candidate intake (share when hackathon opens):
   <intake URL>

📖 How to judge: open HANDOFF.md in the repo (or the Notion mirror if we make one)
🐛 Bugs / weird scores: GitHub Issues on hackathon-autojudge

What AutoJudge does: ranks submissions and surfaces evidence — you pick the final top 10.
Re-runs take ~3 min; don't refresh mid-run.
```

### Who gets what

| Role | Give them | They do |
| --- | --- | --- |
| **Judges (3–5)** | Dashboard URL + password + [`HANDOFF.md`](HANDOFF.md) | Review leaderboard, override verdicts, export top 10 |
| **Hackathon lead** | Intake URL + dashboard URL + this doc | Open/close intake, monitor worker logs |
| **Candidates** | Intake URL only (+ submission template link) | Submit repo / live URL / deck |
| **Engineering** | GitHub repo + [`RUNBOOK.md`](RUNBOOK.md) | Deploy, fix drift, rotate keys |

### Opening intake to candidates (non-technical)

**Option A — Open intake (easiest for hackathon day)**

1. Railway → **intake** service → **Variables**
2. **Delete** or clear `AUTOJUDGE_INTAKE_BASIC_AUTH_USER` and `_PASS`
3. Redeploy completes in ~1 min — candidates can submit without a password

**Option B — Keep intake locked**

Share the intake username/password from 1Password with organisers only;
they forward the link to candidates in the hackathon brief.

**Closing intake after deadline:** set the basic-auth vars again, or disable
the intake service's public domain in Railway Networking.

---

## Part 3: Daily use (judges)

No CLI, no Git, no Railway account needed.

1. Open the **dashboard URL** → sign in.
2. Left panel: submissions ranked by score. Look for `verdict_effective`.
3. Click a submission:
   - Read **Judge review items** (things the AI could not verify — your job
     is to check these manually).
   - Skim dimension scores and summaries.
4. **Override panel** (if you disagree with the auto-judge):
   - Change verdict → add a one-line note → **Save overrides**
   - Or **Save & re-run** if you want a fresh score (e.g. wrong archetype).
5. When done reviewing all entries, tell the lead — they run export (below)
   or you pick top 10 from the sorted list in the UI.

**Verdict meanings (shortlist generator framing):**

| Verdict | Meaning |
| --- | --- |
| `shortlist` | Strong enough to consider for top 10 |
| `borderline` | Worth a human look; evidence mixed |
| `below_threshold` | Unlikely top 10 on automatable surface |
| `insufficient` | Not enough public evidence to score fairly |

The AI **recommends**; your override (shown with `*`) is what counts for
the shortlist.

Full judge guide: [`HANDOFF.md`](HANDOFF.md).

---

## Part 4: Developer follow-ups

Optional but recommended after the pilot is stable.

### Push the CI workflow

The anchor-smoke workflow lives in `.github/workflows/anchor-smoke.yml`.
Push it after refreshing GitHub OAuth scope:

```bash
gh auth refresh -s workflow -h github.com
git add .github/workflows/anchor-smoke.yml
git commit -m "Add anchor-smoke CI workflow"
git push
```

Secrets already on the repo: `ANTHROPIC_API_KEY`, `GROQ_API_KEY`,
`AGRIM_GITHUB_PAT`.

### Local development (engineers only)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium
cp .env.example .env   # fill keys
autojudge doctor
streamlit run dashboard/app.py
```

Local basic auth is **off** when `AUTOJUDGE_DASHBOARD_BASIC_AUTH_*` are empty.

### Export top 10 (hackathon lead or engineer)

From Railway worker shell:

```bash
autojudge export-top --n 10 --out /data/top10.json
```

Download via Railway volume UI or `railway volume download`.

### Phase 2 (post-pilot, not MVP)

- Cloudflare Access SSO instead of shared basic-auth password
- Postgres instead of SQLite
- Hindi / Tamil / Bengali intake
- Tighter anchor drift + real repo fixtures for calibration
- GitHub App per org instead of single PAT

See [`DEPLOY.md`](DEPLOY.md) Appendix A and Phase 2 section.

---

## Quick troubleshooting (no code)

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Railway build: `VOLUME at Line … is not supported` | Dockerfile `VOLUME` directive | Remove it; attach Railway Volume at `/data` in dashboard only |
| Healthcheck fails; logs show `$PORT` as port | Start command not wrapped in shell | Use `bash -lc 'streamlit run … --server.port=$PORT …'` on dashboard + intake |
| Dashboard asks for login, team can't get in | Wrong password or vars not set on **dashboard** service | Check Railway Variables; reset password in 1Password |
| Submission stuck on "pending" forever | Worker not running or volume not attached | Check **worker** logs; confirm `/data` volume on all 3 services |
| All submissions fail at GitHub step | Missing or rate-limited `GITHUB_TOKEN` | Add PAT to Railway Variables; rerun `autojudge doctor` |
| Scores look wrong after prompt change | Anchor drift | Worker shell: `autojudge run-anchors`; if DRIFT, ask engineering |
| Deploy broke mid-hackathon | Bad release | Railway → Deployments → **Rollback** (data on volume is safe) |
| Cost spike | Too many re-runs or wrong model | Check worker logs; confirm `AUTOJUDGE_PRIMARY_PROVIDER=anthropic` with caching |

For anything else: open a GitHub Issue with submission ID + screenshot.

---

## Day-of hackathon checklist

**T−1 day**

- [ ] All three Railway services **Active**
- [ ] `autojudge doctor` green in worker shell
- [ ] `autojudge run-anchors` green
- [ ] Dashboard + intake URLs in 1Password
- [ ] [`HANDOFF.md`](HANDOFF.md) URLs updated
- [ ] Judges invited with dashboard link
- [ ] Decide: intake open (clear auth vars) or locked (share password)

**Hackathon open**

- [ ] Share intake URL + [`submission_standard/SUBMISSION_TEMPLATE.md`](submission_standard/SUBMISSION_TEMPLATE.md) with candidates
- [ ] Watch worker logs for first 2–3 submissions

**Hackathon close**

- [ ] Lock intake (restore basic auth or disable public domain)
- [ ] Wait for worker queue to drain (~3 min per submission)
- [ ] Judges review dashboard; overrides saved
- [ ] Export top 10 (`autojudge export-top`)
- [ ] Deliberation meeting uses exported JSON + judge notes

**After pilot**

- [ ] Collect feedback via GitHub Issues
- [ ] Rotate basic-auth passwords if shared widely
- [ ] Decide Phase 2 items (SSO, all-India scale)

---

## Cost expectation

| Item | ~Cost |
| --- | --- |
| Railway (3 services + 10 GB volume) | ~$20/month |
| LLM API (~50 submissions, Anthropic + caching) | ~$0.20–0.40 total |
| GitHub PAT | free |

Turn off or scale down Railway services when the pilot ends to stop billing.

---

## Summary

1. **Host:** Railway, three services, one volume, env vars from [Step 4](#step-4--set-environment-variables-10-min).
2. **Bootstrap:** worker shell → `doctor` → `run-anchors` → Mayank regression.
3. **Share:** 1Password for creds, Slack for URLs, [`HANDOFF.md`](HANDOFF.md) for judges.
4. **Use:** judges live in the dashboard; worker scores automatically every 60 s.
5. **Non-technical deploy is feasible:** Steps 1–4 and 6–7 are all browser UI;
   only Step 5 needs someone comfortable pasting three commands into Railway Shell.

Questions: `@chetan` or open an issue on the repo.
