---
name: security-review
description: >
  Use WHEN reviewing a change that touches auth, user data, external inputs, billing, or public endpoints.
  Triggers on: "security", "auth", "permissions", "PII", "external API", "public endpoint", "rate limit", "token".
when_to_use: Use to threat-model any change that could expose a security surface — auth, input validation, data access, dependencies.
when_not_to_use: Internal config change with no external surface, no auth/data involvement.
inputs: [diff or route/handler/area to review, data classes involved (auth? PII? billing?)]
read_first: [the diff or handler and its call graph, docs/contexts/<latest>.md, auth/authz middleware in the project]
outputs: security_review.md
hard_stops: [critical finding → halt the change, escalate immediately, compliance regime (SOC2/GDPR) → loop in eng lead]
---

# security-review

> Threat-model the change. Catch things before the public internet does.

## Goal
For a given change set or endpoint, produce a threat-modelled review with findings, severities, and concrete remediations.

## Steps
1. List the entry points the change exposes or modifies.
2. For each entry point: who can call it? authenticated? authorised? rate-limited?
3. Trace data flow: inputs → validation → persistence → outputs.
4. Run the eight-point checklist. One bullet per item; "n/a" with reason if truly not applicable.
5. Assign severity to each finding: `critical` / `high` / `med` / `low` / `info`.
6. Propose a concrete remediation for each non-info finding.

## Eight-Point Checklist

1. **authn** — is the caller identified, correctly?
2. **authz** — does the caller have the right to do this?
3. **input validation** — every external input typed and bounded?
4. **injection surfaces** — SQL, command, template, prompt, log?
5. **PII / secrets** — anything sensitive in responses, logs, errors?
6. **rate / cost** — can a single caller exhaust budget?
7. **dependencies** — any new packages? trusted? pinned?
8. **failure modes** — does the change fail open or fail closed under stress?

## Gates
- Every finding has a severity AND a concrete remediation
- "n/a" lines explain why, not just blank
- Critical or high finding → also appears in the plan's risks section

## Stop When
- A finding is `critical` → halt the change immediately, escalate before any further work
- The area touches an external compliance regime (SOC2, GDPR, PCI) → loop in eng lead

## Output Schema → `security_review.md`

```markdown
# security review · <slug or route>

## summary
<X> critical · <Y> high · <Z> med · <N> low
ready to ship: <yes / no / not without remediation>

## entry points
- <method> <route> · auth: <kind> · authz: <rule>

## findings
[S1] severity:high — authz — <where> — <what> — fix: <how>
[S2] severity:med  — input — <where> — <what> — fix: <how>

## checklist trace
1. authn — <one line>
2. authz — <one line>
3. input validation — <one line>
4. injection surfaces — <one line>
5. PII / secrets — <one line>
6. rate / cost — <one line>
7. dependencies — <one line>
8. failure modes — <one line>
```
