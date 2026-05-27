"""Live URL reachability and lightweight content fetch.

Used by the cross-check verifier (to compare deployed page vs repo claims) and
as a precondition gate for the browser verifier.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class DeployProbe:
    url: str
    reachable: bool
    status_code: int | None
    final_url: str | None
    title: str | None
    body_preview: str
    content_type: str | None
    error: str | None = None


def probe(url: str, timeout: int = 15) -> DeployProbe:
    """Fetch the live URL once and return summary signals.

    We do *not* execute JavaScript here — the browser verifier handles that.
    This probe is meant to be cheap and synchronous.
    """
    if not url:
        return DeployProbe(
            url=url,
            reachable=False,
            status_code=None,
            final_url=None,
            title=None,
            body_preview="",
            content_type=None,
            error="empty url",
        )
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            r = client.get(url, headers={"User-Agent": "AgrimAutoJudge/0.1"})
        body = r.text[:8000]
        title = _extract_title(body)
        return DeployProbe(
            url=url,
            reachable=r.status_code < 500,
            status_code=r.status_code,
            final_url=str(r.url),
            title=title,
            body_preview=body[:2000],
            content_type=r.headers.get("content-type"),
        )
    except Exception as exc:
        logger.warning("Deploy probe failed for %s: %s", url, exc)
        return DeployProbe(
            url=url,
            reachable=False,
            status_code=None,
            final_url=None,
            title=None,
            body_preview="",
            content_type=None,
            error=str(exc),
        )


def _extract_title(html: str) -> str | None:
    import re

    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else None
