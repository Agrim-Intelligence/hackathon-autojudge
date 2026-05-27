"""AI / agentic sophistication probe.

Compares candidate-declared AI components (from InferredSubmission) with
actual source code in likely-agentic files. Emits an AISophisticationReport
with a curated `summary_for_scorer` for the rubric scorer.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..intake import github as gh
from ..llm import LLMResponse, PromptPart, get_llm
from ..models import AISophisticationReport, InferredSubmission, RepoMetrics

logger = logging.getLogger(__name__)

AI_FILE_PATTERNS = [
    "*agent*.py",
    "*agent*.ts",
    "*agent*.js",
    "*llm*.py",
    "*llm*.ts",
    "*prompt*.py",
    "*prompt*.md",
    "*chain*.py",
    "*graph*.py",
    "*orchestrat*.py",
    "*orchestrat*.ts",
    "*ai*.py",
    "*tool*.py",
    "*evals*.py",
    "*eval*.py",
]


def _load_prompt() -> str:
    return (Path(__file__).resolve().parents[3] / "prompts" / "ai_sophistication.md").read_text(
        encoding="utf-8"
    )


def probe(
    repo_url: str | None,
    metrics: RepoMetrics | None,
    inferred: InferredSubmission,
) -> tuple[AISophisticationReport, LLMResponse | None]:
    if not repo_url:
        report = AISophisticationReport(
            has_real_agentic_patterns=False,
            summary="No repo URL — cannot inspect AI code.",
            summary_for_scorer="No repo URL; AI sophistication evidence unavailable.",
            score_band="thin_wrapper",
        )
        return report, None

    paths = gh.find_files_by_pattern(repo_url, AI_FILE_PATTERNS, max_results=10)
    files = gh.fetch_files(repo_url, paths) if paths else {}
    notable_deps = metrics.notable_dependencies if metrics else []

    files_block = "\n\n".join(
        f"### {path}\n```\n{content[:5000]}\n```" for path, content in files.items()
    ) or "(no obviously AI-related source files found in the repo)"

    declared = "\n".join(
        f"- {c.name}: models={c.models or '?'}, "
        f"description={c.description or ''}, "
        f"agentic_claim={c.agentic_claim or ''}, "
        f"tools={c.tools or []}, evals={c.evals or ''}"
        for c in inferred.ai_components
    ) or "(none declared by candidate)"

    llm = get_llm()
    system_parts = [PromptPart(text=_load_prompt(), cacheable=True)]
    user = (
        f"### Candidate-declared AI components\n{declared}\n\n"
        f"### Notable AI-related dependencies detected\n"
        f"{', '.join(notable_deps) if notable_deps else '(none detected)'}\n\n"
        f"### Source excerpts from likely-agentic files\n{files_block}"
    )

    try:
        data, resp = llm.complete_json(system=system_parts, user=user, tier="reasoning", max_tokens=2048)
        report = AISophisticationReport(
            has_real_agentic_patterns=bool(data.get("has_real_agentic_patterns", False)),
            patterns_detected=[str(x) for x in (data.get("patterns_detected", []) or [])],
            thin_wrapper_signals=[str(x) for x in (data.get("thin_wrapper_signals", []) or [])],
            evidence=[str(x) for x in (data.get("evidence", []) or [])],
            score_band=str(data.get("score_band", "unknown")),
            summary=str(data.get("summary", "")),
            summary_for_scorer=str(data.get("summary_for_scorer") or data.get("summary", "")),
        )
        return report, resp
    except Exception as exc:
        logger.warning("AI sophistication probe failed: %s", exc)
        return (
            AISophisticationReport(
                has_real_agentic_patterns=False,
                summary=f"Probe failed: {exc}",
                summary_for_scorer=f"AI sophistication probe failed: {exc}",
                score_band="unknown",
            ),
            None,
        )
