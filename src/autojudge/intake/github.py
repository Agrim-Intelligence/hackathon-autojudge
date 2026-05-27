"""GitHub repo metadata fetcher.

Pulls repo signals over the REST API: metadata, languages, commit timestamps,
top-level files, common-dep detection.

File reads (`fetch_files`, `find_files_by_pattern`) prefer a local tarball
snapshot when one has been provisioned for the repo (see `repo_cache.py`).
This collapses ~10 GitHub REST calls per submission into one tarball download
that all agents share — the critical move for all-India scale.

Authentication is read from `GITHUB_TOKEN` in `.env`. Without a token GitHub
allows only 60 requests/hour per IP and PyGithub blocks on 403 with a backoff
that can stall the pipeline for ~9 minutes. v1.1 surfaces the 403 immediately
as a `GitHubRateLimitError` so the operator can react.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings
from ..models import RepoMetrics

logger = logging.getLogger(__name__)

REPO_URL_RE = re.compile(r"github\.com[:/]([\w.\-]+)/([\w.\-]+?)(?:\.git)?/?$")


class GitHubRateLimitError(RuntimeError):
    """Surfaced when GitHub returns 403 because the rate limit is exhausted.

    The operator should set `GITHUB_TOKEN` in `.env` (unauthenticated 60/hr
    becomes authenticated 5000/hr) or wait for the window to reset. We raise
    rather than letting PyGithub's default 9-minute backoff silently freeze
    the pipeline.
    """

    def __init__(self, message: str, reset_at: datetime | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Heuristic detection of PyGithub rate-limit exceptions across versions."""
    name = type(exc).__name__
    if name in {"RateLimitExceededException", "RateLimitExceeded"}:
        return True
    msg = str(exc).lower()
    if "rate limit" in msg and "403" in msg:
        return True
    status = getattr(exc, "status", None)
    if status == 403 and "rate limit" in msg:
        return True
    return False


def _raise_if_rate_limited(exc: BaseException, context: str) -> None:
    """Translate a PyGithub rate-limit exception into our typed error.

    Call this inside the except branch of any GH API site. If the exception
    is not a rate limit, it is re-raised unchanged so callers keep their
    existing handling for parse / network / auth errors.
    """
    if not _is_rate_limit_error(exc):
        return
    reset_at: datetime | None = None
    # PyGithub attaches the reset header on RateLimitExceededException
    headers = getattr(exc, "headers", None) or {}
    reset_raw = headers.get("x-ratelimit-reset") or headers.get("X-RateLimit-Reset")
    if reset_raw:
        try:
            reset_at = datetime.fromtimestamp(int(reset_raw), tz=timezone.utc)
        except Exception:
            reset_at = None
    settings = get_settings()
    has_token = bool(settings.github_token)
    suffix = (
        f" Resets at {reset_at.isoformat()}." if reset_at else ""
    )
    advice = (
        "Set `GITHUB_TOKEN` in .env (raises limit 60->5000/hr)."
        if not has_token
        else "Wait for the rate-limit window to reset or rotate to a less-used token."
    )
    raise GitHubRateLimitError(
        f"GitHub rate limit hit at {context}.{suffix} {advice}",
        reset_at=reset_at,
    ) from exc


