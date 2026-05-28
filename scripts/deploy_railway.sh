#!/usr/bin/env bash
#
# Agrim AutoJudge — one-shot Railway deployment.
#
# Provisions / refreshes a Railway project containing:
#   - Postgres (Railway-managed plugin)
#   - dashboard service (judges' Streamlit UI, on-demand evaluator)
#   - intake service    (public candidate Streamlit form)
#
# Prerequisites you must do once, BEFORE running this script:
#   1. Install the Railway CLI:                        railway login --help
#         macOS:  brew install railway
#         Linux:  curl -fsSL https://railway.com/install.sh | sh
#   2. Log in:                                          railway login
#   3. Create an empty project in the Railway dashboard, then ``cd`` into your
#      hackathon-autojudge repo locally and run:        railway link
#      (pick the project you just created — links this repo to Railway).
#
# Then run this script with no arguments:
#       bash scripts/deploy_railway.sh
#
# What it does (idempotent — safe to re-run):
#   - Ensures a Postgres plugin exists in the project.
#   - Ensures two services exist: ``dashboard`` and ``intake``.
#   - Pushes the per-service start command and env vars.
#   - Wires DATABASE_URL on each service to the Postgres plugin via a
#     reference variable (shared backing store).
#   - Triggers a deploy of both services from your current local repo.
#
# Re-runs incrementally — only changed config is pushed.
#
# Required environment variables (set in your local shell BEFORE running):
#   ANTHROPIC_API_KEY                     (or GROQ_API_KEY / GEMINI_API_KEY)
#   GITHUB_TOKEN                          (fine-grained, Contents:Read, Metadata:Read)
#   AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER   (judges' username)
#   AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS   (judges' password)
#
# Optional (defaulted if unset):
#   AUTOJUDGE_PRIMARY_PROVIDER=anthropic
#   AUTOJUDGE_FALLBACK_PROVIDER=groq
#   AUTOJUDGE_HACKATHON_START=2026-05-22T00:00:00+05:30
#   AUTOJUDGE_HACKATHON_END=2026-05-23T23:59:59+05:30
#   AUTOJUDGE_INTAKE_BASIC_AUTH_USER      (leave empty for fully public intake)
#   AUTOJUDGE_INTAKE_BASIC_AUTH_PASS      (leave empty for fully public intake)
#
# The script never prints secrets to stdout. Railway stores them in its own
# encrypted variable backend; this script only forwards them from your local
# shell to Railway.

set -euo pipefail

if ! command -v railway >/dev/null 2>&1; then
    echo "ERROR: railway CLI is not on PATH. Install it first."
    echo "  macOS: brew install railway"
    echo "  Linux: curl -fsSL https://railway.com/install.sh | sh"
    exit 1
fi

if ! railway whoami >/dev/null 2>&1; then
    echo "ERROR: Not logged in to Railway. Run \`railway login\` first."
    exit 1
fi

if ! railway status >/dev/null 2>&1; then
    echo "ERROR: This directory is not linked to a Railway project."
    echo "       Create the project in the Railway dashboard, then run:"
    echo "         railway link"
    exit 1
fi

# Required secrets — fail early so the operator doesn't get half-way through.
require_env() {
    local var_name="$1"
    if [[ -z "${!var_name:-}" ]]; then
        echo "ERROR: ${var_name} must be set in your local shell before running this script." >&2
        exit 1
    fi
}

require_env "ANTHROPIC_API_KEY"
require_env "GITHUB_TOKEN"
require_env "AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER"
require_env "AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS"

# Defaults — override by exporting before running this script.
AUTOJUDGE_PRIMARY_PROVIDER="${AUTOJUDGE_PRIMARY_PROVIDER:-anthropic}"
AUTOJUDGE_FALLBACK_PROVIDER="${AUTOJUDGE_FALLBACK_PROVIDER:-groq}"
AUTOJUDGE_HACKATHON_START="${AUTOJUDGE_HACKATHON_START:-2026-05-22T00:00:00+05:30}"
AUTOJUDGE_HACKATHON_END="${AUTOJUDGE_HACKATHON_END:-2026-05-23T23:59:59+05:30}"
GROQ_API_KEY="${GROQ_API_KEY:-}"
GEMINI_API_KEY="${GEMINI_API_KEY:-}"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
AUTOJUDGE_INTAKE_BASIC_AUTH_USER="${AUTOJUDGE_INTAKE_BASIC_AUTH_USER:-}"
AUTOJUDGE_INTAKE_BASIC_AUTH_PASS="${AUTOJUDGE_INTAKE_BASIC_AUTH_PASS:-}"

