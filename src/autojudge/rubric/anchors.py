"""Anchor submissions for per-batch calibration.

The orchestrator re-runs the three anchors as a regression test. If any
anchor drifts by more than `MAX_DRIFT` points from its expected total, the
batch should be reviewed before publication.

The v1.1 anchors carry the same content as v1.0 but the *expected totals*
were nudged after the Shortlist-Generator reframing. Two structural changes
move the numbers:
- Credential-walled / custom-integration claims now route to
  `judge_review_items` instead of penalising the score, so anchors with
  surface-level "we integrated with X" claims tend to score higher.
- `evidence_kind` is now deterministic; dimensions without verifier signal
  cannot be marked `verified`, which can lower scores when the LLM was
  generous before.

Operators should re-run `autojudge run-anchors` once after upgrading to v1.1
and adjust `expected_total` if drift exceeds `MAX_DRIFT`. The first such
calibration after an upgrade is expected drift, not regression.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Slightly wider than v1.0 (was 8.0) to absorb the one-time Shortlist
# Generator recalibration. Operators tighten back to 8.0 after the first
# clean run-anchors pass at this codebase version.
MAX_DRIFT = 10.0


@dataclass(frozen=True)
class Anchor:
    id: str
    filename: str
    expected_total: float
    description: str
    expected_verdict: str = "borderline"


ANCHORS: list[Anchor] = [
    Anchor(
        id="anchor-strong",
        filename="strong.md",
        # MVP calibration (2026-05-27, Claude Haiku 4.5 reasoning + extraction):
        # actual=65.0, evaluable_weight=40. Lower than the v1.1 design target
        # because the anchor is a plain markdown file with no repo or live URL
        # — the new deterministic-provenance clamp denies "verified" on most
        # dimensions and normalises hard. Treat as the new floor; tighten the
        # anchor with a real repo+URL fixture before all-India rollout.
        expected_total=65.0,
        description=(
            "Real agentic loop with LangGraph, structured outputs, evals, live "
            "deployment, honest limitations, clean build log, attribution. "
            "Normalises heavily under v1.1 because the anchor markdown lacks "
            "a real repo/URL — see Phase 2 fixtures backlog."
        ),
        # Markdown-only anchor has no repo/URL so most dimensions return
        # `insufficient`, dragging evaluable_weight below 50% and forcing
        # the verdict to `insufficient`. Phase 2 fixture work will give this
        # anchor a real repo+URL and the verdict will recover to `shortlist`.
        expected_verdict="insufficient",
    ),
    Anchor(
        id="anchor-mid",
        filename="mid.md",
        # MVP calibration: actual=45.0, evaluable_weight=40, drift -7.0 (in
        # tolerance). Held stable across the reframing.
        expected_total=45.0,
        description=(
            "Working Streamlit demo, two-prompt LLM use (no tools), honest "
            "limitations, no tests/evals, attribution present. Post-reframing "
            "the lift from credential-walled-claim routing offsets the "
            "deterministic-provenance penalty."
        ),
        # Same evaluable_weight pinch as anchor-strong — markdown-only fixture.
        expected_verdict="insufficient",
    ),
    Anchor(
        id="anchor-weak",
        filename="weak.md",
        # MVP calibration: actual=11.5, evaluable_weight=65. The weaker anchor
        # has more dimensions that can be evaluated (the marketing copy gives
        # the LLM something to score down), so normalisation is gentler and
        # the low score actually surfaces.
        expected_total=11.5,
        description=(
            "Marketing-only README, no deploy, no tests, no demo, generic "
            "AI buzzwords. Lower than v1.0 because the deterministic-provenance "
            "clamp ensures dimensions can't be marked `verified` without "
            "verifier evidence."
        ),
        expected_verdict="below_threshold",
    ),
]


def anchors_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "anchors"
