"""Tiny stdlib HTTP healthz server for the worker container.

Exposes a single endpoint:

    GET /healthz

returning a JSON document Railway (or any other supervisor) can use as a
liveness probe. Intentionally stdlib-only — pulling in Flask or Starlette for
one endpoint would inflate the worker image for no benefit.

The health payload is intentionally cheap. It opens one SQLite connection,
runs three small COUNT/MAX queries, and returns. If those queries hang
because the DB is locked, the request times out and Railway restarts the
container — which is exactly what we want.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..config import get_settings

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gather_health() -> dict[str, Any]:
    settings = get_settings()
    db_path = settings.autojudge_db_path
    data_dir = settings.autojudge_data_dir

    free_gb: float | None
    try:
        usage = shutil.disk_usage(data_dir)
        free_gb = round(usage.free / (1024**3), 2)
    except OSError:
        free_gb = None

    running = 0
    scored = 0
    last_finalized_at: str | None = None
    db_ok = False
    if Path(db_path).exists():
        try:
            with sqlite3.connect(str(db_path), timeout=2.0) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT "
                    " SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,"
                    " SUM(CASE WHEN status='scored' THEN 1 ELSE 0 END) AS scored"
                    " FROM submissions"
                ).fetchone()
                running = int(row["running"] or 0)
                scored = int(row["scored"] or 0)
                last_row = conn.execute(
                    "SELECT MAX(finalized_at) AS last FROM totals"
                ).fetchone()
                last_finalized_at = last_row["last"] if last_row else None
                db_ok = True
        except sqlite3.Error as exc:
            logger.warning("healthz: db query failed: %s", exc)

    healthy = db_ok and (free_gb is None or free_gb >= 0.5)
    return {
        "status": "ok" if healthy else "degraded",
        "checked_at": _now_iso(),
        "db_path": str(db_path),
        "db_reachable": db_ok,
        "free_disk_gb": free_gb,
        "running_submissions": running,
        "scored_submissions": scored,
        "last_finalized_at": last_finalized_at,
    }


class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("healthz %s - " + format, self.address_string(), *args)

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path.rstrip("/") not in ("/healthz", "/health"):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"not found\n")
            return
        payload = _gather_health()
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200 if payload["status"] == "ok" else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host: str = "0.0.0.0", port: int = 8500) -> None:
    """Run the healthz server in the foreground (blocks).

    Use this from ``autojudge serve-healthz`` or as the foreground process in
    a Dockerfile.worker entrypoint while ``run-batch`` runs in the background.
    """
    server = ThreadingHTTPServer((host, port), _HealthHandler)
    logger.info("healthz serving on http://%s:%d/healthz", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def serve_in_thread(host: str = "0.0.0.0", port: int = 8500) -> ThreadingHTTPServer:
    """Spawn the server in a daemon thread; return the server handle.

    Intended for tests and the case where the same process runs both the
    healthz endpoint and the batch loop.
    """
    server = ThreadingHTTPServer((host, port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="healthz")
    thread.start()
    return server
