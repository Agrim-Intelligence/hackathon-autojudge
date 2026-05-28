# Agrim AutoJudge — single image for both Railway services.
#
# Both services share this image and run `scripts/start.sh`, which dispatches
# on the AUTOJUDGE_ROLE env var:
#
#   - AUTOJUDGE_ROLE=dashboard : judges' review UI + on-demand evaluator. The
#                                "Evaluate" buttons spawn the AI pipeline as
#                                background subprocesses inside this service,
#                                so no separate worker process is needed.
#   - AUTOJUDGE_ROLE=intake    : public candidate submission form. Writes
#                                submissions + deck blobs to Postgres.
#
# Using one env var (instead of a per-service start command) keeps the whole
# deploy scriptable through the Railway CLI, which cannot set a custom start
# command per service. start.sh expands $PORT at runtime under bash, so the
# Railway healthcheck gets a real listening port.
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

# Dispatch on AUTOJUDGE_ROLE (defaults to dashboard). Set AUTOJUDGE_ROLE=intake
# on the intake service. Local: `docker run -p 8501:8501 -e AUTOJUDGE_ROLE=intake ...`.
CMD ["bash", "scripts/start.sh"]
