# Agrim AutoJudge — Submission

## 1. Candidate

- **Name:** Mayank Singh Tomar
- **Email:** mayank.tomar@agrim.ai
- **Team name (or `solo`):** solo
- **Roles / responsibilities:** Full-stack — Remotion video composition, Hono API and collectors, Vite/React admin UI, Slack integration, Railway deployment

## 2. Submission artifacts

- **GitHub repository URL:** https://github.com/mstomar-ag/Wrapped
- **Live deployed URL:** https://inspiring-bravery-production.up.railway.app
- **Demo video URL:**
- **5-slide deck:** data/submissions/20260525-040054-mayank-singh-tomar/deck.pdf
- **Test credentials / sample inputs:** Web UI requires Google sign-in with an `@agrim.ai` account. Slack slash command (`/wrapped @user last-week`) requires workspace bot access and is not testable without Agrim Slack credentials. For API-only testing without auth, `GET /api/health` returns 200.

## 3. Problem statement

Engineering teams produce a steady stream of work signals — Slack messages, GitHub commits, tickets, posts — but that activity is scattered across tools and rarely surfaces in a form teammates actually enjoy sharing. Managers and peers want a lightweight, celebratory way to recognize someone's week without asking that person to connect accounts or fill out a form. Existing analytics dashboards are utilitarian and private; generic "year in review" templates don't pull real workspace data or ship as a shareable vertical video inside the tools teams already use. Wrapped addresses this by turning a teammate's recent activity into a ~25-second, 1080×1920 Spotify-Wrapped-style reel, triggered from Slack with zero end-user setup.

## 4. Solution claims

- Claim 1: Running `/wrapped @alice last-week` in Slack acknowledges within 3 seconds, collects workspace signals in the background, renders an MP4, and posts the video back to the channel where the command was run.
- Claim 2: The rendered reel is ~25 seconds (9 Remotion scenes at 30 fps) and includes numeric stats, peak hour, top emoji, longest thread, hero commit, ghost-mode streak, and LLM/heuristic copy (week title + vibe).
- Claim 3: Collectors for Slack, GitHub, and X are implemented; missing credentials cause individual collectors to return null and the aggregator falls back to DUMMY values so a reel still renders.
- Claim 4: The web UI at the live URL lets a signed-in user pick a member and date window on the Generate page, trigger a wrap, and browse all previously rendered wraps in a shared org-wide Archive.
- Claim 5: Rendered MP4s are content-hash cached under `out/cache/<sha>.mp4` so identical WrappedData reuses the existing file instead of re-rendering.

## 5. Tech stack

- **Languages / frameworks:** TypeScript (strict, ESM), Remotion (React video), Hono (API), Vite + React + React Router (web UI), Vitest
- **Cloud / hosting:** Railway (production); Docker + Makefile for local/prod-like runs; legacy Railway host redirects to GCP via `REDIRECT_TO`
- **Databases / storage:** File-backed JSON (`data/members.json`, `data/archive.json`, `data/schedule.json`, AES-GCM encrypted `data/tokens.json`); MP4 cache on disk (`out/cache/`); HS256 session cookie (stateless)
- **External APIs:** Slack (bot + slash command), GitHub, X/Twitter, Linear, Notion; optional per-user OAuth stubs for LinkedIn/Gmail; LLM providers for copy (Groq, Gemini, OpenRouter, Anthropic)

## 6. AI components

- **Component name:** Copy generator (`server/copy.ts`)
  - **Model(s):** Configurable chain — default order Groq → Gemini → OpenRouter (`qwen/qwen3-next-80b-a3b-instruct:free`) → Anthropic (`claude-haiku-4-5-20251001`); overridable via `COPY_PROVIDERS`
  - **What it does:** Given aggregated weekly signals, produces JSON with `weekTitle`, `vibe`, and `commitSummary` for on-screen reel copy.
  - **Why this approach is more than a thin wrapper:** Structured system prompt with tone rules, word limits, banned phrases, and ticket-ID stripping; multi-provider fallback chain; JSON extraction/parsing with heuristic fallback when all providers fail.
  - **Tools / functions it calls:** None — single-shot text generation, not agentic.
  - **Evals or guardrails you built:** Hard output constraints in prompt (max words, no emoji/exclamation); `parseOverrides` validation; provider failure logging; empty return triggers deterministic heuristic copy in the aggregator.

