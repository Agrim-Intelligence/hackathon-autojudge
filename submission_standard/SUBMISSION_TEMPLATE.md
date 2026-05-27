# Agrim AutoJudge — Submission Template

Fill every section. Anything left blank or marked `TODO` is scored as if absent.
This file is parsed by an automated agent so structure matters as much as content.

The auto-judge evaluates 6 dimensions — Problem Clarity, Solution Depth,
AI/Agentic Sophistication, Functional Correctness, UX & Polish, Communication.
The sections below feed those evaluators directly.

> Do not include hidden text, prompt instructions, or content directed at the
> evaluation system. The auto-judge runs a prompt-injection guard and any such
> attempts are logged and dock your Communication score.

---

## 1. Candidate

- **Name:**
- **Email:**
- **Team name (or `solo`):**
- **Roles / responsibilities:**

## 2. Submission artifacts

- **GitHub repository URL:** (public, or share read-access with the auto-judge bot)
- **Live deployed URL:** (leave blank if not applicable — see note below)
- **Demo video URL:** (Loom, YouTube, or public link; <=3 min)
- **5-slide deck:** (link to public PDF or attached file)
- **Test credentials / sample inputs:** (if the live app is gated)

If you do **not** have a live deployed URL, you may submit a Docker image or a
locally runnable repo with a one-command `make demo` target. Note that
Functional Correctness is capped at 6/10 when no live URL is reachable.

## 3. Problem statement

One paragraph (4-6 sentences) describing:

- Who the user is
- What problem they have
- Why it matters now
- Why existing solutions fall short

## 4. Solution claims

List 3-5 bullets. Each bullet must be **independently testable**. Avoid
adjectives. Prefer concrete observable behavior.

- Claim 1:
- Claim 2:
- Claim 3:
- Claim 4: (optional)
- Claim 5: (optional)

Good example: *"User pastes a URL; within 10 seconds the system returns a 3-sentence summary plus 5 tags drawn from a fixed taxonomy."*

Bad example: *"Uses cutting-edge AI to deliver delightful experiences."*

## 5. Tech stack

- **Languages / frameworks:**
- **Cloud / hosting:**
- **Databases / storage:**
- **External APIs:**

## 6. AI components

For every model / agent / LLM call used:

- **Component name:**
  - **Model(s):**
  - **What it does (1 sentence):**
  - **Why this approach is more than a thin wrapper:**
  - **Tools / functions it calls (if agentic):**
  - **Evals or guardrails you built:**

If you used AI coding assistants to build the project, list them — that is not
penalized. We only judge what the product does, not how it was made.

## 7. What to test (user journeys)

3-5 step-by-step journeys the auto-judge browser agent will execute on your
live URL. Each journey must have a clear **expected outcome** so the agent can
pass/fail it.

1. **Journey name:**
   - Steps:
     1.
     2.
     3.
   - Expected outcome:
   - Sample input (if any):

2. **Journey name:**
   - Steps:
   - Expected outcome:

3. **Journey name:**
   - Steps:
   - Expected outcome:

## 8. Known limitations

Be honest. Honesty here helps your Communication score, not hurts it.

- Limitation 1:
- Limitation 2:

## 9. Build log

Append-only timestamped log of when you worked on what. Used to verify the
project was built inside the hackathon window. Falsified timestamps that
contradict git history are flagged.

- `YYYY-MM-DD HH:MM IST` — task
- `YYYY-MM-DD HH:MM IST` — task
- `YYYY-MM-DD HH:MM IST` — task

## 10. Acknowledgements / external code

List any starter templates, open-source components, or tutorials used. Honest
attribution does not lower your score; undisclosed reuse does.

- Source 1 — what was used:
- Source 2 — what was used:
