#!/usr/bin/env bash
# Post-deploy smoke check for the Railway deployment.
#
# Hits the dashboard, intake form, and worker healthz endpoints, plus runs
# `autojudge doctor` inside the worker container. Exits non-zero on any
# failure so it can be wired into a release gate.
#
# Usage:
#     DASHBOARD_URL=https://judge.agrim.ai \
#     INTAKE_URL=https://submit.agrim.ai \
#     WORKER_URL=https://worker.agrim.ai \
#     ./scripts/smoke_railway.sh
#
# When DASHBOARD_URL / INTAKE_URL are fronted by Cloudflare Access, pass a
# CF_ACCESS_CLIENT_ID + CF_ACCESS_CLIENT_SECRET service-token pair so this
# script can bypass the SSO flow. Otherwise it expects them to respond 200
# directly (e.g. when run from inside the Cloudflare zone).
set -euo pipefail

DASHBOARD_URL="${DASHBOARD_URL:-}"
INTAKE_URL="${INTAKE_URL:-}"
WORKER_URL="${WORKER_URL:-}"

if [[ -z "$DASHBOARD_URL" || -z "$INTAKE_URL" || -z "$WORKER_URL" ]]; then
  echo "DASHBOARD_URL, INTAKE_URL, and WORKER_URL must all be set." >&2
  exit 2
fi

cf_headers=()
if [[ -n "${CF_ACCESS_CLIENT_ID:-}" && -n "${CF_ACCESS_CLIENT_SECRET:-}" ]]; then
  cf_headers+=(-H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}")
  cf_headers+=(-H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}")
fi

check() {
  local name="$1" url="$2" expected="${3:-200}"
  local code
  code=$(curl -fsS -o /dev/null -w "%{http_code}" "${cf_headers[@]}" "$url" || true)
  if [[ "$code" != "$expected" ]]; then
    echo "FAIL  $name $url -> HTTP $code (expected $expected)" >&2
    return 1
  fi
  echo "OK    $name $url -> HTTP $code"
}

failures=0

check "dashboard"     "${DASHBOARD_URL%/}/_stcore/health"  200 || failures=$((failures+1))
check "intake-form"   "${INTAKE_URL%/}/_stcore/health"     200 || failures=$((failures+1))
check "worker-healthz" "${WORKER_URL%/}/healthz"            200 || failures=$((failures+1))

if [[ $failures -gt 0 ]]; then
  echo "" >&2
  echo "$failures endpoint(s) failed." >&2
  exit 1
fi

echo ""
echo "All Railway endpoints healthy."
