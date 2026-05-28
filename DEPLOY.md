# Deploying Agrim AutoJudge on Railway

This guide walks the Agrim infra team through the MVP deploy: one repo, one
Docker image, three Railway services sharing a single persistent volume,
Streamlit-side basic auth as the front door. Plan for ~45 minutes
end-to-end on the first deploy.

The Cloudflare Access path lives in **Appendix A** at the bottom as the
recommended hardening step once basic auth has carried us through the
internal pilot.

## Architecture (MVP)

```
            Railway-issued HTTPS URLs (no CF required)
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   dashboard         intake-form        (worker, no public UI)
   (Streamlit +      (Streamlit +       (run-batch loop + /healthz)
    basic auth)       basic auth)
        │                │                │
        └────────────────┼────────────────┘
                         │
                  Railway volume @ /data
                  (SQLite + snapshot cache + screenshots)
```

All three services run the same image built from
[`Dockerfile`](Dockerfile). The only difference is the start command — see
[`railway.toml`](railway.toml) for the per-service overrides.

## Prerequisites

1. **Railway** project (Hobby plan is enough for the internal hackathon).
2. **GitHub fine-grained PAT** with `Contents:Read` and `Metadata:Read` on
   the org repos candidates will submit. Without this the pipeline hits the
   60 req/hr unauthenticated GitHub limit and dies on submission #2.
3. **LLM provider key** — Gemini, Anthropic, OpenRouter, or Groq. Anthropic
   is recommended for live runs because of prompt caching; Gemini is the
   cheapest fallback.
4. **Two strong random passwords** for the basic-auth shim (one for the
   dashboard, one for the intake form). 24+ chars; 1Password or
   `openssl rand -base64 24` is fine.

Cloudflare is **not** required for the MVP. See Appendix A when you're ready
to swap basic auth for proper SSO.

## One-time setup

### 1. Create the Railway project

```
railway login
railway init             # in the repo root
```

Push the GitHub remote to Railway when prompted. Railway detects the
[`Dockerfile`](Dockerfile) automatically.

### 2. Create the shared volume

In the Railway dashboard:

1. Project → Settings → Volumes → **New Volume**
2. Name `autojudge-data`, mount path `/data`, initial size **10 GB**.
3. Attach it to every service you create below.

### 3. Create the three services

For each service: New Service → Deploy from GitHub repo → select the same
repo → set the start command per the table below. Then attach the
`autojudge-data` volume to the service (Settings → Volumes).

| Service     | Start command                                                                                                                                       | Healthcheck path        | Public? |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- | ------- |
| `dashboard` | `bash -lc 'streamlit run dashboard/app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true'`                                   | `/_stcore/health`       | yes     |
| `intake`    | `bash -lc 'streamlit run src/autojudge/intake/form.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true'`                       | `/_stcore/health`       | yes     |
| `worker`    | `bash -lc 'autojudge serve-healthz --port 8500 & while true; do autojudge run-batch || true; sleep 60; done'`                                       | `/healthz` on port 8500 | no      |

### 4. Set environment variables

Configure these on **each** service (Railway → Service → Variables). Copy
from [`.env.example`](.env.example) for the full matrix; the minimum set is:

```
AUTOJUDGE_PRIMARY_PROVIDER=anthropic
AUTOJUDGE_FALLBACK_PROVIDER=gemini
ANTHROPIC_API_KEY=<sk-ant-...>
GEMINI_API_KEY=<...>
GITHUB_TOKEN=<github_pat_...>
AUTOJUDGE_DATA_DIR=/data
AUTOJUDGE_DB_PATH=/data/traces.db
AUTOJUDGE_SUBMISSION_TIMEOUT_S=900
AUTOJUDGE_SNAPSHOT_TTL_DAYS=14
```

### 5. Lock the public Streamlit surfaces (basic auth)

The dashboard exposes candidate submissions and judge overrides; do not
leave it open to the internet. The MVP front door is a Streamlit-side basic
auth shim ([`src/autojudge/auth.py`](src/autojudge/auth.py)) gated on four
env vars:

On the **dashboard** service, set both:

```
AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER=agrim-judge
AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS=<24-char random>
```

On the **intake** service, set both (or leave empty during the hackathon
window so candidates can submit without a credential):

```
AUTOJUDGE_INTAKE_BASIC_AUTH_USER=agrim-intake
AUTOJUDGE_INTAKE_BASIC_AUTH_PASS=<24-char random>
```

On the **worker** service the basic-auth keys are not needed (no public UI).

Notes:

- The shim is a no-op when either USER or PASS is empty — that's the local
  dev path.
- The signed-in username flows into the override audit trail
  (`overridden_by` column on `totals`). Rotate the credential between
  judging sessions if you want per-session attribution; per-judge SSO is
  the Cloudflare Access upgrade in Appendix A.
- The shim does **not** gate the healthcheck paths
  (`/_stcore/health`, `/healthz`) so Railway's healthchecks and our
  [`scripts/smoke_railway.sh`](scripts/smoke_railway.sh) still pass.

