"""Code analyst agent.

Combines deterministic repo metrics with an LLM-driven qualitative review of
a curated set of representative files. Emits CodeAnalystReport including a
`summary_for_scorer` field the rubric scorer reads instead of the full JSON.

Deterministic integrity checks:
- Commit-window ratio against the hackathon dates
- Single-commit / squash-of-everything pattern
- Missing README / tests / CI signals
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..intake import github as gh
from ..llm import LLMResponse, PromptPart, get_llm
from ..models import CodeAnalystReport, RepoMetrics

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    return (Path(__file__).resolve().parents[3] / "prompts" / "code_analyst.md").read_text(
        encoding="utf-8"
    )


def _select_representative_files(repo_url: str) -> dict[str, str]:
    patterns = [
        "readme*",
        "main.py",
        "app.py",
        "index.ts",
        "index.tsx",
        "index.js",
        "server.py",
        "agent.py",
        "agents.py",
        "graph.py",
        "orchestrator.py",
        "*.config.js",
        "Dockerfile",
        "pyproject.toml",
        "package.json",
        "requirements.txt",
    ]
    paths = gh.find_files_by_pattern(repo_url, patterns, max_results=12)
    return gh.fetch_files(repo_url, paths)


def _deterministic_flags(metrics: RepoMetrics, *, skip_window_check: bool = False) -> list[str]:
    flags: list[str] = []
    if metrics.total_commits == 0:
        flags.append("No commits visible — repo may be empty or token-gated.")
    elif not skip_window_check:
        if metrics.commits_in_window == 0:
            flags.append(
                "Zero commits inside hackathon window — submission likely predates the event."
            )
        elif metrics.total_commits >= 5 and metrics.commits_in_window <= 1:
            flags.append(
                f"Only {metrics.commits_in_window}/{metrics.total_commits} commits in hackathon window."
            )
    if metrics.total_commits == 1:
        flags.append("Single-commit history — may be a squash dump, hard to verify build log.")
    if not metrics.has_readme:
        flags.append("No README at repo root.")
    if not metrics.has_tests:
        flags.append("No visible test directory or test files at top level.")
    return flags


def analyze(
    repo_url: str | None, *, skip_window_check: bool = False
) -> tuple[CodeAnalystReport, LLMResponse | None, RepoMetrics | None]:
    if not repo_url:
        report = CodeAnalystReport(
            integrity_flags=["No repository URL provided."],
            summary="No repository to analyze.",
            summary_for_scorer="No repository URL submitted; code depth signals unavailable.",
        )
        return report, None, None

    metrics = gh.fetch_metrics(repo_url)
    if metrics is None:
        return (
            CodeAnalystReport(
                integrity_flags=["Repo URL unparseable."],
                summary="Repo URL unparseable.",
                summary_for_scorer="Repo URL unparseable; cannot evaluate code depth.",
            ),
            None,
            None,
        )

    integrity = _deterministic_flags(metrics, skip_window_check=skip_window_check)
    files = _select_representative_files(repo_url)

    llm = get_llm()
    system_parts = [PromptPart(text=_load_prompt(), cacheable=True)]
    metrics_payload = metrics.model_dump(mode="json")
    langs = metrics_payload.get("languages") or {}
    if isinstance(langs, dict) and len(langs) > 8:
        top = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:8]
        metrics_payload["languages"] = dict(top)
        metrics_payload["languages_truncated"] = True
    metrics_summary = json.dumps(metrics_payload, indent=2, default=str)
    files_block = "\n\n".join(
        f"### {path}\n```\n{content[:2500]}\n```" for path, content in list(files.items())[:6]
    ) or "(no representative files retrieved)"

    user = (
        f"### Repo metrics\n```json\n{metrics_summary}\n```\n\n"
        f"### Deterministic integrity flags\n- "
        + ("\n- ".join(integrity) if integrity else "(none)")
        + f"\n\n### Representative files\n{files_block}"
    )

    try:
        data, resp = llm.complete_json(system=system_parts, user=user, tier="reasoning", max_tokens=2048)
        report = CodeAnalystReport(
            metrics=metrics,
            quality_signals=dict(data.get("quality_signals", {}) or {}),
            integrity_flags=integrity + [str(x) for x in (data.get("integrity_flags", []) or [])],
            summary=str(data.get("summary", "")),
            summary_for_scorer=str(data.get("summary_for_scorer") or data.get("summary", "")),
        )
        return report, resp, metrics
    except Exception as exc:
        logger.warning("Code analyst LLM failed: %s", exc)
        return (
            CodeAnalystReport(
                metrics=metrics,
                integrity_flags=integrity + [f"LLM analysis failed: {exc}"],
                summary="Code analyst LLM failed; relying on deterministic signals only.",
                summary_for_scorer=(
                    "Code analyst LLM failed. Deterministic flags only: "
                    + ("; ".join(integrity) if integrity else "(none)")
                ),
            ),
            None,
            metrics,
        )
