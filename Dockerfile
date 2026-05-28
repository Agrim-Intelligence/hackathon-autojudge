# Agrim AutoJudge — single image for both Railway services.
#
# Both services share the same image; only the start command differs (set in
# the per-service railway.<service>.toml or via the Railway UI / CLI).
#
#   - dashboard: bash -lc 'streamlit run dashboard/app.py --server.port=$PORT
#                          --server.address=0.0.0.0 --server.headless=true'
#                Runs the judges' UI. Background subprocesses spawned by the
#                "Evaluate selected" button perform the actual AI runs, so the
#                dashboard service is its own worker (no separate worker
#                process is required).
#   - intake:    bash -lc 'streamlit run src/autojudge/intake/form.py
#                          --server.port=$PORT --server.address=0.0.0.0
#                          --server.headless=true'
#                Public candidate-facing form. Writes submissions and deck
#                blobs into Postgres (DATABASE_URL); reads nothing back.
#
# Wrap the start command in `bash -lc '...'` so `$PORT` expands at runtime —
# Railway Dockerfile deploys execute the start command in exec form (no shell
# expansion), so a bare `$PORT` is passed to Streamlit literally and the
# healthcheck never receives a response.
#
# Playwright Chromium adds ~250 MB but is mandatory for the browser verifier.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    AUTOJUDGE_DATA_DIR=/data \
    AUTOJUDGE_DB_PATH=/data/traces.db \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# System deps Playwright + httpx need. Chromium itself is pulled by
# `playwright install` below; --with-deps brings the X libs Chromium links
# against on debian-slim.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps before copying the rest so the layer caches across
# code edits.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip \
 && pip install -e .

# Playwright Chromium. Doing this after pip-install means we get the version
# pinned in pyproject. --with-deps installs the X / font libs Chromium needs.
RUN playwright install --with-deps chromium

# Now copy the rest of the project (prompts, dashboard, anchors, scripts).
COPY prompts ./prompts
COPY dashboard ./dashboard
COPY anchors ./anchors
COPY scripts ./scripts
COPY .env.example ./.env.example

EXPOSE 8501

# /data is used by the dashboard service for repo-snapshot cache, screenshots,
# and submission scratch files during evaluation. Postgres is the source of
# truth for submission rows + scores + deck blobs, so the intake service can
# run with NO volume mounted at all. On Railway: attach a volume at /data on
# the dashboard service only; do NOT use a Dockerfile `VOLUME` directive
# (Railway's Metal builder rejects it).

ENTRYPOINT ["/usr/bin/tini", "--"]

# Default to the dashboard so `docker run -p 8501:8501 ...` works locally
# without any extra args. Railway overrides this per service.
CMD ["bash", "-lc", "streamlit run dashboard/app.py --server.port=${PORT:-8501} --server.address=0.0.0.0 --server.headless=true"]