If you used AI coding assistants to build the project, list them — that is not
penalized. We only judge what the product does, not how it was made.

- **AI coding assistants used:** Claude (Cursor / Claude Code) for implementation, scene design skills, and documentation.

## 7. What to test (user journeys)

1. **Landing page loads**
   - Steps:
     1. Open https://inspiring-bravery-production.up.railway.app
     2. Wait for the React app to render
     3. Verify the page title or branding mentions "Wrapped"
   - Expected outcome: A dark-themed Wrapped web app shell loads without a server error.
   - Sample input: none

2. **Health check (no auth)**
   - Steps:
     1. Open `https://inspiring-bravery-production.up.railway.app/api/health`
     2. Read the response body
   - Expected outcome: HTTP 200 with a JSON health payload confirming the API is up.
   - Sample input: none

3. **Browse archive (authenticated)**
   - Steps:
     1. Open the live URL and sign in with an `@agrim.ai` Google account when prompted
     2. Navigate to the Archive page from the sidebar
     3. Verify a list of previously rendered wraps appears (or an empty-state message if none exist)
   - Expected outcome: Archive page renders and displays wrap entries with member name and date metadata, or a clear empty state.
   - Sample input: `@agrim.ai` Google account

4. **Generate a wrap from the UI (authenticated)**
   - Steps:
     1. Sign in with an `@agrim.ai` Google account
     2. Open the Generate page
     3. Select a member from the dropdown and a preset window (e.g. "last-week")
     4. Click generate and wait for completion
   - Expected outcome: The UI shows a success/processing state and the new wrap appears in the Archive; the wrap is saved server-side but is not auto-posted to Slack.
   - Sample input: any member listed in the dropdown, window = `last-week`

5. **Watch a rendered wrap**
   - Steps:
     1. From the Archive page, click an existing wrap entry
     2. Open the watch/detail view
     3. Verify an MP4 video player loads and plays a vertical reel
   - Expected outcome: A ~25-second 1080×1920 video plays showing multiple animated scenes (intro, stats, vibe, etc.).
   - Sample input: any archived wrap entry

## 8. Known limitations

- LinkedIn and Gmail collectors are stubs requiring per-user OAuth; they are optional enrichments, not part of the core v1 flow.
- The org-wide archive is intentionally unfiltered — every signed-in `@agrim.ai` user sees all wraps; there is no per-user privacy toggle enabled yet.
- Slack slash-command flow cannot be exercised by the browser agent without Agrim workspace Slack credentials; primary browser testing is via the web UI and `/api/health`.
- No demo video URL submitted; evaluators should rely on the live deployment and attached deck.
- Linear/Notion/X collectors require additional API keys that may not be configured in production; missing sources fall back to dummy data for those slides.

## 9. Build log

- `2026-05-23 16:41 IST` — Initial deployment docs and project scaffolding
- `2026-05-23 16:44 IST` — Railway deploy docs, faster Slack wraps, named render outputs
- `2026-05-23 17:20 IST` — Archive filter fix, IST standardization, Slack render ETA copy
- `2026-05-23 19:05 IST` — Wrapped UX improvements, data collection, theme rotation
- `2026-05-23 19:07 IST` — Site manifest, asset handling, layout branding
- `2026-05-23 19:52 IST` — Deployment setup, asset management, data seeding
- `2026-05-24 23:32 IST` — Quality toggle (standard vs HD), redirector mode, EPIPE-resilient render
- `2026-05-24 23:55 IST` — 720p layout overflow fix, Slack `new` flag to bypass render cache
- `2026-05-25 00:15 IST` — Restore multi-provider AI copy chain + faststart MP4 muxing

## 10. Acknowledgements / external code

- Remotion — programmatic React-based video rendering framework
- Hono — lightweight HTTP server for API routes and static frontend serving
- CC0 background music tracks in `public/music/` (deterministic rotation per handle via `pickTrack`)
- Spotify Wrapped — conceptual inspiration for the reel format and shared social-object framing
- `.claude/skills/design-reel-scene/` — internal Claude skill used for scene design conventions
