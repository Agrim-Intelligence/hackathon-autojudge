"""Pipeline orchestrator.

Runs the full DAG for one submission:

  guard -> deploy_probe -> inference (tool-calling) -> archetype
        -> {code_analyst, ai_sophistication, browser_verifier, cross_check}
        -> rubric_scorer -> persist

Sequential rather than concurrent — easier to reason about, easier to debug,
and the dominant latency (browser verifier) does not overlap usefully with
other agents on the same submission.

Every agent run is persisted to the trace store before the next agent starts.
Exceptions inside any step are caught, logged into a synthetic verifier_runs
row with `agent='orchestrator'`, and re-raised so `run_pending_batch` can
mark the submission failed while preserving the full traceback.
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents import (
    ai_sophistication,
    archetype as archetype_agent,
    browser_verifier,
    code_analyst,
    cross_check,
    inference as inference_agent,
    rubric_scorer,
)
from .agents.inference_tools import ArtifactBundle
from .config import get_settings
from .intake.deck import parse_deck
from .intake.deploy import probe as probe_deploy
from .intake.github import GitHubRateLimitError
from .intake.repo_cache import ensure_snapshot
from .intake.video import fetch_transcript
from .llm import LLMResponse


# --- Per-agent cost ceilings -------------------------------------------------
#
# Hard upper bounds prevent any single agent from blowing the batch budget on
# a runaway tool-call loop. We check after the fact and surface violations as
# integrity flags. The numbers leave generous headroom (typical runs use a
# small fraction). Phase 2 will enforce these mid-run; Phase 1 is observational
# so we don't accidentally kill in-flight pipelines on edge submissions.

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentBudget:
    max_llm_calls: int
    max_input_tokens: int = 400_000


AGENT_BUDGETS: dict[str, AgentBudget] = {
    "guard": AgentBudget(max_llm_calls=2),
    "inference": AgentBudget(max_llm_calls=12, max_input_tokens=600_000),
    "archetype": AgentBudget(max_llm_calls=2),
    "code_analyst": AgentBudget(max_llm_calls=2),
    "ai_sophistication": AgentBudget(max_llm_calls=2),
    "browser_verifier": AgentBudget(max_llm_calls=80, max_input_tokens=400_000),
    "cross_check": AgentBudget(max_llm_calls=2),
    "rubric_scorer": AgentBudget(max_llm_calls=2),
}


def _check_budget(agent: str, calls: list[LLMResponse]) -> list[str]:
    """Report budget violations for one agent's LLM activity.

    Returns a list of human-readable flags (possibly empty). Never raises.
    Hooked into the orchestrator post-agent so the trace store records the
    actual usage while the pipeline continues.
    """
    budget = AGENT_BUDGETS.get(agent)
    if budget is None:
        return []
    flags: list[str] = []
    n_calls = len(calls)
    in_tokens = sum(c.input_tokens for c in calls)
    if n_calls > budget.max_llm_calls:
        flags.append(
            f"cost_ceiling: {agent} made {n_calls} LLM calls "
            f"(budget {budget.max_llm_calls})"
        )
    if in_tokens > budget.max_input_tokens:
        flags.append(
            f"cost_ceiling: {agent} used {in_tokens} input tokens "
            f"(budget {budget.max_input_tokens})"
        )
    return flags
from .models import (
    BrowserVerifierReport,
    CandidateInfo,
    Submission,
    SubmissionArtifacts,
    SubmissionStatus,
    VerifierRun,
)
from .rubric.weights import profile_for
from .sanitize.guard import sanitize
from .trace.store import get_store

logger = logging.getLogger(__name__)


def _pace() -> None:
    """Groq free tier is TPM-limited; a short pause helps avoid 429s."""
    if get_settings().autojudge_primary_provider == "groq":
        time.sleep(2.5)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record(
    store,
    submission_id: str,
    agent: str,
    started_at: datetime,
    finished_at: datetime,
    input_summary: str,
    output: Any,
    llm_response: LLMResponse | None = None,
    error: str | None = None,
) -> None:
    out_dict: dict[str, Any]
    if hasattr(output, "model_dump"):
        out_dict = output.model_dump(mode="json")
    elif isinstance(output, dict):
        out_dict = output
    else:
        out_dict = {"value": str(output)}
    store.record_run(
        VerifierRun(
            submission_id=submission_id,
            agent=agent,
            model=llm_response.model if llm_response else None,
            provider=llm_response.provider if llm_response else None,
            started_at=started_at,
            finished_at=finished_at,
            input_summary=input_summary,
            output=out_dict,
            cost_usd=llm_response.estimated_cost_usd if llm_response else 0.0,
            cost_is_precise=llm_response.cost_is_precise if llm_response else False,
            error=error,
        )
    )


def _record_failure(store, submission_id: str, step: str, exc: BaseException) -> None:
    """Write a synthetic verifier_runs row recording an orchestrator failure."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    now = _now()
    store.record_run(
        VerifierRun(
            submission_id=submission_id,
            agent="orchestrator",
            started_at=now,
            finished_at=now,
            input_summary=f"step={step}",
            output={"step": step, "exception_class": type(exc).__name__, "message": str(exc)},
            error=tb[:8000],
        )
    )


