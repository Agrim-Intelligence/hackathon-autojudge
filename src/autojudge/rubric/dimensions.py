"""The 6-dimension rubric definitions.

Used by the rubric scorer (prompts include these anchor descriptors) and by
the dashboard (to render the breakdown).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import RubricDimensionId


@dataclass(frozen=True)
class Dimension:
    id: RubricDimensionId
    name: str
    base_weight: int
    description: str
    anchors: dict[int, str]


DIMENSIONS: list[Dimension] = [
    Dimension(
        id=RubricDimensionId.PROBLEM,
        name="Problem Clarity & Relevance",
        base_weight=10,
        description="Is the problem real, framed crisply, and worth solving now?",
        anchors={
            10: "Sharp problem, specific user, urgency clear, current alternatives explicitly compared.",
            7: "Real problem, decent framing, light comparison to alternatives.",
            5: "Generic but plausible problem; vague user or urgency.",
            3: "Vague problem statement; could be a thousand other products.",
            1: "No identifiable problem; pure tech-demo or solution-in-search-of-problem.",
        },
    ),
    Dimension(
        id=RubricDimensionId.DEPTH,
        name="Solution Depth (Technical)",
        base_weight=25,
        description="Code quality, architecture, non-trivial engineering, repo signals.",
        anchors={
            10: "Non-trivial architecture, clear modular code, tests, CI, thoughtful trade-offs documented.",
            7: "Working multi-component system; reasonable code organization; some tests or docs.",
            5: "Basic functional code; thin layers; minimal organization; mostly happy-path.",
            3: "Template-heavy, copy-pasted, or extremely shallow.",
            1: "Barely working or essentially a fork of a public starter.",
        },
    ),
    Dimension(
        id=RubricDimensionId.AI_SOPHISTICATION,
        name="AI / Agentic Sophistication",
        base_weight=20,
        description="Genuine agentic patterns vs thin LLM wrappers; tool use, planning, evals.",
        anchors={
            10: "Multi-step agentic flow with real tool use, planning/reflection, evals or guardrails.",
            7: "Structured LLM use with tools or RAG, some guardrails or retries.",
            5: "Single-shot LLM call with prompt engineering; competent but not agentic.",
            3: "Thin wrapper around an LLM API; no clear value-add beyond the model itself.",
            1: "Calls an LLM trivially with no engineering around it.",
        },
    ),
    Dimension(
        id=RubricDimensionId.FUNCTIONAL,
        name="Functional Correctness",
        base_weight=25,
        description="Does the deployed product actually do what it claims?",
        anchors={
            10: "All claimed user journeys execute end-to-end on the live URL with correct outputs.",
            7: "Most journeys work; one fails or degrades on edge cases.",
            5: "Happy path works; multiple journeys fail or are not reachable.",
            3: "Major claimed flows broken or inaccessible.",
            1: "Live URL unreachable / app crashes / nothing works.",
        },
    ),
    Dimension(
        id=RubricDimensionId.UX,
        name="UX & Polish",
        base_weight=10,
        description="Friction, visual quality, error handling, copywriting clarity.",
        anchors={
            10: "Clean UI, low friction, errors handled gracefully, instructions clear.",
            7: "Usable UI; minor friction or rough edges; basic error handling.",
            5: "Functional but rough; visible friction; little error handling.",
            3: "Confusing UI or broken flows; bare-minimum styling.",
            1: "Unusable or broken UI; user cannot complete intended tasks.",
        },
    ),
    Dimension(
        id=RubricDimensionId.COMMUNICATION,
        name="Communication",
        base_weight=10,
        description="Quality of README, deck, video — clarity over flash.",
        anchors={
            10: "README, deck, video are concise, consistent, and honest; claims = reality.",
            7: "Materials are clear; one minor inconsistency.",
            5: "Materials present but uneven; vague claims or missing pieces.",
            3: "Marketing-heavy or unclear; multiple inconsistencies vs repo/URL.",
            1: "Missing materials, or materials contradict the product.",
        },
    ),
]


DIMENSIONS_BY_ID: dict[RubricDimensionId, Dimension] = {d.id: d for d in DIMENSIONS}


def render_rubric_for_prompt() -> str:
    """Render the full rubric for inclusion in scorer prompts."""
    lines: list[str] = []
    for d in DIMENSIONS:
        lines.append(f"### {d.name} (id: {d.id.value}, base weight: {d.base_weight})")
        lines.append(d.description)
        lines.append("Anchor scores:")
        for score in sorted(d.anchors.keys(), reverse=True):
            lines.append(f"- {score}/10: {d.anchors[score]}")
        lines.append("")
    return "\n".join(lines)
