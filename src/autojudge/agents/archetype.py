"""Archetype classifier agent."""
from __future__ import annotations

import logging
from pathlib import Path

from ..llm import LLMResponse, PromptPart, get_llm
from ..models import Archetype, ArchetypeReport, InferredSubmission

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    return (Path(__file__).resolve().parents[3] / "prompts" / "archetype_classifier.md").read_text(
        encoding="utf-8"
    )


def classify(
    inferred: InferredSubmission, has_live_url: bool
) -> tuple[ArchetypeReport, LLMResponse | None]:
    llm = get_llm()
    system_parts = [PromptPart(text=_load_prompt(), cacheable=True)]
    problem = inferred.problem_statement.value or "(no problem statement inferred)"
    tech_stack = inferred.tech_stack.value or {}
    claims = "; ".join(c.text for c in inferred.claims[:5]) or "(no claims)"
    user = (
        f"Live URL reachable: {has_live_url}\n\n"
        f"--- Inferred submission summary ---\n"
        f"Problem: {problem[:1500]}\n"
        f"Tech stack: {tech_stack}\n"
        f"Top claims: {claims}\n"
        f"AI components: {len(inferred.ai_components)}\n"
        f"Summary for scorer: {inferred.summary_for_scorer[:1500]}\n"
    )
    try:
        data, resp = llm.complete_json(system=system_parts, user=user, tier="extraction", max_tokens=512)
        arch_raw = str(data.get("archetype", "unknown")).lower()
        try:
            archetype = Archetype(arch_raw)
        except ValueError:
            archetype = Archetype.UNKNOWN
        return (
            ArchetypeReport(
                archetype=archetype,
                confidence=float(data.get("confidence", 0.0) or 0.0),
                rationale=str(data.get("rationale", "")),
            ),
            resp,
        )
    except Exception as exc:
        logger.warning("Archetype classifier failed: %s", exc)
        return (
            ArchetypeReport(
                archetype=Archetype.UNKNOWN,
                confidence=0.0,
                rationale=f"Classifier failed: {exc}",
            ),
            None,
        )