def run_submission(submission_id: str) -> None:
    """Run the full pipeline for one submission already registered in the store."""
    store = get_store()
    sub_row = store.get_submission(submission_id)
    if not sub_row:
        raise ValueError(f"submission {submission_id} not in store")

    extras = json.loads(sub_row.get("extras_json") or "{}")
    submission_md_path = extras.get("submission_md_path")
    test_credentials = extras.get("test_credentials")
    if not submission_md_path or not Path(submission_md_path).exists():
        raise FileNotFoundError(f"submission body file missing for {submission_id}")
    submission_md_raw = Path(submission_md_path).read_text(encoding="utf-8")
    is_anchor = bool(sub_row.get("is_anchor"))

    store.set_status(submission_id, SubmissionStatus.RUNNING)
    logger.info("[%s] pipeline start", submission_id)

    try:
        _run_pipeline(
            store=store,
            submission_id=submission_id,
            sub_row=sub_row,
            submission_md_raw=submission_md_raw,
            test_credentials=test_credentials,
            is_anchor=is_anchor,
        )
    except Exception as exc:
        logger.exception("[%s] pipeline failed: %s", submission_id, exc)
        _record_failure(store, submission_id, "pipeline", exc)
        store.set_status(submission_id, SubmissionStatus.FAILED)
        raise


class _DeadlineExceeded(Exception):
    """Raised when the per-submission wall-clock budget is exhausted."""


def _make_deadline_check(submission_id: str, deadline_s: int):
    """Return a callable that raises ``_DeadlineExceeded`` past the deadline.

    Kept as a closure so each pipeline run gets its own monotonic baseline.
    The orchestrator catches the exception and short-circuits to the scorer
    with whatever reports it has, rather than letting one stuck submission
    block an entire batch.
    """
    started = time.monotonic()

    def _check(stage: str) -> None:
        elapsed = time.monotonic() - started
        if elapsed > deadline_s:
            raise _DeadlineExceeded(
                f"submission_timeout after {elapsed:.0f}s at stage={stage} "
                f"(budget={deadline_s}s)"
            )

    return _check


