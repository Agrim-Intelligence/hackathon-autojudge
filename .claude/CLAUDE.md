# CLAUDE.md

> Agrim AI · how we work with the model.
> Read this file first. Then `.claude/project-rules.md`. Then run the loop.

This is the contract between every engineer here and any AI tool they invoke — Claude Code, Claude in chat, Cursor, anything that lands a diff. It merges Agrim's house rules with four behavioural guardrails adapted from Andrej Karpathy's `CLAUDE.md` (see appendix).

The tradeoff these rules make: **caution over speed**. For trivial tasks, use judgement.

**How the system works:** Skills live in `.claude/skills/` and are natively discovered by Claude Code. A SessionStart hook loads `getting-started` at session open. The agent invokes the relevant skill before any non-trivial action — automatically, without typing commands. Slash commands (`/debug-issue`, `/plan-feature`, etc.) in `.claude/commands/` are direct shortcuts.

---

## House rules

### 1. Always start with project-context
Even for one-line fixes. Especially for one-line fixes. The model doesn't know your repo until you tell it — and it will *invent* plausible-sounding architecture if you don't. Build the shared ground truth first; spend the 90 seconds. The harness will prompt you; `/project-context` also works as a shortcut.

### 2. No code without a plan
If `docs/plans/<slug>.md` doesn't exist, you're not implementing — you're guessing. Run `/plan-feature` first. Anything bigger than a 5-line typo fix gets a plan. The plan is what gets reviewed, the diff is what gets merged.

### 3. Surgery over rewrite
Touch only what you must. Every changed line must trace to a line in the plan. No drive-by refactors. No "improving" adjacent code, comments, or formatting. Match the existing house style — even if you would write it differently. Conformity ships faster.

### 4. Reproduce, then fix
No "let me try this and see" without a failing test first. The order is non-negotiable: **bug → write reproducing test → red → fix → green**. `/debug-issue` enforces this. If the test is hard to write, the bug is harder to fix — that is the signal, not the problem.

### 5. Route every lesson — don't just re-prompt
When a lesson surfaces, send it to the right store. Four questions, in order (full text in `docs/decisions/README.md`):
1. **A linter / CI / type-checker can enforce it?** → add the mechanical gate, not prose. *Scarce always-on attention is never spent on what a machine can catch.*
2. **The skill or process itself is wrong (misfires in any repo)?** → `improvement-plan` → PR to `.claude/skills/`.
3. **Rationale worth re-reading (why we chose X)?** → `record-decision` → ADR. *Most lessons stop here.*
4. **Must gate every future plan/review in this repo, judgment-only, repo-specific?** → also a **design-watch** in `docs/decisions/design-watches.md` (capped ~10-12, each with a retire-when condition).

A correction taught twice in one week is question 2. A skill not updated in 60 days has a label that says so.

### 6. When in doubt, stop and ask
Ambiguity is the only thing that costs more than rework. If the ask has two reasonable interpretations, surface both — never pick silently. If you need information the user has and you do not, say so. The skill's `stop_when` clauses exist for a reason.

---

## Hard stops · the model must not proceed silently

The model **must hand back to a human** before:

- **Destructive operations.** DELETE, DROP, TRUNCATE, `rm -rf`, force-pushes to shared branches.
- **Auth / billing / data of consequence.** Identity, permissions, payment paths, PII-bearing tables. Even "just a one-liner".
- **Secrets and environment.** API keys, env vars, third-party tokens, anything in `.env` or a secret manager. Never echo. Never commit. Never paste back.
- **Cross-team contracts.** Public APIs, event shapes, exported types, anything another team consumes. Ping the consumer before the diff.
- **Anything not covered by the active skill's `stop_when`.** When in doubt: stop.

The right behaviour at a hard stop is a structured handback — not a guess.

---

## How a session goes

The harness starts it. The SessionStart hook fires, the agent reads `getting-started` from the native Skill tool, and invokes the relevant skill before any action.

A normal session produces these artifacts in order:

| Step | Skill | Artifact |
|---|---|---|
| 0 (exploratory) | `brainstorm` | `docs/specs/<slug>.md` |
| 1 | `project-context` | `docs/contexts/<slug>.md` |
| 2 | `plan-feature` | `docs/plans/<slug>.md` |
| 3 | `implement-slice` | `implementation_notes.md` |
| 3a | `verification-before-completion` | appended to notes |
| 4 | `test-change` | `test_report.md` |
| 5 | `review-change` | `review.md` |
| 5a | `receiving-code-review` | updated `review.md` |

For multi-task plans, workflow skills wrap the implement loop:
`using-git-worktrees` → `subagent-driven-development` → `finishing-a-development-branch`

Risk skills (`debug-issue`, `security-review`, `contract-check`, `migration-check`) and delivery skills (`release-check`, `work-summary`, `improvement-plan`, `maintain-context`) interleave as needed. The order above is the spine, not the law.

**Slash commands** (`/project-context`, `/plan-feature`, etc.) are optional shortcuts — the harness invokes the right skill automatically. Use them when you want to explicitly trigger a skill outside the auto-trigger flow.

---

## Where things live

