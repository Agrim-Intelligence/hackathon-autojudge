#!/usr/bin/env bash
#
# Container entrypoint dispatcher.
#
# Both Railway services (dashboard + intake) run the SAME Docker image and
# differ ONLY by the AUTOJUDGE_ROLE environment variable. This avoids needing
# a per-service start-command override (which the Railway CLI cannot set) and
# keeps the deployment fully scriptable: create two services, set one var on
# each, done.
#
#   AUTOJUDGE_ROLE=dashboard  -> judges' review UI + on-demand evaluator
#   AUTOJUDGE_ROLE=intake     -> public candidate submission form
#   AUTOJUDGE_ROLE=worker     -> one-shot batch runner (optional / CLI use)
#
# $PORT is provided by Railway at runtime; we default to 8501 for local runs.
set -euo pipefail

PORT="${PORT:-8501}"
ROLE="${AUTOJUDGE_ROLE:-dashboard}"

echo "[start.sh] AUTOJUDGE_ROLE=${ROLE} PORT=${PORT}"

case "${ROLE}" in
  dashboard)
    exec streamlit run dashboard/app.py \
      --server.port="${PORT}" \
      --server.address=0.0.0.0 \
      --server.headless=true
    ;;
  intake)
    exec streamlit run src/autojudge/intake/form.py \
      --server.port="${PORT}" \
      --server.address=0.0.0.0 \
      --server.headless=true
    ;;
  worker)
    # One-shot batch run, then exit. Kept for CLI / cron use; the dashboard's
    # "Evaluate" buttons are the primary evaluation trigger in v1.2.
    exec autojudge run-batch
    ;;
  *)
    echo "[start.sh] ERROR: unknown AUTOJUDGE_ROLE='${ROLE}' (expected dashboard|intake|worker)" >&2
    exit 1
    ;;
esac
