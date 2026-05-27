# Hackathon submission — action required

Hi team,

Submissions for the Agrim hackathon are open. Please submit **within the deadline** so we can shortlist fairly.

## What to send (1 minute)

At minimum, send **one** of these:

- a GitHub repo URL, **or**
- a live deployed URL, **or**
- a demo video URL (YouTube, ≤3 min), **or**
- a slide deck (PDF)

Everything else is optional. Don't worry about formatting, sections, or a specific template. The auto-judge reads whatever you provide, infers structure, and shortlists you based on real evidence.

## How shortlisting works (so you can submit smart)

AutoJudge produces a **shortlist**, not a final score. Human judges then pick the winners from the shortlist. We rank you on what we can verify from the public surface of your work — repo code, public live URL, deck slides, video transcript.

Things AutoJudge **cannot** verify (and therefore won't penalise) — they're flagged for human judges instead:

- Slack / Discord bot integrations (we don't have your workspace)
- OAuth / paid-API features that need your credentials
- Hardware demos / IoT devices
- Anything behind a login wall

If your project has these, **mention them in your free-form notes**. They become judge-review items and your human judge will verify them with you in the deliberation meeting.

## How to send it

Open the intake form: **http://localhost:8501** (or the LAN URL the organisers shared).

Fill the candidate fields (name, email, team). Drop in any of the URLs above. Add free-form notes if you want to point judges at specific things — what problem you solved, what to try first, what's broken, what needs credentials. Free-form notes are optional.

If the form is unreachable, you can submit from your terminal:

```
autojudge ingest-flexible --name "Your Name" \
  --repo https://github.com/... --live https://...
```

## A few things worth knowing

- AutoJudge attributes every score to specific evidence (`stated` by you, `inferred` from your artifacts, or `verified` by a tool). Internal judges see the full provenance trail and decide.
- If you have a live URL with auth, mention any test credentials in your free-form notes; the browser verifier can sign in.
- Honest "what doesn't work" notes help your Communication score. Pretending things work when they don't gets caught by cross-check.
- Don't put instructions directed at the auto-judge in your notes. Those attempts are logged and dock your Communication score.

That's it. You don't need to do anything else after submitting. Internal judges review the ranked output and pick the winners from the shortlist.

Questions? Ping the hackathon organisers.

— Agrim AI
