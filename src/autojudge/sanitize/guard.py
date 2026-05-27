"""Prompt-injection guard.

Runs cheap-tier LLM over candidate-supplied text and returns a sanitized
version plus a list of injection attempts and a severity score.

Used at the pipeline entry on the raw SUBMISSION.md and again on each
external blob (deck text, video transcript) before any reasoning agent sees
them.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..llm import LLMResponse, PromptPart, get_llm
from ..models import GuardReport

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    path = Path(__file__).resolve().parents[3] / "prompts" / "guard.md"
    return path.read_text(encoding="utf-8")


def sanitize(text: str, source_label: str = "submission") -> tuple[GuardReport, LLMResponse | None]:
    """Return a GuardReport and the underlying LLM response for trace logging.

    Falls back to a no-op pass-through if the LLM call fails — we never want
    the guard to block the pipeline. Failures are logged.
    """
    if not text or not text.strip():
        return GuardReport(sanitized_text="", injection_attempts=[], severity=0), None

    llm = get_llm()
    system_parts = [PromptPart(text=_load_prompt(), cacheable=True)]
    user = f"[source: {source_label}]\n\n{text}"
    try:
        data, resp = llm.complete_json(system=system_parts, user=user, tier="extraction", max_tokens=4096)
        report = GuardReport(
            sanitized_text=str(data.get("sanitized_text", text)),
            injection_attempts=list(data.get("injection_attempts", []) or []),
            severity=int(data.get("severity", 0) or 0),
        )
        return report, resp
    except Exception as exc:
        logger.warning("Guard model failed: %s. Passing text through unmodified.", exc)
        return GuardReport(sanitized_text=text, injection_attempts=[], severity=0), None
