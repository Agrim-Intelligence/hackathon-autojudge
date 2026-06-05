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


QUARANTINE_PLACEHOLDER = "[QUARANTINED: guard unavailable — untrusted text withheld]"

# Structured prefix the channel-sanitizing agents append to their report's
# flags/gaps so the orchestrator finalize block can recover the max severity
# observed across untrusted channels.
INJECTION_FLAG_PREFIX = "injection_detected"


def injection_flag(channel: str, report: GuardReport) -> str | None:
    """Return a structured integrity flag for a sanitized channel, or None.

    Only emitted when the guard saw something worth propagating (severity >= 1
    or explicit attempts), so clean channels add no noise.
    """
    if report.severity < 1 and not report.injection_attempts:
        return None
    attempts = "; ".join(report.injection_attempts) or "(none listed)"
    return f"{INJECTION_FLAG_PREFIX} channel={channel} severity={report.severity}: {attempts}"


def max_injection_severity(flags: list[str]) -> int:
    """Scan integrity flags / gaps for the highest channel-injection severity."""
    best = 0
    for f in flags:
        if not f.startswith(INJECTION_FLAG_PREFIX):
            continue
        for tok in f.split():
            if tok.startswith("severity="):
                try:
                    best = max(best, int(tok.split("=", 1)[1].rstrip(":")))
                except ValueError:
                    pass
    return best


def sanitize(text: str, source_label: str = "submission") -> tuple[GuardReport, LLMResponse | None]:
    """Return a GuardReport and the underlying LLM response for trace logging.

    Fail-secure: if the guard LLM call fails we withhold the untrusted text
    (replace it with a neutralized placeholder) and raise the severity so
    downstream enforcement can quarantine, rather than letting raw candidate
    text reach a reasoning LLM. Failures are logged.
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
        logger.warning("Guard model failed: %s. Quarantining untrusted text (fail-secure).", exc)
        return (
            GuardReport(
                sanitized_text=QUARANTINE_PLACEHOLDER,
                injection_attempts=["guard_unavailable"],
                severity=3,
            ),
            None,
        )
