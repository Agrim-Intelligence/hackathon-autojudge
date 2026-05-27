"""Repo snapshot cache — fetch the candidate's repo once per submission.

This is the single largest scale-win between the v1.0 (10 GitHub REST calls
per submission across agents) and v1.1 (1 tarball download, all agents read
from disk) pipelines. Critical for all-India rollout: unauthenticated
GitHub allows only 60 requests/hour and a 5000-submission batch with the v1.0
path would blow the rate limit on the first ~6 candidates.

The snapshot is keyed in-process by `owner/repo` (lower-cased) and on disk
under `data/submissions/<submission_id>/repo_cache/snapshot.tar.gz`. The
orchestrator provisions one per submission before any agent runs;
`intake/github.py` falls back to direct REST reads when no snapshot is
registered (preserves backwards-compat for ad-hoc CLI calls).

We deliberately do NOT use the snapshot for commit history, languages, or
contributor data — that information is not in the tarball. `fetch_metrics`
still calls the GitHub API for those, but with snapshot-backed top-level
and dependency reads, the per-submission call count drops from ~10 to ~3.
"""
from __future__ import annotations

import fnmatch
import logging
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..config import get_settings
from .github import GitHubRateLimitError, _is_rate_limit_error, parse_repo_url

logger = logging.getLogger(__name__)


_SNAPSHOTS: dict[str, "RepoSnapshot"] = {}


@dataclass
class RepoSnapshot:
    """Read-only view of a GitHub repo tarball cached on disk.

    GitHub tarballs prefix every entry with `{owner}-{repo}-{sha}/`. We strip
    that prefix on read so paths look like `src/main.py` regardless of the
    repo or commit SHA. Reads stream from the tarball; we do not keep
    decompressed data resident.
    """

    tarball_path: Path
    repo_url: str
    sha: str | None = None
    _members: list[str] | None = field(default=None, init=False, repr=False)
    _prefix: str | None = field(default=None, init=False, repr=False)

    def _resolve_prefix(self) -> str:
        if self._prefix is not None:
            return self._prefix
        try:
            with tarfile.open(self.tarball_path, mode="r:gz") as tar:
                first = tar.next()
                if first is not None and first.isdir():
                    self._prefix = first.name.rstrip("/") + "/"
                elif first is not None and "/" in first.name:
                    self._prefix = first.name.split("/", 1)[0] + "/"
                else:
                    self._prefix = ""
        except Exception as exc:
            logger.warning("snapshot: cannot read tarball %s: %s", self.tarball_path, exc)
            self._prefix = ""
        return self._prefix

    def list_files(self, max_results: int = 5000) -> list[str]:
        if self._members is not None:
            return self._members[:max_results]
        prefix = self._resolve_prefix()
        members: list[str] = []
        try:
            with tarfile.open(self.tarball_path, mode="r:gz") as tar:
                for m in tar:
                    if not m.isfile():
                        continue
                    name = m.name
                    if prefix and name.startswith(prefix):
                        name = name[len(prefix):]
                    if name:
                        members.append(name)
        except Exception as exc:
            logger.warning("snapshot: list_files failed on %s: %s", self.tarball_path, exc)
        self._members = members
        return members[:max_results]

    def top_level_files(self) -> list[str]:
        return [p for p in self.list_files() if "/" not in p]

    def find_files_by_pattern(
        self, patterns: list[str], max_results: int = 20
    ) -> list[str]:
        files = self.list_files()
        if not files:
            return []
        lowered = [p.lower() for p in patterns]
        matches: list[str] = []
        for path in files:
            base = path.split("/")[-1].lower()
            if any(fnmatch.fnmatch(base, lp) for lp in lowered):
                matches.append(path)
                if len(matches) >= max_results:
                    break
        return matches

    def fetch_files(
        self, paths: list[str], max_bytes: int = 40_000
    ) -> dict[str, str]:
        wanted = set(p for p in paths if p)
        if not wanted:
            return {}
        prefix = self._resolve_prefix()
        out: dict[str, str] = {}
        try:
            with tarfile.open(self.tarball_path, mode="r:gz") as tar:
                for m in tar:
                    if not m.isfile():
                        continue
                    name = m.name
                    if prefix and name.startswith(prefix):
                        name = name[len(prefix):]
                    if name in wanted:
                        f = tar.extractfile(m)
                        if f is None:
                            continue
                        data = f.read(max_bytes + 1)
                        out[name] = data[:max_bytes].decode("utf-8", errors="ignore")
                        if len(out) == len(wanted):
                            break
        except Exception as exc:
            logger.warning("snapshot: fetch_files failed on %s: %s", self.tarball_path, exc)
        return out