def _run_pipeline(
    *,
    store,
    submission_id: str,
    sub_row: dict[str, Any],
    submission_md_raw: str,
    test_credentials: str | None,
    is_anchor: bool,
) -> None:
    budget_flags: list[str] = []
    settings = get_settings()
    deadline_s = settings.autojudge_submission_timeout_s
    check_deadline = _make_deadline_check(submission_id, deadline_s)
    # --- Guard ---
    t0 = _now()
    try:
        guard_report, guard_resp = sanitize(submission_md_raw, source_label="submission_body")
    except Exception as exc:
        _record_failure(store, submission_id, "guard", exc)
        raise
    t1 = _now()
    _record(
        store,
        submission_id,
        "guard",
        t0,
        t1,
        f"body length={len(submission_md_raw)}",
        guard_report,
        guard_resp,
    )
    budget_flags.extend(_check_budget("guard", [guard_resp] if guard_resp else []))
    _pace()

    # --- Live URL probe (deterministic, no LLM) ---
    live_url = sub_row.get("live_url")
    deploy = None
    if live_url:
        t0 = _now()
        try:
            deploy = probe_deploy(live_url)
        except Exception as exc:
            _record_failure(store, submission_id, "deploy_probe", exc)
            deploy = None
        t1 = _now()
        if deploy is not None:
            _record(
                store,
                submission_id,
                "deploy_probe",
                t0,
                t1,
                f"url={live_url}",
                {
                    "url": deploy.url,
                    "reachable": deploy.reachable,
                    "status_code": deploy.status_code,
                    "final_url": deploy.final_url,
                    "title": deploy.title,
                    "error": deploy.error,
                },
            )
    has_live_url = bool(deploy and deploy.reachable)

    # --- Repo snapshot (one tarball per submission; all agents share it) ---
    repo_url = sub_row.get("repo_url")
    if repo_url:
        settings = get_settings()
        snapshot_dir = settings.submissions_dir / submission_id / "repo_cache"
        t0 = _now()
        snapshot = None
        snapshot_error: str | None = None
        try:
            snapshot = ensure_snapshot(repo_url, snapshot_dir)
        except GitHubRateLimitError as exc:
            snapshot_error = str(exc)
            logger.warning("[%s] %s", submission_id, snapshot_error)
        except Exception as exc:
            snapshot_error = f"{type(exc).__name__}: {exc}"
            logger.warning("[%s] snapshot fetch failed: %s", submission_id, snapshot_error)
        t1 = _now()
        if snapshot is not None:
            try:
                size_kb = snapshot.tarball_path.stat().st_size // 1024
            except Exception:
                size_kb = 0
            _record(
                store,
                submission_id,
                "repo_snapshot",
                t0,
                t1,
                f"repo_url={repo_url}",
                {
                    "repo_url": repo_url,
                    "sha": snapshot.sha,
                    "tarball_path": str(snapshot.tarball_path),
                    "size_kb": size_kb,
                },
            )
        else:
            _record(
                store,
                submission_id,
                "repo_snapshot",
                t0,
                t1,
                f"repo_url={repo_url}",
                {
                    "repo_url": repo_url,
                    "snapshot": "unavailable",
                    "reason": snapshot_error or "download_failed",
                    "fallback": "agents will use direct GitHub REST reads",
                },
                error=snapshot_error,
            )

    check_deadline("pre_inference")
    # --- Inference Agent (tool-calling) ---
    bundle = ArtifactBundle(
        repo_url=sub_row.get("repo_url"),
        live_url=sub_row.get("live_url"),
        video_url=sub_row.get("video_url"),
        deck_path=sub_row.get("deck_path"),
        free_text=guard_report.sanitized_text,
    )
    t0 = _now()
    try:
        inferred, inference_calls = inference_agent.run_inference(bundle)
    except Exception as exc:
        _record_failure(store, submission_id, "inference", exc)
        raise
    t1 = _now()
    last_inference_call = inference_calls[-1] if inference_calls else None
    inference_out = inferred.model_dump(mode="json")
    inference_out["llm_call_count"] = len(inference_calls)
    inference_out["llm_total_cost_usd"] = round(
        sum(c.estimated_cost_usd for c in inference_calls), 4
    )
    _record(
        store,
        submission_id,
        "inference",
        t0,
        t1,
        f"artifacts_seen={inferred.artifacts_seen}",
        inference_out,
        last_inference_call,
    )
    budget_flags.extend(_check_budget("inference", inference_calls))
    _pace()

    check_deadline("pre_archetype")
    # --- Archetype ---
    t0 = _now()
    try:
        arch_report, arch_resp = archetype_agent.classify(inferred, has_live_url)
    except Exception as exc:
        _record_failure(store, submission_id, "archetype", exc)
        raise
    t1 = _now()
    _record(store, submission_id, "archetype", t0, t1, "inferred submission", arch_report, arch_resp)
    store.set_archetype(submission_id, arch_report.archetype.value)
    budget_flags.extend(_check_budget("archetype", [arch_resp] if arch_resp else []))
    _pace()

    check_deadline("pre_code_analyst")
    # --- Code analyst ---
    t0 = _now()
    try:
        code_report, code_resp, metrics = code_analyst.analyze(
            sub_row.get("repo_url"), skip_window_check=is_anchor
        )
    except Exception as exc:
        _record_failure(store, submission_id, "code_analyst", exc)
        raise
    t1 = _now()
    _record(
        store,
        submission_id,
        "code_analyst",
        t0,
        t1,
        sub_row.get("repo_url") or "(no repo)",
        code_report,
        code_resp,
    )
    budget_flags.extend(_check_budget("code_analyst", [code_resp] if code_resp else []))
    _pace()

    check_deadline("pre_ai_sophistication")
    # --- AI sophistication ---
    t0 = _now()
    try:
        ai_report, ai_resp = ai_sophistication.probe(sub_row.get("repo_url"), metrics, inferred)
    except Exception as exc:
        _record_failure(store, submission_id, "ai_sophistication", exc)
        raise
    t1 = _now()
    _record(
        store,
        submission_id,
        "ai_sophistication",
        t0,
        t1,
        sub_row.get("repo_url") or "(no repo)",
        ai_report,
        ai_resp,
    )
    budget_flags.extend(_check_budget("ai_sophistication", [ai_resp] if ai_resp else []))
    _pace()

    # --- Browser verifier ---
    # This is the most common cause of a hung submission. If we've already
    # blown the deadline, skip the agent and synthesise a stub report so the
    # scorer still has something to consume; otherwise run normally and
    # convert a mid-run timeout into the same stub.
    browser_skip_reason: str | None = None
    try:
        check_deadline("pre_browser_verifier")
    except _DeadlineExceeded as exc:
        browser_skip_reason = str(exc)

    t0 = _now()
    browser_calls: list[LLMResponse] = []
    if browser_skip_reason is not None:
        browser_report = BrowserVerifierReport(
            live_url_reachable=has_live_url,
            skipped=True,
            skipped_reason=browser_skip_reason,
            summary="Browser verifier skipped: submission_timeout reached.",
            summary_for_scorer="Browser verifier skipped due to submission_timeout.",
        )
        budget_flags.append(f"submission_timeout: {browser_skip_reason}")
    else:
        try:
            browser_report, browser_calls = browser_verifier.verify(
                live_url=live_url,
                journeys=inferred.user_journeys,
                submission_id=submission_id,
                test_credentials=test_credentials,
            )
        except Exception as exc:
            _record_failure(store, submission_id, "browser_verifier", exc)
            raise
    t1 = _now()
    last_browser_call = browser_calls[-1] if browser_calls else None
    total_browser_cost = sum(c.estimated_cost_usd for c in browser_calls)
    out_dict = browser_report.model_dump(mode="json")
    out_dict["llm_call_count"] = len(browser_calls)
    out_dict["llm_total_cost_usd"] = round(total_browser_cost, 4)
    _record(
        store,
        submission_id,
        "browser_verifier",
        t0,
        t1,
        f"live_url={live_url}",
        out_dict,
        last_browser_call,
    )
    budget_flags.extend(_check_budget("browser_verifier", browser_calls))
    _pace()

    check_deadline("pre_cross_check")
    # --- Cross-check ---
    deck = parse_deck(sub_row.get("deck_path"))
    transcript = fetch_transcript(sub_row.get("video_url"))
    t0 = _now()
    try:
        cross_report, cross_resp = cross_check.check(inferred, deck, transcript, deploy, code_report)
    except Exception as exc:
        _record_failure(store, submission_id, "cross_check", exc)
        raise
    t1 = _now()
    _record(store, submission_id, "cross_check", t0, t1, "deck+video vs repo+url", cross_report, cross_resp)
    budget_flags.extend(_check_budget("cross_check", [cross_resp] if cross_resp else []))
    _pace()

    # --- Weights & caps ---
    weights = profile_for(arch_report.archetype, has_live_url=has_live_url)

    # --- Rubric scorer ---
    t0 = _now()
    try:
        rubric_score, rubric_resp = rubric_scorer.score(
            submission_id=submission_id,
            archetype=arch_report.archetype,
            inferred=inferred,
            code=code_report,
            ai_soph=ai_report,
            browser=browser_report,
            cross=cross_report,
            guard=guard_report,
            weights=weights,
        )
    except Exception as exc:
        _record_failure(store, submission_id, "rubric_scorer", exc)
        raise
    t1 = _now()
    _record(store, submission_id, "rubric_scorer", t0, t1, "all verifier reports", rubric_score, rubric_resp)
    budget_flags.extend(_check_budget("rubric_scorer", [rubric_resp] if rubric_resp else []))

    # --- Persist final scores ---
    integrity_flags = list(rubric_score.integrity_flags)
    if code_report.integrity_flags:
        integrity_flags.extend(code_report.integrity_flags)
    if guard_report.severity >= 2:
        integrity_flags.append(
            f"prompt_injection_severity={guard_report.severity}: "
            + "; ".join(guard_report.injection_attempts)
        )
    if not has_live_url:
        integrity_flags.append("no_reachable_live_url")
    if inferred.gaps:
        integrity_flags.extend(f"inference_gap: {g}" for g in inferred.gaps[:5])
    if budget_flags:
        integrity_flags.extend(budget_flags)
    rubric_score.integrity_flags = list(dict.fromkeys(integrity_flags))

    store.record_total(rubric_score)
    store.set_status(submission_id, SubmissionStatus.SCORED)
    logger.info(
        "[%s] pipeline done — total=%.2f (evaluable_weight=%d)",
        submission_id,
        rubric_score.total_score,
        rubric_score.evaluable_weight,
    )