### 6. Post-deploy smoke check

From the Railway shell on any service (Service → Settings → Shell):

```
autojudge doctor
```

You should see:

* every provider with `set` for whichever keys you configured;
* `GITHUB_TOKEN set (5000 req/hr authenticated limit)`;
* `Playwright Chromium detected`;
* a free-disk line for `/data` reporting close to your volume size;
* the outbound-HTTPS smoke green for both example.com and api.github.com;
* the live-URL table empty (no submissions yet);
* no anchor entries yet (anchors haven't been run).

Then run the anchors once to seed the calibration table:

```
autojudge run-anchors
```

This will create three submissions in the DB and verify the rubric's
expected totals are within `MAX_DRIFT`. Repeat after any prompt or model
change.

### 7. Wire the GitHub Actions anchor-smoke check

Add the same secrets used by Railway to the GitHub repo:

```
GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY,
AGRIM_GITHUB_PAT
```

The [`anchor-smoke`](.github/workflows/anchor-smoke.yml) workflow runs the
calibration anchors on every PR touching agents/prompts/rubric and nightly
at 00:30 IST. It will fail any PR that drifts anchors beyond `MAX_DRIFT`.

## Day-of-hackathon operations

* **Open intake** — flip the Cloudflare Access policy on the intake
  application to `Bypass for IPs in <candidate range>` or `Allow everyone`.
* **Stop accepting submissions** — flip the Cloudflare Access policy back
  to `Allow @agrim.ai only`. Candidates already mid-form keep their copy of
  the form open but can't submit.
* **Score everything** — the worker loops every 60 s and picks up pending
  submissions automatically. To force a sweep:
  `railway run --service worker autojudge run-batch`.
* **Review** — judges open the dashboard, sort by `verdict`, drill into
  each submission, override verdict + notes as needed, and (optionally)
  hit `Save & re-run` for any submission they want re-scored under a
  different archetype.
* **Export the top 10** — from any shell:
  `railway run --service worker autojudge export-top --n 10 --out /data/top10.json`.
  Copy the JSON out of the volume with
  `railway volume download autojudge-data /data/top10.json`.

## Rollback

If a deploy goes bad:

1. Railway → Service → Deployments → previous successful deploy → **Rollback**.
2. The volume is untouched; SQLite and snapshot cache are preserved.
3. Any submissions caught mid-pipeline by the redeploy auto-reset from
   `running` → `failed` on the next worker startup (see
   `TraceStore.reset_stale_running` in
   [`src/autojudge/trace/store.py`](src/autojudge/trace/store.py)). Re-queue
   them with `autojudge run-batch` once you've identified the failed
   submission IDs.

## Cost ballpark (internal hackathon, ~50 submissions)

| Component                         | Estimate    |
| --------------------------------- | ----------- |
| Railway Hobby (3 services, 10 GB) | ~$20 / mo   |
| Anthropic Claude (with caching)   | ~$0.20-0.40 |
| Cloudflare Access (first 50 seats)| free        |
| GitHub PAT                        | free        |
| **Total for the hackathon**       | **< $30**   |

## Phase 2 follow-ups

The items below are explicitly **out of scope** for the internal pilot and
queued for the all-India phase:

* Postgres swap (the `TraceStoreProtocol` exists so this is mechanical).
* Per-agent enforcing cost ceilings (currently observational only).
* Multilingual intake + rubric (Hindi/Tamil/Bengali submissions).
* Score recalibration after a 50-submission baseline.
* GitHub App instead of a single PAT (per-candidate-org-install flow).
* Cloudflare Access SSO (see Appendix A).

---

## Appendix A: Cloudflare Access (hardening, post-MVP)

Once the internal pilot has shaken out and you're ready to upgrade from the
basic-auth shim to per-judge SSO:

1. Provision a Cloudflare zone for whatever domain you'll point at the
   dashboard (e.g. `agrim.ai`).
2. Point a CNAME `judge.agrim.ai` at the Railway dashboard service's public
   URL. Repeat for the intake service.
3. Cloudflare Zero Trust → Access → Applications → **Add an application**
   (Self-hosted).
   - Application domain: `judge.agrim.ai`.
   - Policy: `Allow when email ends in @agrim.ai`. Optional: also allow
     specific judge emails for external collaborators.
4. Cloudflare injects `Cf-Access-Authenticated-User-Email` on every
   request. [`dashboard/app.py`](dashboard/app.py) `_judge_identity()`
   reads it ahead of the basic-auth username, so the override audit trail
   automatically upgrades to real email attribution.
5. **Clear** the basic-auth env vars on the dashboard service so the
   Streamlit shim becomes a no-op and Cloudflare is the only gate.
6. Repeat for the intake form domain. During the hackathon window flip the
   Access policy to `Bypass for candidate IP range` or `Allow everyone`,
   then re-lock after.

No code change is required to migrate from basic auth to Cloudflare Access;
the audit trail simply switches from the shared username to the
per-request email.
