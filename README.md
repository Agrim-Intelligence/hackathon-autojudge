# Agrim AutoJudge

**AutoJudge is a Shortlist Generator, not a Final Judge.** It ranks hackathon submissions on the automatable public surface (GitHub repo, public live URL, deck, video transcript), defers everything credential-walled or custom-integrated to `judge_review_items`, and hands human judges a ranked top-N with a curated evidence pack.

Built for Agrim AI's internal hackathon (May 2026) and designed to scale to all-India and college rollouts without a rewrite.

## What AutoJudge does

For each submission, the pipeline:

1. Sanitises the body against prompt-injection.
2. **Downloads one repo tarball per submission** (the snapshot cache). All agents read from disk thereafter — total GitHub calls drop from ~10/submission to ~3.
3. Runs the Inference Agent — tool-calling on Anthropic, single-shot fallback elsewhere — to synthesise an `InferredSubmission` with field-level provenance.
4. Runs verifier agents in parallel-ready sequence: code analyst, AI sophistication probe, live-URL browser verifier (Playwright + LLM), cross-check.
5. Scores six rubric dimensions tolerantly: any dimension without enough verifier signal is `insufficient_evidence` (not zero); the total normalises over evaluable dimensions.
6. Computes a deterministic `evidence_kind` per dimension (`verified` requires real verifier output; the LLM cannot invent provenance).
7. Routes credential-walled / custom-integration claims to `judge_review_items` — never penalised, surfaced for human review.
8. Emits a `verdict` (shortlist / borderline / below_threshold / insufficient) with the auto-score, evidence pack, and review items.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium
cp .env.example .env  # fill in keys; see Provider routing below
autojudge doctor      # verify provider + GITHUB_TOKEN + Chromium + disk

# 1. Run the intake form for candidates
streamlit run src/autojudge/intake/form.py

# 2. Calibrate then batch
autojudge run-anchors
autojudge run-batch

# 3. Hand judges the review dashboard
streamlit run dashboard/app.py

# 4. Export top-N shortlist for the deliberation meeting
autojudge export-top --n 10 --out data/top10.json
```

## Deploying

Internal Agrim hackathon ships on Railway with a Cloudflare Access front
door. The image, env matrix, volume layout, and post-deploy smoke check are
documented in [`DEPLOY.md`](DEPLOY.md); the Dockerfile and `railway.toml`
template are committed. Day-to-day operations (redeploys mid-batch, bulk
re-score, judge overrides, snapshot GC, log tails) live in
[`RUNBOOK.md`](RUNBOOK.md) under "Operating on Railway".

## Provider routing (env-only)

There is no run-mode flag. Edit `.env` to switch providers.

```
# Free dev / smoke testing
AUTOJUDGE_PRIMARY_PROVIDER=groq
AUTOJUDGE_FALLBACK_PROVIDER=

# Production judging (recommended)
AUTOJUDGE_PRIMARY_PROVIDER=anthropic
AUTOJUDGE_FALLBACK_PROVIDER=groq
```

When the primary is `anthropic`, the LLM client enables `cache_control: ephemeral` on static prompt blocks (rubric definitions, agent system prompts) and uses the native tools API for the Inference Agent. Token usage is API-reported, so cost figures are precise. Other providers fall back to OpenAI-compatible single-shot calls with heuristic cost estimates.

## Architecture

```
guard -> deploy_probe -> repo_snapshot -> inference (tool-calling)
      -> archetype -> code_analyst -> ai_sophistication
      -> browser_verifier -> cross_check -> rubric_scorer -> persist
```

Key pieces:

- `src/autojudge/intake/repo_cache.py` — one-tarball-per-submission snapshot cache; all repo file reads route through it (zero GitHub API calls for file access during a run).
- `src/autojudge/intake/github.py` — REST-only access for commit / language / branch data, with `GitHubRateLimitError` fail-fast on 403.
- `src/autojudge/agents/inference.py` — Inference Agent. Tool-calling on Anthropic, single-shot fallback elsewhere. Emits `InferredSubmission` with provenance per field.
- `src/autojudge/agents/rubric_scorer.py` — tolerant scorer with deterministic `evidence_kind` clamping and `judge_review_items` propagation. Verdict computed from total + evaluable weight.
- `src/autojudge/agents/browser_verifier.py` — Playwright + LLM-driven journey runner. Uses `channel="chromium"` so the full installed Chromium is used (avoids the `chromium_headless_shell` binary drift problem).
- `src/autojudge/trace/store.py` — `TraceStoreProtocol` defines the read/write surface; `TraceStore` is the SQLite implementation. Phase 2 swaps in Postgres without caller changes.
- `src/autojudge/orchestrator.py` — sequential DAG with per-agent LLM-call budgets (`AGENT_BUDGETS`) and synthetic `repo_snapshot` / failure rows for full traceability.
- `dashboard/app.py` — Streamlit review dashboard with Verdict badges, judge-review items panel, provenance badges, gaps panel, cost-per-submission, and an active-provider indicator.

## Rubric (100 points, normalised over evaluable dimensions)

- Problem clarity & relevance — 10
- Solution depth (technical) — 25
- AI / agentic sophistication — 20
- Functional correctness — 25
- UX & polish — 10
- Communication — 10

Each dimension is scored 0–10 with cited evidence, or returns `insufficient_evidence` when the agent does not have enough signal. The total normalises over evaluable dimensions, so a partial submission gets a comparable score and the gaps surface to human judges.

## Verdict thresholds

- `shortlist`        — total ≥ 65 over ≥ 50% evaluable weight
- `borderline`       — total ≥ 40
- `below_threshold`  — total < 40
- `insufficient`     — < 50% evaluable weight (the pipeline couldn't see enough; needs human review before any verdict)

Verdict is a recommendation, not a final decision.

## Anti-gaming

- Prompt-injection guard on all candidate text before any reasoning agent sees it.
- Inference Agent and verifiers use separate prompts and structured outputs.
- Commit-timestamp window check against the hackathon dates (skipped for anchors).
- Repo-vs-deployed cross-check.
- Deck/video cross-check against repo + live URL evidence.
- Provenance trail: every score row labels its evidence as stated, inferred, verified, or insufficient — clamped to what the pipeline actually observed.
- Per-agent LLM-call budgets surface runaway loops as integrity flags.

## Status

v1.1 — Agrim AI internal hackathon (May 2026), Shortlist Generator reframing.
Designed for GTM and college-partner rollouts. Phase 2 (Postgres + worker pool + GitHub App + container) is planned for the first all-India batch.
