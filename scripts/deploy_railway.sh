#!/usr/bin/env bash
#
# Agrim AutoJudge — one-shot Railway deployment (v1.2, CLI >= 4.65).
#
# Creates / refreshes two services (dashboard + intake) connected to the
# GitHub repo, wires them to a shared Postgres, attaches a volume to the
# dashboard, and generates public URLs. Both services run the SAME image and
# differ only by AUTOJUDGE_ROLE.
#
# Prerequisites (do these once, in the Railway dashboard / your shell):
#   1. Install + log in:   railway login
#   2. Create a project, then in the repo root:   railway link
#   3. Add Postgres (skipped automatically if it already exists).
#
# Required env vars in your shell BEFORE running (secrets — never committed):
#   ANTHROPIC_API_KEY
#   GITHUB_TOKEN
# Optional (sensible defaults applied if unset):
#   GROQ_API_KEY GEMINI_API_KEY OPENROUTER_API_KEY
#   AUTOJUDGE_PRIMARY_PROVIDER=anthropic
#   AUTOJUDGE_FALLBACK_PROVIDER=groq
#   AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER=agrim-judge
#   AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS=(generated if unset; printed once)
#   AUTOJUDGE_INTAKE_BASIC_AUTH_USER / _PASS (leave empty for public intake)
#   AUTOJUDGE_HACKATHON_START / _END
#   GIT_REPO=Agrim-Intelligence/hackathon-autojudge
#
# Re-running is safe: services are created only if absent, variables are
# upserted, deploys are re-triggered.

set -euo pipefail

RAILWAY_BIN="${RAILWAY_BIN:-railway}"
if ! command -v "${RAILWAY_BIN}" >/dev/null 2>&1; then
    if [[ -x "${HOME}/.railway/bin/railway" ]]; then
        RAILWAY_BIN="${HOME}/.railway/bin/railway"
    else
        echo "ERROR: railway CLI not found. Install it and run 'railway login'." >&2
        exit 1
    fi
fi

"${RAILWAY_BIN}" whoami >/dev/null 2>&1 || { echo "ERROR: run 'railway login' first." >&2; exit 1; }
"${RAILWAY_BIN}" status >/dev/null 2>&1 || { echo "ERROR: run 'railway link' in the repo root first." >&2; exit 1; }

require_env() { [[ -n "${!1:-}" ]] || { echo "ERROR: ${1} must be set in your shell." >&2; exit 1; }; }
require_env ANTHROPIC_API_KEY
require_env GITHUB_TOKEN

GIT_REPO="${GIT_REPO:-Agrim-Intelligence/hackathon-autojudge}"
AUTOJUDGE_PRIMARY_PROVIDER="${AUTOJUDGE_PRIMARY_PROVIDER:-anthropic}"
AUTOJUDGE_FALLBACK_PROVIDER="${AUTOJUDGE_FALLBACK_PROVIDER:-groq}"
AUTOJUDGE_HACKATHON_START="${AUTOJUDGE_HACKATHON_START:-2026-05-22T00:00:00+05:30}"
AUTOJUDGE_HACKATHON_END="${AUTOJUDGE_HACKATHON_END:-2026-05-23T23:59:59+05:30}"
GROQ_API_KEY="${GROQ_API_KEY:-}"
GEMINI_API_KEY="${GEMINI_API_KEY:-}"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER="${AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER:-agrim-judge}"
AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS="${AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS:-$(openssl rand -base64 18)}"
AUTOJUDGE_INTAKE_BASIC_AUTH_USER="${AUTOJUDGE_INTAKE_BASIC_AUTH_USER:-}"
AUTOJUDGE_INTAKE_BASIC_AUTH_PASS="${AUTOJUDGE_INTAKE_BASIC_AUTH_PASS:-}"

echo "Dashboard login -> user: ${AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER}  pass: ${AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS}"
echo "(Save the password above — it is only printed here.)"

# 1. Postgres (idempotent).
if ! "${RAILWAY_BIN}" service list --json 2>/dev/null | grep -qi '"name": *"Postgres"'; then
    echo "==> Provisioning Postgres..."
    "${RAILWAY_BIN}" add --database postgres
else
    echo "==> Postgres already present."
fi

ensure_service() {
    local name="$1"
    if ! "${RAILWAY_BIN}" service list --json 2>/dev/null | grep -q "\"name\": *\"${name}\""; then
        echo "==> Creating service: ${name} (linked to ${GIT_REPO})"
        "${RAILWAY_BIN}" add --service "${name}" --repo "${GIT_REPO}"
    else
        echo "==> Service exists: ${name}"
    fi
}

