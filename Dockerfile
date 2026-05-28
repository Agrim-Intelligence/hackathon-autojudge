# Agrim AutoJudge — single image for all three Railway services.
#
# Each service overrides the start command in railway.toml:
#   - dashboard: streamlit run dashboard/app.py --server.port=$PORT --server.address=0.0.0.0
#   - intake:    streamlit run src/autojudge/intake/form.py --server.port=$PORT --server.address=0.0.0.0
#   - worker:    bash -lc 'autojudge serve-healthz --port 8500 & while true; do autojudge run-batch || true; sleep 60; done'
#
# Building one image keeps the registry footprint small and guarantees all
# three services run identical code. Playwright Chromium adds ~250 MB but is
# unavoidable for the browser verifier.

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

# Railway provides $PORT at runtime; expose both Streamlit (8501) and the
# worker healthz (8500) for local docker-run convenience.
EXPOSE 8500 8501

# Persistent data lives at /data (SQLite, snapshot cache, screenshots).
# Railway: attach a project Volume at mount path /data — do NOT use Dockerfile
# VOLUME here; Railway's Metal builder rejects it. Local docker run:
#   docker run -v "$(pwd)/data:/data" ...

ENTRYPOINT ["/usr/bin/tini", "--"]

# Default to the dashboard so `docker run -p 8501:8501 ...` works locally
# without any extra args. Railway overrides this per service.
CMD ["bash", "-lc", "streamlit run dashboard/app.py --server.port=${PORT:-8501} --server.address=0.0.0.0 --server.headless=true"]