def run_anchor(anchor_id: str, anchor_md_path: Path) -> Submission:
    """Register and run an anchor submission for calibration."""
    store = get_store()
    settings = get_settings()
    sub_dir = settings.submissions_dir / anchor_id
    sub_dir.mkdir(parents=True, exist_ok=True)
    target_path = sub_dir / "submission.md"
    target_path.write_text(anchor_md_path.read_text(encoding="utf-8"), encoding="utf-8")

    submission = Submission(
        id=anchor_id,
        candidate=CandidateInfo(name=anchor_id, team="anchor"),
        artifacts=SubmissionArtifacts(submission_md_path=str(target_path)),
        submission_md_raw=target_path.read_text(encoding="utf-8"),
        is_anchor=True,
        status=SubmissionStatus.PENDING,
    )
    store.upsert_submission(submission)
    run_submission(anchor_id)
    return submission


def run_pending_batch() -> list[str]:
    """Run every submission still in pending or failed state."""
    store = get_store()
    ids: list[str] = []
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT id FROM submissions WHERE status IN ('pending', 'failed') ORDER BY created_at"
        ).fetchall()
        ids = [r["id"] for r in rows]
    for sid in ids:
        try:
            run_submission(sid)
        except Exception as exc:
            logger.exception("Submission %s failed: %s", sid, exc)
    return ids
