# meeting-notes-agent

solo hack by anchor-strong (anchors@agrim.ai)

## what it is

Slack bot + web app that turns a meeting recording (or a posted Slack thread)
into action items, owner assignments, and a follow-up calendar invite. The
agent runs as a 3-step LangGraph state machine (transcribe -> extract ->
plan), with structured outputs validated against a pydantic schema and a
human-in-the-loop step where the requester confirms owners before the agent
posts back to Slack.

repo: https://github.com/example/meeting-notes-agent
live: https://meeting-notes-agent.fly.dev/  (login: demo@agrim.ai / hackathon)
deck: 4 slides describing the loop, architecture, and an eval result
video: https://www.youtube.com/watch?v=dQw4w9WgXcQ  (3 min walkthrough)

## what works today

- Slack slash command `/notes <thread-link>` -> within ~12s the bot replies
  with a summary, an action-items list, and a "confirm owners" interactive
  message. After confirmation it creates the follow-up event in Google
  Calendar.
- Web app at the live URL shows the same flow for a manually-pasted
  transcript and a small dashboard of every run including the pydantic
  validation outcome per step.
- Eval harness in `evals/` runs 12 golden conversations and checks
  precision/recall on extracted action items; current run scores 0.83/0.78.
- Prompt-injection guard is wired in front of every user-supplied text.
  False positives are logged into `data/guard_log.json` so we can iterate.

## tech

python 3.12, langgraph 0.2, anthropic claude-haiku for extraction and
claude-sonnet for the planner, postgres for persistence, fly.io for hosting.
small react front-end (vite). 87% of code by line count is python.

## what's testable

- Posting `/notes https://...slack-link` returns within 15s with an action
  items message containing at least one assigned owner.
- POSTing a transcript to `/api/notes` returns a JSON object with
  `action_items: [{owner, due, text}]` validating against the documented
  schema.
- `GET /api/health` returns 200 and the running model versions.
- `evals/golden/*.json` are runnable via `make eval`.

## what doesn't

- Speaker diarization on audio is poor; we recommend candidates use the
  pre-transcribed Slack thread path until v1.1.
- Calendar integration requires google workspace; for personal gmail it
  drops to a downloadable .ics file.
- No row-level multi-tenancy yet; everyone on a workspace sees every run.

## build log (commits + my notes)

2026-05-23 09:14 IST  scaffolding + first prompt
2026-05-23 12:02 IST  langgraph state machine working end-to-end
2026-05-23 15:30 IST  slack slash command + interactive ack
2026-05-23 19:45 IST  pydantic schema validation per step
2026-05-23 22:10 IST  eval harness + golden conversations
2026-05-23 23:50 IST  fly.io deploy + auth
2026-05-24 02:20 IST  prompt-injection guard wired
2026-05-24 09:10 IST  calendar invite path
2026-05-24 14:00 IST  3-min video + slides

## acknowledgements

- LangGraph examples for the state machine skeleton
- Slack `bolt-python` starter
- A friend's vite+react template
- Used Cursor with Claude Sonnet 4 for code completion throughout