def get_cached_snapshot(repo_url: str | None) -> RepoSnapshot | None:
    """Return an in-process cached snapshot for this repo, if one was provisioned."""
    if not repo_url:
        return None
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return None
    key = f"{parsed[0]}/{parsed[1]}".lower()
    return _SNAPSHOTS.get(key)


def _register(repo_url: str, snapshot: RepoSnapshot) -> None:
    parsed = parse_repo_url(repo_url)
    if parsed is None:
        return
    _SNAPSHOTS[f"{parsed[0]}/{parsed[1]}".lower()] = snapshot


def clear_in_process_cache() -> None:
    """Used by tests to drop snapshot state between runs."""
    _SNAPSHOTS.clear()


def ensure_snapshot(repo_url: str | None, dest_dir: Path) -> RepoSnapshot | None:
    """Download (or reuse) a tarball of the repo HEAD and register it.

    Returns None when the URL is unparseable, GitHub is unreachable, or the
    download fails — callers must fall back to direct REST reads.

    Raises `GitHubRateLimitError` when GitHub returns 403 due to rate limit,
    so the operator gets immediate feedback rather than a 9-minute PyGithub
    silent backoff.
    """
    if not repo_url:
        return None
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return None
    owner, name = parsed
    key = f"{owner}/{name}".lower()

    cached = _SNAPSHOTS.get(key)
    if cached is not None and cached.tarball_path.exists():
        return cached

    dest_dir.mkdir(parents=True, exist_ok=True)
    tarball_path = dest_dir / "snapshot.tar.gz"

    settings = get_settings()
    try:
        from github import Auth, Github

        if settings.github_token:
            gh_client = Github(auth=Auth.Token(settings.github_token))
        else:
            gh_client = Github()
        repo = gh_client.get_repo(f"{owner}/{name}")
        sha: str | None = None
        try:
            sha = repo.get_branch(repo.default_branch).commit.sha[:12]
        except Exception:
            sha = None
        archive_url = repo.get_archive_link("tarball")
    except Exception as exc:
        if _is_rate_limit_error(exc):
            raise GitHubRateLimitError(
                f"GitHub rate limit while resolving archive link for {owner}/{name}. "
                "Set GITHUB_TOKEN in .env."
            ) from exc
        logger.warning("snapshot: cannot resolve archive link for %s: %s", repo_url, exc)
        return None

    try:
        headers: dict[str, str] = {"User-Agent": "AgrimAutoJudge/1.1"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        with httpx.stream(
            "GET",
            archive_url,
            timeout=120.0,
            follow_redirects=True,
            headers=headers,
        ) as resp:
            resp.raise_for_status()
            with tarball_path.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)
    except Exception as exc:
        logger.warning("snapshot download failed for %s: %s", repo_url, exc)
        try:
            tarball_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    try:
        size_kb = tarball_path.stat().st_size // 1024
    except Exception:
        size_kb = 0
    logger.info(
        "snapshot: cached %s/%s @ %s (%d KB) -> %s",
        owner,
        name,
        sha or "head",
        size_kb,
        tarball_path,
    )
    snapshot = RepoSnapshot(tarball_path=tarball_path, repo_url=repo_url, sha=sha)
    _register(repo_url, snapshot)
    return snapshot
