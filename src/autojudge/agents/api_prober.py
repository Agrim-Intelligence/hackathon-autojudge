"""API prober.

Deterministic HTTP verifier for ``app_type == "api"`` submissions. The
browser verifier needs a rendered UI; an API has none, so we probe the
candidate's *declared* endpoints directly and report which responded as
expected.

Safety is by construction, not by trust:

- We only ever touch endpoints the candidate explicitly declared (path joined
  onto the declared base URL / live URL). No link-following, no discovery.
- GET/HEAD are always allowed. POST is allowed *only* when the endpoint object
  declares ``method == "POST"`` and carries a ``sample_body`` — and we send
  exactly that declared body, nothing synthesised. Every other verb
  (PUT/DELETE/PATCH/...) is rejected and recorded as skipped.
- Hard per-request timeout and a cap on total requests bound the blast radius.

The report mirrors :class:`~autojudge.models.BrowserVerifierReport` closely
enough that the orchestrator's ``_record`` helper and the rubric scorer can
treat it uniformly (``api_ok`` plays the role of ``browser_ok``).
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field

from ..llm import LLMResponse

logger = logging.getLogger(__name__)

# Bounds. Per-request timeout matches the deploy probe; the request cap stops a
# candidate from declaring hundreds of endpoints and turning verification into
# a load test against their own host.
_REQUEST_TIMEOUT_S = 15
_MAX_REQUESTS = 12
_USER_AGENT = "AgrimAutoJudge/0.1"

# Verbs we are willing to issue. POST is conditionally allowed (see module
# docstring); everything outside this set is rejected outright.
_SAFE_METHODS = {"GET", "HEAD"}
_CONDITIONAL_METHODS = {"POST"}


class EndpointResult(BaseModel):
    method: str
    path: str
    status_code: int | None = None
    ok: bool = False
    expected_status: int | None = None
    note: str = ""


class ApiProberReport(BaseModel):
    base_url_reachable: bool = False
    endpoint_results: list[EndpointResult] = Field(default_factory=list)
    # True when at least one declared endpoint returned its expected status (or
    # a 2xx when no explicit expectation was declared). Plays the same role for
    # the scorer that browser_ok does for web submissions.
    api_ok: bool = False
    summary: str = ""
    summary_for_scorer: str = ""
    skipped: bool = False
    skipped_reason: str | None = None


def _auth_header(test_credentials: str | None) -> dict[str, str]:
    """Best-effort bearer/token header from candidate-supplied credentials.

    We never invent credentials. If the candidate handed us something that
    looks like a token (a bare token, ``Bearer x``, ``token: x``,
    ``Authorization: x``), attach it. Anything that looks like a
    username/password pair is left alone — we have no safe way to guess the
    auth scheme.
    """
    if not test_credentials:
        return {}
    raw = test_credentials.strip()
    low = raw.lower()
    if low.startswith("authorization:"):
        return {"Authorization": raw.split(":", 1)[1].strip()}
    if low.startswith("bearer "):
        return {"Authorization": raw}
    for prefix in ("token:", "api_key:", "apikey:", "api-key:", "key:"):
        if low.startswith(prefix):
            return {"Authorization": f"Bearer {raw.split(':', 1)[1].strip()}"}
    # A single opaque whitespace-free token with no obvious user:pass shape.
    if " " not in raw and ":" not in raw and "@" not in raw and len(raw) >= 8:
        return {"Authorization": f"Bearer {raw}"}
    return {}


def _join(base_url: str | None, path: str) -> str | None:
    if path.startswith(("http://", "https://")):
        return path
    if not base_url:
        return None
    # urljoin needs a trailing slash on the base to treat it as a directory;
    # candidates rarely include one.
    base = base_url if base_url.endswith("/") else base_url + "/"
    return urljoin(base, path.lstrip("/"))


def _ok_for(status_code: int | None, expected_status: int | None) -> bool:
    if status_code is None:
        return False
    if expected_status is not None:
        return status_code == expected_status
    return 200 <= status_code < 300


def _note_shape(resp: httpx.Response) -> str:
    """Shallow shape note — top-level JSON key count, never deep validation."""
    ctype = (resp.headers.get("content-type") or "").lower()
    if "json" not in ctype:
        return f"content-type={ctype or 'unknown'}"
    try:
        body = resp.json()
    except Exception:
        return "declared JSON but body did not parse"
    if isinstance(body, dict):
        return f"JSON object with {len(body)} top-level keys"
    if isinstance(body, list):
        return f"JSON array of {len(body)} items"
    return "JSON scalar"


def verify_api(
    base_url: str | None,
    endpoints: list,
    submission_id: str,
    test_credentials: str | None,
) -> tuple[ApiProberReport, list[LLMResponse]]:
    """Probe declared API endpoints and report which responded as expected.

    ``endpoints`` is a list of objects/dicts shaped like
    :class:`~autojudge.models.ApiEndpoint` (``method``, ``path``,
    ``expected_status``, ``sample_body``, ``description``). Returns the report
    plus an empty LLM-response list — this agent issues no LLM calls, but keeps
    the ``(report, calls)`` tuple shape so the orchestrator's ``_record`` path
    is uniform across agents.
    """
    if not base_url and not endpoints:
        return (
            ApiProberReport(
                skipped=True,
                skipped_reason="no api_base_url and no declared endpoints to probe.",
                summary="API prober skipped: nothing declared to probe.",
                summary_for_scorer=(
                    "API prober skipped: candidate declared no base URL or endpoints. "
                    "Functional correctness could not be machine-verified."
                ),
            ),
            [],
        )

    headers = {"User-Agent": _USER_AGENT, **_auth_header(test_credentials)}
    results: list[EndpointResult] = []
    base_reachable = False
    requests_made = 0

    with httpx.Client(follow_redirects=True, timeout=_REQUEST_TIMEOUT_S, headers=headers) as client:
        for ep in endpoints:
            if requests_made >= _MAX_REQUESTS:
                logger.info("[%s] api_prober request cap (%d) reached", submission_id, _MAX_REQUESTS)
                break

            method = str(_attr(ep, "method", "GET") or "GET").upper()
            path = str(_attr(ep, "path", "") or "")
            expected_status = _attr(ep, "expected_status", None)
            sample_body = _attr(ep, "sample_body", None)
            if not path:
                continue

            url = _join(base_url, path)
            if url is None:
                results.append(
                    EndpointResult(
                        method=method,
                        path=path,
                        note="skipped: relative path with no base URL to join against.",
                        expected_status=_as_int(expected_status),
                    )
                )
                continue

            # Verb gate. POST only with an explicit declared sample body; every
            # other mutating verb is rejected without a request.
            allow_post = method in _CONDITIONAL_METHODS and sample_body is not None
            if method not in _SAFE_METHODS and not allow_post:
                reason = (
                    "skipped: POST without a declared sample_body."
                    if method in _CONDITIONAL_METHODS
                    else f"skipped: method {method} not permitted (only GET/HEAD, or POST with sample_body)."
                )
                results.append(
                    EndpointResult(
                        method=method,
                        path=path,
                        note=reason,
                        expected_status=_as_int(expected_status),
                    )
                )
                continue

            try:
                if method == "POST":
                    resp = client.post(url, json=sample_body)
                elif method == "HEAD":
                    resp = client.head(url)
                else:
                    resp = client.get(url)
                requests_made += 1
            except Exception as exc:
                results.append(
                    EndpointResult(
                        method=method,
                        path=path,
                        note=f"request failed: {type(exc).__name__}: {exc}",
                        expected_status=_as_int(expected_status),
                    )
                )
                continue

            if resp.status_code < 500:
                base_reachable = True
            exp_int = _as_int(expected_status)
            ok = _ok_for(resp.status_code, exp_int)
            results.append(
                EndpointResult(
                    method=method,
                    path=path,
                    status_code=resp.status_code,
                    ok=ok,
                    expected_status=exp_int,
                    note=_note_shape(resp),
                )
            )

    probed = [r for r in results if r.status_code is not None]
    ok_count = sum(1 for r in results if r.ok)
    declared = len(results)
    api_ok = ok_count >= 1

    summary_for_scorer = (
        f"{ok_count}/{declared} declared endpoints responded as expected."
        if declared
        else "No declared endpoints were probeable."
    )
    summary = (
        f"API prober: {ok_count}/{declared} endpoints OK; "
        f"{len(probed)} reachable; base_url_reachable={base_reachable}."
    )

    return (
        ApiProberReport(
            base_url_reachable=base_reachable,
            endpoint_results=results,
            api_ok=api_ok,
            summary=summary,
            summary_for_scorer=summary_for_scorer,
        ),
        [],
    )


def _attr(obj, name: str, default):
    """Read ``name`` from a pydantic model or a plain dict uniformly."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
