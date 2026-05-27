"""Cross-check agent.

Compares candidate claims (from InferredSubmission) and deck/video evidence
against repo + live URL evidence. Emits CrossCheckReport with discrepancies
and a curated `summary_for_scorer` field.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..intake.deck import DeckParse
from ..intake.deploy import DeployProbe
from ..intake.video import VideoTranscript
from ..llm import LLMResponse, PromptPart, get_llm
from ..models import CodeAnalystReport, CrossCheckReport, InferredSubmission, JudgeReviewItem

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    return (Path(__file__).resolve().parents[3] / "prompts" / "cross_check.md").read_text(
        encoding="utf-8"
    )


def _coerce_review_items(raw: object) -> list[JudgeReviewItem]:
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
                source=str(it.get("source") or it.get("where") or "inferred_submission"),
                where=str(it["where"]) if it.get("where") else None,
            )
        )
    return items


def check(
    inferred: InferredSubmission,
    deck: DeckParse,
    transcript: VideoTranscript,
    deploy: DeployProbe | None,
    code: CodeAnalystReport,
) -> tuple[CrossCheckReport, LLMResponse | None]:
    llm = get_llm()
    system_parts = [PromptPart(text=_load_prompt(), cacheable=True)]

    claims_block = "\n".join(
        f"- [{c.id}] {c.text} (expected: {c.expected_outcome or '?'}) "
        f"[source={c.source}, confidence={c.confidence:.2f}]"
        for c in inferred.claims
    ) or "(no claims extracted)"

    deck_text = deck.joined if deck.available else "(deck unavailable)"
    video_text = transcript.transcript if transcript.available else "(transcript unavailable)"

    deploy_text = (
        f"Reachable: {deploy.reachable}, status: {deploy.status_code}, "
        f"final_url: {deploy.final_url}, title: {deploy.title}\n"
        f"Body preview:\n{deploy.body_preview[:1500]}"
        if deploy
        else "(no live URL)"
    )

    repo_text = (
        f"Top level files: {code.metrics.top_level_files if code.metrics else []}\n"
        f"Notable deps: {code.metrics.notable_dependencies if code.metrics else []}\n"
        f"Code analyst summary: {code.summary_for_scorer or code.summary}"
    )

    user = (
        f"### Candidate claims (from InferredSubmission)\n{claims_block}\n\n"
        f"### Deck contents\n{deck_text[:4000]}\n\n"
        f"### Video transcript\n{video_text[:4000]}\n\n"
        f"### Live URL probe\n{deploy_text}\n\n"
        f"### Repo summary\n{repo_text}"
    )

    try:
        data, resp = llm.complete_json(system=system_parts, user=user, tier="reasoning", max_tokens=2048)
        review_items = _coerce_review_items(data.get("judge_review_items"))
        return (
            CrossCheckReport(
                deck_summary=str(data.get("deck_summary", "")),
                video_summary=str(data.get("video_summary", "")),
                discrepancies=list(data.get("discrepancies", []) or []),
                judge_review_items=review_items,
                consistent=bool(data.get("consistent", True)),
                summary=str(data.get("summary", "")),
                summary_for_scorer=str(data.get("summary_for_scorer") or data.get("summary", "")),
            ),
            resp,
        )
    except Exception as exc:
        logger.warning("Cross-check failed: %s", exc)
        return (
            CrossCheckReport(
                summary=f"Cross-check failed: {exc}",
                summary_for_scorer=f"Cross-check failed: {exc}",
            ),
            None,
        )
