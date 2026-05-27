"""Archetype-aware weight redistribution and dimension caps.

Each archetype reshapes the rubric to score submissions fairly. The base
weights always sum to 100; redistributions keep that sum invariant. Caps are
applied transparently and logged as `cap_applied` + `cap_reason`.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import Archetype, RubricDimensionId
from .dimensions import DIMENSIONS


@dataclass
class WeightProfile:
    archetype: Archetype
    weights: dict[RubricDimensionId, int]
    caps: dict[RubricDimensionId, tuple[int, str]]
    notes: str


def _base_weights() -> dict[RubricDimensionId, int]:
    return {d.id: d.base_weight for d in DIMENSIONS}


def profile_for(archetype: Archetype, *, has_live_url: bool) -> WeightProfile:
    weights = _base_weights()
    caps: dict[RubricDimensionId, tuple[int, str]] = {}
    notes: list[str] = []

    if archetype == Archetype.RESEARCH:
        ux = weights[RubricDimensionId.UX]
        weights[RubricDimensionId.UX] = max(0, ux - 5)
        weights[RubricDimensionId.DEPTH] += 5
        notes.append("Research archetype: shifted 5pts from UX to Solution Depth.")
    elif archetype == Archetype.TOOL:
        notes.append("Tool archetype: base weights retained; UX still matters for CLI/SDK clarity.")
    elif archetype == Archetype.DEMO:
        if not has_live_url:
            caps[RubricDimensionId.FUNCTIONAL] = (
                6,
                "Demo-only submission without a reachable live URL — Functional Correctness capped at 6/10.",
            )
        notes.append("Demo archetype: emphasis on Communication + AI sophistication.")
    elif archetype == Archetype.PRODUCT:
        notes.append("Product archetype: base weights retained.")
    else:
        notes.append("Unknown archetype: base weights retained, will request human review.")

    if not has_live_url and archetype != Archetype.DEMO:
        caps.setdefault(
            RubricDimensionId.FUNCTIONAL,
            (
                6,
                "No reachable live URL — Functional Correctness capped at 6/10.",
            ),
        )

    total = sum(weights.values())
    if total != 100:
        diff = 100 - total
        weights[RubricDimensionId.DEPTH] += diff
        notes.append(f"Adjusted +{diff} on Solution Depth to keep total at 100.")

    return WeightProfile(
        archetype=archetype,
        weights=weights,
        caps=caps,
        notes=" ".join(notes),
    )