```
.claude/                   ← copy into every Agrim repo (.claude/ IS the product)
├── CLAUDE.md              ← this file (Agrim house rules + guardrails)
├── project-rules.md       ← per-repo: test command, no-go zones, owners (gitignored)
├── project-rules.template.md ← blank template — copy → project-rules.md on install
├── settings.json          ← hook config + skillOverrides (commit this)
├── hooks/
│   ├── session-start.sh   ← fires at session open; injects getting-started + install self-check
│   ├── prompt-reminder.sh ← UserPromptSubmit; re-injects the loop reminder each turn
│   ├── plan-gate.sh       ← PreToolUse; denies source edits with no current plan
│   └── completion-gate.sh ← Stop; blocks finishing when source changed without plan/tests
├── lib/
│   └── setup.sh           ← create worktree + verify clean baseline
├── agents/
│   ├── code-reviewer.md   ← two-stage review subagent
│   ├── implementer.md     ← per-task implementation subagent
│   └── plan-executor.md   ← orchestrates subagent loop
├── commands/              ← optional slash shortcuts (/plan-feature, /debug-issue, etc.)
└── skills/                ← 23 skills, natively discovered by Claude Code
    │
    │   ── core (11) ──────────────────────────────────────────────────────
    ├── getting-started/           ← loaded at session open via SessionStart hook
    ├── brainstorm/                ← explore before planning → docs/specs/<slug>.md
    ├── project-context/           ← ground truth snapshot → docs/contexts/<slug>.md
    ├── plan-feature/              ← plan before coding → docs/plans/<slug>.md
    ├── implement-slice/           ← one slice at a time
    ├── test-change/               ← RED → GREEN → REFACTOR
    ├── review-change/             ← dispatches code-reviewer subagent → review.md
    ├── receiving-code-review/     ← respond to review findings; re-review if Critical
    ├── verification-before-completion/ ← 5-point done-gate before review
    ├── externalize-architecture/  ← document repo structure → docs/contexts/architecture/
    ├── record-decision/           ← capture decision + rationale → docs/decisions/YYYY-MM.md
    │
    │   ── risk (4) ────────────────────────────────────────────────────────
    ├── debug-issue/               ← reproduce → red test → fix → green
    ├── security-review/           ← auth/PII/input-trust audit
    ├── contract-check/            ← breaking-change detection for public APIs
    ├── migration-check/           ← safe data migration verification
    │
    │   ── delivery (4) ───────────────────────────────────────────────────
    ├── release-check/             ← pre-release readiness gate
    ├── work-summary/              ← session trail → docs/summaries/<slug>.md
    ├── improvement-plan/          ← skill + process retrospective
    ├── maintain-context/          ← bi-weekly health pass on all context stores
    │
    │   ── workflow (3) ───────────────────────────────────────────────────
    ├── using-git-worktrees/       ← isolated branch + worktree before implement
    ├── subagent-driven-development/ ← parallel-task orchestration via subagents
    ├── finishing-a-development-branch/ ← PR / merge / cleanup after all tasks done
    │
    │   ── meta (1) ────────────────────────────────────────────────────────
    └── writing-skills/            ← how to author, pressure-test, and PR a skill

docs/
├── contexts/              ← project-context + architecture artifacts
├── specs/                 ← brainstorm artifacts
├── plans/                 ← plan-feature artifacts
├── decisions/             ← record-decision append-only log + design-watches.md (review-gate register)
├── reviews/               ← review-change artifacts
├── summaries/             ← work-summary artifacts
└── improvements/          ← improvement-plan artifacts
```

---

## Behavioural guardrails

Adapted from `github.com/multica-ai/andrej-karpathy-skills/CLAUDE.md`. These apply at every step, in every skill.

### 1 · Think before coding
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — do not pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what is confusing. Ask.

### 2 · Simplicity first
- Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that was not requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

### 3 · Surgical changes
- Do not "improve" adjacent code, comments, or formatting.
- Do not refactor things that are not broken.
- Match existing style, even if you would do it differently.
- Notice unrelated dead code? Mention it. Do not delete it.
- Remove imports/variables/functions *your* changes made unused. Leave the rest.
- Every changed line traces directly to the user's request.

### 4 · Goal-driven execution
- Transform tasks into verifiable goals.
  - "Add validation" → "Write tests for invalid inputs, then make them pass."
  - "Fix the bug" → "Write a test that reproduces it, then make it pass."
  - "Refactor X" → "Ensure tests pass before and after."
- For multi-step tasks, state a brief plan with explicit verify-steps.
- Strong success criteria let you loop independently. Weak criteria need constant clarification.

**These guidelines are working if:** fewer unnecessary lines in diffs, fewer rewrites due to overcomplication, and clarifying questions come *before* implementation rather than *after* mistakes.

---

## How this file changes

Open a PR. Tag `@skills-lead`. Discussed in the weekly skill review. Merged with a dated entry in the changelog at the bottom. No silent edits.

## Changelog

- Initial rollout. 12 skills + 4 guardrails + 6 house rules.
- 2026-05-29. Harness upgrade: SessionStart hook + `find-skill.sh` + 17 skills in 5-category layout + 3 agents + workflow engine. Flat `01-12-*.md` files retired.
- 2026-06-03. Go-native: `claude-config/` removed. Skills live in `.claude/skills/` (flat, natively discovered). `find-skill.sh` removed. Native Skill tool + slash commands replace script-based discovery. Reviewer-diff bug fixed. `skillOverrides` suppresses conflicting built-ins.
