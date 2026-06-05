"""Rubric scorer.

Reads curated summaries from upstream verifiers, calls one reasoning LLM
that emits 6 dimension scores (each possibly null when evidence is
insufficient), applies archetype caps, and computes a normalised total
over the evaluable dimensions.

The prompt is split into cache-friendly static blocks (rubric definitions,
scorer system prompt) and one dynamic block (per-submission data). On the
Anthropic provider the static blocks ride `cache_control: ephemeral` and
are reused across submissions in a batch.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..llm import LLMResponse, PromptPart, get_llm
from ..models import (
    AISophisticationReport,
    Archetype,
    BrowserVerifierReport,
    CodeAnalystReport,
    CrossCheckReport,
    DimensionScore,
    EvidenceKind,
    GuardReport,
    InferredSubmission,
    JudgeReviewItem,
    RubricDimensionId,
    RubricScore,
    Verdict,
)
from ..rubric.dimensions import DIMENSIONS_BY_ID, render_rubric_for_prompt
from ..rubric.weights import WeightProfile
from .api_prober import ApiProberReport

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    return (Path(__file__).resolve().parents[3] / "prompts" / "rubric_scorer.md").read_text(
        encoding="utf-8"
    )


def _evidence_kind(raw: object) -> EvidenceKind:
    if isinstance(raw, str) and raw in ("stated", "inferred", "verified", "insufficient"):
        return raw  # type: ignore[return-value]
    return "inferred"


# Provenance ladder used to clamp the LLM's evidence_kind to what the pipeline
# can actually back. `insufficient` is handled separately (it implies null
# score) so it is not in the ladder.
_PROVENANCE_RANK: dict[EvidenceKind, int] = {
    "stated": 1,
    "inferred": 2,
    "verified": 3,
}


def _candidate_provided_body(inferred: InferredSubmission) -> bool:
    """True when the candidate's own words backed *some* part of the submission.

    Scanned across the InferredSubmission fields and claims. Used to decide
    whether `stated` is even a possible evidence_kind ceiling for the
    text-heavy dimensions (problem_clarity, communication).
    """
    for field in (
        inferred.candidate_identity,
        inferred.problem_statement,
        inferred.tech_stack,
        inferred.known_limitations,
        inferred.acknowledgements,
    ):
        if field.source == "stated" and field.value:
            return True
    return any(c.source == "stated" for c in inferred.claims)


def _has_browser_success(browser: BrowserVerifierReport) -> bool:
    return (
        not browser.skipped
        and browser.live_url_reachable
        and any(j.success for j in browser.journey_results)
    )


def _max_evidence_kind(
    dim_id: RubricDimensionId,
    *,
    inferred: InferredSubmission,
    code: CodeAnalystReport,
    ai_soph: AISophisticationReport,
    browser: BrowserVerifierReport,
    cross: CrossCheckReport,
    api: ApiProberReport | None = None,
) -> EvidenceKind:
    """Strongest evidence_kind the pipeline can defensibly attest to.

    The rubric scorer LLM may propose `verified`/`inferred`/`stated`; we clamp
    its output to what the verifiers actually observed. This is deterministic
    and computed from pipeline state, never LLM-judged.
    """
    browser_ok = _has_browser_success(browser)
    api_ok = bool(api and not api.skipped and api.api_ok)
    # An API submission can reach `verified` functional via the prober even
    # though it has no browser-renderable UI. UX stays browser-only.
    functional_evidence = browser_ok or api_ok
    has_repo = code.metrics is not None
    candidate_words = _candidate_provided_body(inferred)
    cross_has_signal = bool(cross.summary_for_scorer or cross.summary or cross.discrepancies)
    ai_probe_ran = bool(ai_soph.summary_for_scorer or ai_soph.evidence)

    if dim_id == RubricDimensionId.FUNCTIONAL:
        if functional_evidence:
            return "verified"
        if has_repo or cross_has_signal:
            return "inferred"
        return "stated" if candidate_words else "inferred"

    if dim_id == RubricDimensionId.UX:
        if browser_ok:
            return "verified"
        return "stated" if candidate_words else "inferred"

    if dim_id == RubricDimensionId.AI_SOPHISTICATION:
        if ai_probe_ran and has_repo:
            return "verified"
        if ai_probe_ran or has_repo:
            return "inferred"
        return "stated" if candidate_words else "inferred"

    if dim_id == RubricDimensionId.DEPTH:
        if has_repo:
            return "verified"
        return "stated" if candidate_words else "inferred"

    if dim_id == RubricDimensionId.PROBLEM:
        return "stated" if candidate_words else "inferred"

    if dim_id == RubricDimensionId.COMMUNICATION:
        # Communication tracks how the candidate presents the work; observed
        # only through their own words. Verifier signals never elevate this
        # past `stated` (when present) or `inferred` (synthesised).
        return "stated" if candidate_words else "inferred"

    return "inferred"


def _clamp_kind(llm_kind: EvidenceKind, ceiling: EvidenceKind) -> EvidenceKind:
    """Downgrade an LLM-proposed evidence_kind to a defensible ceiling.

    `insufficient` short-circuits — it lives in a separate axis and means
    "no score", not a strength level. Otherwise we pick the lesser of the
    two on the provenance ladder.
    """
    if llm_kind == "insufficient":
        return "insufficient"
    llm_rank = _PROVENANCE_RANK.get(llm_kind, _PROVENANCE_RANK["inferred"])
    ceiling_rank = _PROVENANCE_RANK.get(ceiling, _PROVENANCE_RANK["inferred"])
    if llm_rank <= ceiling_rank:
        return llm_kind
    return ceiling


def _inferred_for_scorer(inferred: InferredSubmission) -> str:
    """Compact view of an InferredSubmission for the scorer prompt."""

    def fmt_field(name: str, field) -> str:
        if field.value is None:
            return f"- {name}: (unknown, gap noted)"
        value = field.value
        if isinstance(value, dict):
            value_str = ", ".join(f"{k}={v}" for k, v in value.items())
        elif isinstance(value, list):
            value_str = "; ".join(str(v) for v in value)
        else:
            value_str = str(value)
        return (
            f"- {name} [source={field.source}, conf={field.confidence:.2f}]: "
            f"{value_str[:600]}"
        )

    parts = [
        fmt_field("candidate_identity", inferred.candidate_identity),
        fmt_field("problem_statement", inferred.problem_statement),
        fmt_field("tech_stack", inferred.tech_stack),
        fmt_field("known_limitations", inferred.known_limitations),
        fmt_field("acknowledgements", inferred.acknowledgements),
    ]
    if inferred.claims:
        parts.append("- claims:")
        for c in inferred.claims[:8]:
            parts.append(
                f"  * [{c.id}] {c.text[:180]} "
                f"(source={c.source}, conf={c.confidence:.2f}, "
                f"expected={c.expected_outcome or '?'})"
            )
    if inferred.user_journeys:
        parts.append("- user_journeys:")
        for j in inferred.user_journeys[:5]:
            parts.append(
                f"  * {j.name}: {len(j.steps)} steps -> {j.expected_outcome[:120]} "
                f"(source={j.source})"
            )
    if inferred.ai_components:
        parts.append("- ai_components:")
        for a in inferred.ai_components[:5]:
            parts.append(
                f"  * {a.name}: {a.description or ''} (models={a.models or '?'}, "
                f"tools={a.tools}, evals={a.evals or 'none'}, source={a.source})"
            )
    if inferred.gaps:
        parts.append("- gaps flagged by Inference Agent:")
        for g in inferred.gaps[:10]:
            parts.append(f"  * {g}")
    if inferred.summary_for_scorer:
        parts.append(f"- summary_for_scorer: {inferred.summary_for_scorer[:1000]}")
    return "\n".join(parts)


def _all_dim_insufficient(reason: str) -> list[DimensionScore]:
    return [
        DimensionScore(
            dimension=d.id,
            raw_score=None,
            weighted_score=None,
            rationale=reason,
            evidence=[],
            evidence_kind="insufficient",
        )
        for d in DIMENSIONS_BY_ID.values()
    ]


# Verdict thresholds (over the normalised 100-point scale). The numbers
# match anchor expectations: anchor-strong (~78) lands in shortlist,
# anchor-mid (~50) in borderline, anchor-weak (~18) below threshold.
# Operators can override via judging committee decisions; these are the
# default recommendations from the auto-pipeline.
SHORTLIST_THRESHOLD = 65.0
BORDERLINE_THRESHOLD = 40.0
MIN_EVALUABLE_WEIGHT_FOR_VERDICT = 50


def _compute_verdict(total: float, evaluable_weight: int) -> Verdict:
    if evaluable_weight < MIN_EVALUABLE_WEIGHT_FOR_VERDICT:
        return "insufficient"
    if total >= SHORTLIST_THRESHOLD:
        return "shortlist"
    if total >= BORDERLINE_THRESHOLD:
        return "borderline"
    return "below_threshold"


def _coerce_review_items(raw: object, fallback_source: str) -> list[JudgeReviewItem]:
    if not isinstance(raw, list):
        return []
    items: list[JudgeReviewItem] = []
    for it in raw:
        if not isinstance(it, dict) or not it.get("claim"):
            continue
        items.append(
            JudgeReviewItem(
                claim=str(it["claim"]),
                reason=str(it.get("reason", "")),
                source=str(it.get("source") or fallback_source),
                where=str(it["where"]) if it.get("where") else None,
            )
        )
    return items


def _dedupe_review_items(items: list[JudgeReviewItem]) -> list[JudgeReviewItem]:
    seen: set[str] = set()
    out: list[JudgeReviewItem] = []
    for it in items:
        key = (it.claim or "").strip().lower()[:240]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def score(
    submission_id: str,
    archetype: Archetype,
    inferred: InferredSubmission,
    code: CodeAnalystReport,
    ai_soph: AISophisticationReport,
    browser: BrowserVerifierReport,
    cross: CrossCheckReport,
    guard: GuardReport,
    weights: WeightProfile,
    api: ApiProberReport | None = None,
) -> tuple[RubricScore, LLMResponse | None]:
    llm = get_llm()

    rubric_text = render_rubric_for_prompt()

    caps_block = (
        "\n".join(
            f"- {dim.value}: cap at {cap}/10 ({reason})"
            for dim, (cap, reason) in weights.caps.items()
        )
        or "(no caps active)"
    )

    weights_block = "\n".join(
        f"- {d.value}: {w} pts" for d, w in weights.weights.items()
    )

    inferred_block = _inferred_for_scorer(inferred)

    discrepancies_block = json.dumps(cross.discrepancies, indent=2, default=str)[:1500]

    if api is not None:
        api_block = (
            f"{api.summary_for_scorer or api.summary or '(no summary)'}\n"
            f"api_ok: {api.api_ok}; base_url_reachable: {api.base_url_reachable}; "
            f"skipped: {api.skipped} ({api.skipped_reason or ''})"
        )
    else:
        api_block = "(not an API submission)"

    user = (
        f"### Archetype\n{archetype.value} (weight notes: {weights.notes})\n\n"
        f"### Weights per dimension\n{weights_block}\n\n"
        f"### Active score caps\n{caps_block}\n\n"
        f"### InferredSubmission\n{inferred_block}\n\n"
        f"### Code analyst summary\n{code.summary_for_scorer or code.summary or '(no summary)'}\n"
        f"Integrity flags: {code.integrity_flags or '(none)'}\n\n"
        f"### AI sophistication summary\n{ai_soph.summary_for_scorer or ai_soph.summary or '(no summary)'}\n"
        f"Score band: {ai_soph.score_band}; thin-wrapper signals: {ai_soph.thin_wrapper_signals}\n\n"
        f"### Browser verifier summary\n{browser.summary_for_scorer or browser.summary or '(no summary)'}\n"
        f"Reachable: {browser.live_url_reachable}; skipped: {browser.skipped} "
        f"({browser.skipped_reason or ''})\n\n"
        f"### API prober summary\n{api_block}\n\n"
        f"### Cross-check summary\n{cross.summary_for_scorer or cross.summary or '(no summary)'}\n"
        f"Discrepancies: {discrepancies_block}\n\n"
        f"### Guard report\nseverity={guard.severity}; "
        f"attempts={guard.injection_attempts or '(none)'}\n"
    )

    system_parts = [
        PromptPart(text=_load_prompt(), cacheable=True),
        PromptPart(text="### Rubric definitions and anchor scores\n" + rubric_text, cacheable=True),
    ]

    try:
        data, resp = llm.complete_json(
            system=system_parts, user=user, tier="reasoning", max_tokens=3072
        )
    except Exception as exc:
        logger.error("Rubric scorer LLM failed: %s", exc)
        return (
            RubricScore(
                submission_id=submission_id,
                archetype=archetype,
                total_score=0.0,
                dimensions=_all_dim_insufficient(f"Scorer LLM failed: {exc}"),
                summary=f"Scorer failed: {exc}",
                integrity_flags=["scorer_failed"],
                evaluable_weight=0,
                normalized=False,
                judge_review_items=list(cross.judge_review_items),
                verdict="insufficient",
            ),
            None,
        )

    raw_dims: dict[RubricDimensionId, dict] = {}
    for item in data.get("dimensions", []) or []:
        try:
            dim_id = RubricDimensionId(item["dimension"])
        except Exception:
            continue
        raw_dims[dim_id] = item

    dim_scores: list[DimensionScore] = []
    evaluable_weight = 0
    weighted_total_evaluable = 0.0
    kind_overrides: list[str] = []
    for dim in DIMENSIONS_BY_ID.values():
        item = raw_dims.get(dim.id, {})
        weight = weights.weights.get(dim.id, dim.base_weight)
        raw_value = item.get("raw_score", None)
        rationale = str(item.get("rationale", ""))
        evidence = [str(x) for x in (item.get("evidence", []) or [])]
        llm_kind = _evidence_kind(item.get("evidence_kind"))

        if raw_value is None or llm_kind == "insufficient":
            dim_scores.append(
                DimensionScore(
                    dimension=dim.id,
                    raw_score=None,
                    weighted_score=None,
                    rationale=rationale or "Insufficient evidence to evaluate this dimension.",
                    evidence=evidence,
                    evidence_kind="insufficient",
                )
            )
            continue

        try:
            raw_score = float(raw_value)
        except (TypeError, ValueError):
            dim_scores.append(
                DimensionScore(
                    dimension=dim.id,
                    raw_score=None,
                    weighted_score=None,
                    rationale=rationale or f"Scorer returned unparseable raw_score: {raw_value!r}",
                    evidence=evidence,
                    evidence_kind="insufficient",
                )
            )
            continue

        # Clamp LLM-proposed evidence_kind to what the pipeline can attest.
        # This is the deterministic provenance rule: the LLM never gets to
        # call something `verified` without a verifier signal behind it.
        ceiling = _max_evidence_kind(
            dim.id,
            inferred=inferred,
            code=code,
            ai_soph=ai_soph,
            browser=browser,
            cross=cross,
            api=api,
        )
        ekind = _clamp_kind(llm_kind, ceiling)
        if ekind != llm_kind:
            kind_overrides.append(
                f"{dim.id.value}: scorer said {llm_kind!r}, clamped to {ekind!r} "
                f"(no pipeline signal supports {llm_kind!r})"
            )

        raw_score = max(0.0, min(10.0, raw_score))
        cap_applied = False
        cap_reason: str | None = None
        if dim.id in weights.caps:
            cap, reason = weights.caps[dim.id]
            if raw_score > cap:
                raw_score = float(cap)
                cap_applied = True
                cap_reason = reason
        weighted = round(raw_score * weight / 10.0, 2)
        weighted_total_evaluable += weighted
        evaluable_weight += weight
        dim_scores.append(
            DimensionScore(
                dimension=dim.id,
                raw_score=round(raw_score, 1),
                weighted_score=weighted,
                rationale=rationale,
                evidence=evidence,
                evidence_kind=ekind,
                cap_applied=cap_applied,
                cap_reason=cap_reason,
            )
        )

    if evaluable_weight == 0:
        total = 0.0
        normalized = False
    elif evaluable_weight == 100:
        total = round(weighted_total_evaluable, 2)
        normalized = False
    else:
        total = round(weighted_total_evaluable * 100.0 / evaluable_weight, 2)
        normalized = True

    integrity_flags = [str(x) for x in (data.get("integrity_flags", []) or [])]
    if evaluable_weight < 100 and evaluable_weight > 0:
        integrity_flags.append(
            f"normalized_total: only {evaluable_weight}/100 weight evaluable; "
            "score normalised over evaluable dimensions only."
        )
    integrity_flags.extend(kind_overrides)

    scorer_review_items = _coerce_review_items(
        data.get("judge_review_items"), fallback_source="inferred_submission"
    )
    review_items = _dedupe_review_items(scorer_review_items + list(cross.judge_review_items))
    verdict = _compute_verdict(total, evaluable_weight)

    if verdict == "insufficient" and browser.auth_blocked:
        integrity_flags.append(
            "insufficient_cause: live app is credential-walled — functional/UX could "
            "not be verified end-to-end. Provide working test credentials and re-run. "
            "This is a missing-evidence gap, not a quality penalty."
        )

    # API submissions have no UX surface to verify; a skipped/unreachable prober
    # leaves functional unverified too. Make that legible rather than penalising.
    if verdict == "insufficient" and api is not None and (api.skipped or not api.api_ok):
        integrity_flags.append(
            "insufficient_cause: API submission could not be machine-verified end-to-end "
            f"({api.skipped_reason or api.summary_for_scorer or 'no declared endpoint responded as expected'}). "
            "This is a missing-evidence gap, not a quality penalty — routed to judge review."
        )

    rubric = RubricScore(
        submission_id=submission_id,
        archetype=archetype,
        total_score=total,
        dimensions=dim_scores,
        summary=str(data.get("summary", "")),
        integrity_flags=integrity_flags,
        evaluable_weight=evaluable_weight,
        normalized=normalized,
        judge_review_items=review_items,
        verdict=verdict,
    )
    return rubric, resp