# ----------------------------------------------------------------------------
# 1. Postgres plugin — create if missing.
#    Railway names the auto-created plugin "Postgres"; the CLI lets us add it
#    idempotently by name. The plugin exposes DATABASE_URL on its own service
#    which we reference from the other two services.
# ----------------------------------------------------------------------------
if ! railway service list 2>/dev/null | grep -qi "Postgres"; then
    echo "==> Provisioning Postgres plugin..."
    railway add --database postgres
else
    echo "==> Postgres plugin already present, skipping."
fi

# ----------------------------------------------------------------------------
# 2. Helper: ensure a Railway service of the given name exists.
# ----------------------------------------------------------------------------
ensure_service() {
    local service_name="$1"
    if ! railway service list 2>/dev/null | grep -q "^${service_name}$"; then
        echo "==> Creating service: ${service_name}"
        railway service create "${service_name}"
    else
        echo "==> Service exists: ${service_name}"
    fi
}

ensure_service "dashboard"
ensure_service "intake"

# ----------------------------------------------------------------------------
# 3. Helper: push env vars onto a specific service.
#    We always pass DATABASE_URL by reference so the value can't drift if
#    the Postgres plugin gets recreated.
# ----------------------------------------------------------------------------
set_service_vars() {
    local service_name="$1"
    shift
    echo "==> Setting env vars on ${service_name}"
    railway variables --service "${service_name}" \
        --set "DATABASE_URL=\${{Postgres.DATABASE_URL}}" \
        --set "AUTOJUDGE_PRIMARY_PROVIDER=${AUTOJUDGE_PRIMARY_PROVIDER}" \
        --set "AUTOJUDGE_FALLBACK_PROVIDER=${AUTOJUDGE_FALLBACK_PROVIDER}" \
        --set "AUTOJUDGE_HACKATHON_START=${AUTOJUDGE_HACKATHON_START}" \
        --set "AUTOJUDGE_HACKATHON_END=${AUTOJUDGE_HACKATHON_END}" \
        --set "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" \
        --set "GROQ_API_KEY=${GROQ_API_KEY}" \
        --set "GEMINI_API_KEY=${GEMINI_API_KEY}" \
        --set "OPENROUTER_API_KEY=${OPENROUTER_API_KEY}" \
        --set "GITHUB_TOKEN=${GITHUB_TOKEN}" \
        "$@"
}

set_service_vars "dashboard" \
    --set "AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER=${AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER}" \
    --set "AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS=${AUTOJUDGE_DASHBOARD_BASIC_AUTH_PASS}" \
    --set "AUTOJUDGE_DATA_DIR=/data" \
    --set "AUTOJUDGE_DB_PATH=/data/traces.db"

set_service_vars "intake" \
    --set "AUTOJUDGE_INTAKE_BASIC_AUTH_USER=${AUTOJUDGE_INTAKE_BASIC_AUTH_USER}" \
    --set "AUTOJUDGE_INTAKE_BASIC_AUTH_PASS=${AUTOJUDGE_INTAKE_BASIC_AUTH_PASS}"

# ----------------------------------------------------------------------------
# 4. Deploy both services from the current local repo.
#    ``railway up`` uploads the working directory and triggers a build.
#    We use --detach so the script exits when the deploy is queued; tail
#    logs separately if you want to watch the build.
# ----------------------------------------------------------------------------
echo "==> Deploying dashboard..."
railway up --service dashboard --detach

echo "==> Deploying intake..."
railway up --service intake --detach

echo ""
echo "============================================================"
echo "  Agrim AutoJudge: deploy queued."
echo ""
echo "  Watch progress:"
echo "    railway logs --service dashboard"
echo "    railway logs --service intake"
echo ""
echo "  Generate public URLs (one per service):"
echo "    railway domain --service dashboard"
echo "    railway domain --service intake"
echo ""
echo "  Next: attach a 10 GB volume to the dashboard service at /data"
echo "  via the Railway dashboard (Settings → Volumes). The intake"
echo "  service does NOT need a volume."
echo ""
echo "  Bootstrap calibration anchors once the dashboard is healthy:"
echo "    railway run --service dashboard autojudge doctor"
echo "    railway run --service dashboard autojudge run-anchors"
echo "============================================================"