def _sanitize_languages(repo: Any) -> dict[str, int]:
    """PyGithub occasionally surfaces a non-numeric `url` entry inside the
    languages dict for some repos (the lazy-loaded response). RepoMetrics
    requires `dict[str, int]`; coerce defensively, drop everything we cannot
    interpret as a byte count, and never raise."""
    try:
        raw = repo.get_languages() or {}
    except Exception as exc:  # pragma: no cover - network errors
        _raise_if_rate_limited(exc, "repo.get_languages")
        logger.warning("repo.get_languages() failed: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, int] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            cleaned[k] = v
        elif isinstance(v, float):
            cleaned[k] = int(v)
        elif isinstance(v, str) and v.isdigit():
            cleaned[k] = int(v)
        # ignore url-style or any other non-numeric entry
    return cleaned


def parse_repo_url(url: str) -> tuple[str, str] | None:
    """Return (owner, repo) or None if not a GitHub URL."""
    m = REPO_URL_RE.search(url.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def _github_client():
    from github import Auth, Github

    settings = get_settings()
    if settings.github_token:
        return Github(auth=Auth.Token(settings.github_token))
    return Github()


def fetch_metrics(repo_url: str) -> RepoMetrics | None:
    """Pull repo metadata and commit-window signals.

    Returns None if the URL is unparseable or the repo is inaccessible.
    """
    parsed = parse_repo_url(repo_url)
    if not parsed:
        logger.warning("Cannot parse GitHub URL: %s", repo_url)
        return None

    owner, name = parsed
    settings = get_settings()
    try:
        gh = _github_client()
        repo = gh.get_repo(f"{owner}/{name}")
    except Exception as exc:
        _raise_if_rate_limited(exc, f"get_repo({owner}/{name})")
        logger.warning("GitHub fetch failed for %s/%s: %s", owner, name, exc)
        return RepoMetrics(repo_url=repo_url)

    languages = _sanitize_languages(repo)
    try:
        default_branch = repo.default_branch
    except Exception:
        default_branch = None
    try:
        metrics = RepoMetrics(
            repo_url=repo_url,
            default_branch=default_branch,
            languages=languages,
        )
    except Exception as exc:
        logger.warning(
            "RepoMetrics construction failed for %s/%s (languages=%s): %s",
            owner,
            name,
            list(languages)[:5],
            exc,
        )
        return RepoMetrics(repo_url=repo_url, default_branch=default_branch)

    try:
        commits = list(repo.get_commits()[:200])
    except Exception as exc:
        _raise_if_rate_limited(exc, "repo.get_commits")
        commits = []

    metrics.total_commits = len(commits)
    in_window = 0
    out_window = 0
    contributors: set[str] = set()
    first: datetime | None = None
    last: datetime | None = None
    window_start = settings.autojudge_hackathon_start
    window_end = settings.autojudge_hackathon_end

    for c in commits:
        try:
            ts = c.commit.author.date
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        first = ts if first is None or ts < first else first
        last = ts if last is None or ts > last else last
        if window_start <= ts <= window_end:
            in_window += 1
        else:
            out_window += 1
        try:
            if c.author and c.author.login:
                contributors.add(c.author.login)
        except Exception:
            pass

    metrics.commits_in_window = in_window
    metrics.commits_outside_window = out_window
    metrics.first_commit_at = first
    metrics.last_commit_at = last
    metrics.contributors = max(len(contributors), 1) if commits else 0

    # Prefer the snapshot for top-level enumeration; saves one GH API call.
    from .repo_cache import get_cached_snapshot

    snapshot = get_cached_snapshot(repo_url)
    top_level: list[str] = []
    if snapshot is not None:
        top_level = snapshot.top_level_files()
    if not top_level:
        try:
            contents = repo.get_contents("")
            top_level = (
                [c.name for c in contents]
                if isinstance(contents, list)
                else [contents.name]
            )
        except Exception as exc:
            _raise_if_rate_limited(exc, "repo.get_contents('')")
            top_level = []
    metrics.top_level_files = top_level
    lower = {f.lower() for f in top_level}
    metrics.has_readme = any(f.startswith("readme") for f in lower)
    metrics.has_dockerfile = "dockerfile" in lower
    metrics.has_tests = any(
        f in lower for f in ("tests", "test", "__tests__", "spec", "specs")
    )
    metrics.has_ci = any(f in lower for f in (".github", ".circleci", ".gitlab-ci.yml"))

    metrics.notable_dependencies = _detect_dependencies(repo, repo_url, top_level)

    metrics.line_count_estimate = sum(metrics.languages.values())

    return metrics


def _detect_dependencies(repo: Any, repo_url: str, top_level: list[str]) -> list[str]:
    """Look for known AI/ML dep markers in package manifests.

    Reads manifests from the in-process snapshot when one is registered for
    this repo (zero GH API calls). Falls back to per-file REST reads when
    no snapshot is available.
    """
    interesting = {
        "openai",
        "anthropic",
        "google-generativeai",
        "google-genai",
        "langchain",
        "langgraph",
        "llamaindex",
        "llama-index",
        "crewai",
        "autogen",
        "pyautogen",
        "transformers",
        "instructor",
        "dspy",
        "pydantic-ai",
        "vercel/ai",
        "ai-sdk",
        "vercel-ai",
    }
    found: set[str] = set()
    files_to_check = {
        "requirements.txt",
        "pyproject.toml",
        "package.json",
        "Pipfile",
        "poetry.lock",
        "uv.lock",
    }
    targets = [f for f in top_level if f in files_to_check]
    if not targets:
        return []

    from .repo_cache import get_cached_snapshot

    snapshot = get_cached_snapshot(repo_url)
    if snapshot is not None:
        manifests = snapshot.fetch_files(targets, max_bytes=40_000)
        for content in manifests.values():
            lowered = content.lower()
            for dep in interesting:
                if dep in lowered:
                    found.add(dep)
        return sorted(found)

    for fname in targets:
        try:
            blob = repo.get_contents(fname)
            if isinstance(blob, list):
                continue
            content = blob.decoded_content.decode("utf-8", errors="ignore").lower()
        except Exception as exc:
            _raise_if_rate_limited(exc, f"repo.get_contents({fname})")
            continue
        for dep in interesting:
            if dep in content:
                found.add(dep)
    return sorted(found)


def fetch_files(repo_url: str, paths: list[str], max_bytes: int = 40_000) -> dict[str, str]:
    """Best-effort fetch of specific files for downstream inspection.

    Reads from the local tarball snapshot when one has been provisioned by the
    orchestrator (preferred path; one HTTP call total per submission). Falls
    back to the REST API only when no snapshot is available — useful for
    ad-hoc CLI calls outside the pipeline.
    """
    from .repo_cache import get_cached_snapshot

    snapshot = get_cached_snapshot(repo_url)
    if snapshot is not None:
        return snapshot.fetch_files(paths, max_bytes=max_bytes)

    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {}
    owner, name = parsed
    try:
        gh = _github_client()
        repo = gh.get_repo(f"{owner}/{name}")
    except Exception as exc:
        _raise_if_rate_limited(exc, f"get_repo({owner}/{name})")
        return {}

    out: dict[str, str] = {}
    for path in paths:
        try:
            blob = repo.get_contents(path)
            if isinstance(blob, list):
                continue
            text = blob.decoded_content.decode("utf-8", errors="ignore")
            out[path] = text[:max_bytes]
        except Exception as exc:
            _raise_if_rate_limited(exc, f"get_contents({path})")
            continue
    return out


def find_files_by_pattern(
    repo_url: str, name_patterns: list[str], max_results: int = 20
) -> list[str]:
    """Find files matching glob-like name patterns.

    Prefers the local tarball snapshot (zero GitHub calls). Falls back to a
    single git-tree fetch via the REST API when no snapshot exists.
    Patterns are matched against the file basename, case-insensitively.
    """
    from .repo_cache import get_cached_snapshot

    snapshot = get_cached_snapshot(repo_url)
    if snapshot is not None:
        return snapshot.find_files_by_pattern(name_patterns, max_results=max_results)

    parsed = parse_repo_url(repo_url)
    if not parsed:
        return []
    owner, name = parsed
    try:
        gh = _github_client()
        repo = gh.get_repo(f"{owner}/{name}")
        tree = repo.get_git_tree(repo.default_branch, recursive=True)
    except Exception as exc:
        _raise_if_rate_limited(exc, f"get_git_tree({owner}/{name})")
        return []
    import fnmatch

    matches: list[str] = []
    for entry in tree.tree:
        if entry.type != "blob":
            continue
        base = entry.path.split("/")[-1].lower()
        for pat in name_patterns:
            if fnmatch.fnmatch(base, pat.lower()):
                matches.append(entry.path)
                break
        if len(matches) >= max_results:
            break
    return matches