set_common_vars() {
    local svc="$1"
    "${RAILWAY_BIN}" variable set "DATABASE_URL=\${{Postgres.DATABASE_URL}}" --service "${svc}" --skip-deploys >/dev/null
    "${RAILWAY_BIN}" variable set "AUTOJUDGE_PRIMARY_PROVIDER=${AUTOJUDGE_PRIMARY_PROVIDER}" --service "${svc}" --skip-deploys >/dev/null
    "${RAILWAY_BIN}" variable set "AUTOJUDGE_FALLBACK_PROVIDER=${AUTOJUDGE_FALLBACK_PROVIDER}" --service "${svc}" --skip-deploys >/dev/null
    "${RAILWAY_BIN}" variable set "AUTOJUDGE_HACKATHON_START=${AUTOJUDGE_HACKATHON_START}" --service "${svc}" --skip-deploys >/dev/null
    "${RAILWAY_BIN}" variable set "AUTOJUDGE_HACKATHON_END=${AUTOJUDGE_HACKATHON_END}" --service "${svc}" --skip-deploys >/dev/null
    "${RAILWAY_BIN}" variable set "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" --service "${svc}" --skip-deploys >/dev/null
    [[ -n "${GROQ_API_KEY}" ]] && "${RAILWAY_BIN}" variable set "GROQ_API_KEY=${GROQ_API_KEY}" --service "${svc}" --skip-deploys >/dev/null
    [[ -n "${GEMINI_API_KEY}" ]] && "${RAILWAY_BIN}" variable set "GEMINI_API_KEY=${GEMINI_API_KEY}" --service "${svc}" --skip-deploys >/dev/null
    [[ -n "${OPENROUTER_API_KEY}" ]] && "${RAILWAY_BIN}" variable set "OPENROUTER_API_KEY=${OPENROUTER_API_KEY}" --service "${svc}" --skip-deploys >/dev/null
    "${RAILWAY_BIN}" variable set "GITHUB_TOKEN=${GITHUB_TOKEN}" --service "${svc}" --skip-deploys >/dev/null
}

ensure_service "dashboard"
set_common_vars "dashboard"
"${RAILWAY_BIN}" variable set "AUTOJUDGE_ROLE=dashboard" --service dashboard --skip-deploys >/dev/null
"${RAILWAY_BIN}" variable set "AUTOJUDGE_DATA_DIR=/data" --service dashboard --skip-deploys >/dev/null
"${RAILWAY_BIN}" variable set "AUTOJUDGE_DB_PATH=/data/traces.db" --service dashboard --skip-deploys >/dev/null
"${RAILWAY_BIN}" variable set "AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER=${AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER}" --service dashboard --skip-deploys >/dev/null
"${RAILWAY_BIN}" variable set "AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS=${AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS}" --service dashboard --skip-deploys >/dev/null

ensure_service "intake"
set_common_vars "intake"
"${RAILWAY_BIN}" variable set "AUTOJUDGE_ROLE=intake" --service intake --skip-deploys >/dev/null
if [[ -n "${AUTOJUDGE_INTAKE_BASIC_AUTH_USER}" ]]; then
    "${RAILWAY_BIN}" variable set "AUTOJUDGE_INTAKE_BASIC_AUTH_USER=${AUTOJUDGE_INTAKE_BASIC_AUTH_USER}" --service intake --skip-deploys >/dev/null
    "${RAILWAY_BIN}" variable set "AUTOJUDGE_INTAKE_BASIC_AUTH_PASS=${AUTOJUDGE_INTAKE_BASIC_AUTH_PASS}" --service intake --skip-deploys >/dev/null
fi

# Volume on the dashboard only (intake is filesystem-free).
if ! "${RAILWAY_BIN}" volume list 2>/dev/null | grep -q "Attached to: dashboard"; then
    echo "==> Attaching 10 GB volume to dashboard at /data"
    "${RAILWAY_BIN}" volume add --service dashboard --mount-path /data
fi

echo "==> Triggering deploys"
"${RAILWAY_BIN}" up --service dashboard --detach || true
"${RAILWAY_BIN}" up --service intake --detach || true

echo "==> Generating public URLs"
"${RAILWAY_BIN}" domain --service dashboard || true
"${RAILWAY_BIN}" domain --service intake || true

cat <<'EOF'

============================================================
  Deploy queued. Next:
    railway logs --service dashboard
    railway run --service dashboard autojudge doctor       # expect backend: postgres
    railway run --service dashboard autojudge run-anchors  # seed calibration
============================================================
EOF
