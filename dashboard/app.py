"""Streamlit review dashboard for internal human judges.

Run with:
    streamlit run dashboard/app.py

Shows a ranked leaderboard with full traces, dimension breakdown with
provenance badges (stated / inferred / verified / insufficient), a Gaps
Flagged panel surfacing inferred gaps and insufficient_evidence reasons,
per-submission cost (precise when provider=anthropic, heuristic otherwise),
and an active-provider indicator that reads Settings directly.

Judges can record overrides (archetype, verdict, free-form notes) and
optionally trigger a re-run inline. Overrides are sticky across re-runs and
captured with auditor identity (Cloudflare Access header when present,
``USER`` otherwise) so the deliberation trail is preserved.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from autojudge.auth import current_user, require_basic_auth
from autojudge.config import get_settings
from autojudge.llm import supports_prompt_caching, supports_tool_calling
from autojudge.models import Archetype
from autojudge.rubric.dimensions import DIMENSIONS
from autojudge.trace.store import get_store


VERDICT_CHOICES = ["(no override)", "shortlist", "borderline", "below_threshold", "insufficient"]

# Board (Stream 3) taxonomies — kept here so the filter bar and chips stay in
# lockstep with the foundation store contract (AppType / verdict_effective).
APP_TYPE_CHOICES = ["web", "api", "cli", "notebook", "ml_model", "mobile", "hardware", "other"]
VERDICT_EFFECTIVE_CHOICES = [
    "shortlist",
    "borderline",
    "below_threshold",
    "insufficient",
    "quarantined",
]
STATUS_CHOICES = ["pending", "running", "scored", "failed"]
SORT_CHOICES = ["score", "app_type", "created_at", "verdict"]

VERDICT_EFFECTIVE_BADGE = {
    "shortlist": ":green-background[shortlist]",
    "borderline": ":orange-background[borderline]",
    "below_threshold": ":red-background[below]",
    "insufficient": ":gray-background[insufficient]",
    "quarantined": ":red-background[QUARANTINED]",
}
SHORTLIST_STATE_BADGE = {
    "finalist": ":blue-background[FINALIST]",
    "winner": ":violet-background[WINNER]",
}


def _parse_json_list(raw: Any) -> list:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except Exception:
        return []


def _judge_identity() -> str:
    """Best-effort identity for override audit.

    Resolution order:
      1. ``st.session_state`` from the basic-auth shim (set when MVP
         credentials are configured in the env).
      2. Cloudflare Access header (when fronting Railway in Phase 2).
      3. ``X-Forwarded-User`` (other reverse-proxy fallbacks).
      4. Local ``$USER`` for development; ``anonymous`` as a last resort.
    """
    auth_user = current_user("dashboard")
    if auth_user:
        return auth_user
    try:
        headers = st.context.headers
    except Exception:
        headers = {}
    for key in (
        "Cf-Access-Authenticated-User-Email",
        "cf-access-authenticated-user-email",
        "X-Forwarded-User",
        "x-forwarded-user",
    ):
        value = headers.get(key) if hasattr(headers, "get") else None
        if value:
            return value
    return os.environ.get("USER") or "anonymous"


# Auth gate (no-op when AUTOJUDGE_DASHBOARD_BASIC_AUTH_USER / _PASS are unset).
# Must run before any other page rendering so the login form is what the
# unauthenticated visitor sees first.
require_basic_auth("dashboard")

st.set_page_config(page_title="Agrim AutoJudge — Review", layout="wide")
store = get_store()
settings = get_settings()


PROVENANCE_BADGE = {
    "stated": ":green[stated]",
    "inferred": ":blue[inferred]",
    "verified": ":violet[verified]",
    "insufficient": ":orange[insufficient]",
    "unknown": ":gray[unknown]",
}


def _fmt_score(v: Any) -> str:
    if isinstance(v, (int, float)):
        return f"{v:.2f}"
    return "—"


@st.cache_data(ttl=10)
def _leaderboard_df(include_anchors: bool) -> pd.DataFrame:
    rows = store.leaderboard(include_anchors=include_anchors)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


@st.cache_data(ttl=10)
def _leaderboard_rows(
    include_anchors: bool,
    *,
    app_types: tuple[str, ...] | None,
    verdict: tuple[str, ...] | None,
    status: tuple[str, ...] | None,
    has_live_url: bool | None,
    finalist_only: bool,
    search: str | None,
    sort: str,
) -> list[dict[str, Any]]:
    """Board fetch — pushes every filter into the store (no Python re-filter).

    Tuples (not lists) for the cache key so Streamlit can hash the args.
    """
    return store.leaderboard(
        include_anchors=include_anchors,
        app_types=list(app_types) if app_types else None,
        verdict=list(verdict) if verdict else None,
        status=list(status) if status else None,
        has_live_url=has_live_url,
        finalist_only=finalist_only,
        search=search or None,
        sort=sort,
    )


def _provider_panel() -> None:
    primary = settings.autojudge_primary_provider
    fallback = settings.autojudge_fallback_provider or "(none)"
    caching = supports_prompt_caching(primary)
    tools = supports_tool_calling(primary)
    cols = st.columns(4)
    cols[0].metric("Primary provider", primary)
    cols[1].metric("Fallback provider", fallback)
    cols[2].metric("Prompt caching", "yes" if caching else "no")
    cols[3].metric("Tool calling", "yes" if tools else "no")
    if not caching:
        st.caption(
            "Cost figures shown below are **heuristic** for this provider. "
            "Switch `AUTOJUDGE_PRIMARY_PROVIDER=anthropic` in .env and restart "
            "the dashboard for precise per-call cost accounting."
        )
    else:
        st.caption(
            "Anthropic prompt caching active. Cost figures use API-reported "
            "cache_creation / cache_read token counts."
        )


def render_leaderboard() -> None:
    st.header("Judge board")
    st.caption(
        "Filter, scan, and shortlist entirely from here — no drill-down "
        "required. The Submission detail tab remains for optional audit."
    )
    _provider_panel()

    # --- filter / sort control bar (pushed straight into leaderboard(...)) ---
    fc1, fc2, fc3 = st.columns([2, 2, 2])
    with fc1:
        sel_app_types = st.multiselect("App type", APP_TYPE_CHOICES, key="board_app_types")
    with fc2:
        sel_verdicts = st.multiselect(
            "Verdict (effective)", VERDICT_EFFECTIVE_CHOICES, key="board_verdicts"
        )
    with fc3:
        sel_status = st.multiselect("Status", STATUS_CHOICES, key="board_status")

    fc4, fc5, fc6, fc7 = st.columns([2, 1, 1, 1])
    with fc4:
        search = st.text_input(
            "Search candidate / team", key="board_search", placeholder="name or team…"
        )
    with fc5:
        sort = st.selectbox("Sort by", SORT_CHOICES, index=0, key="board_sort")
    with fc6:
        live_only = st.checkbox("Live URL only", value=False, key="board_live_only")
    with fc7:
        finalist_only = st.checkbox("Finalists only", value=False, key="board_finalist_only")

    bc1, bc2, bc3, bc4 = st.columns([1, 1, 1, 1])
    with bc1:
        include_anchors = st.checkbox("Include calibration anchors", value=False)
    with bc2:
        top_n = st.number_input("Top N", min_value=3, max_value=200, value=10, step=1)
    with bc3:
        if st.button("Refresh"):
            _leaderboard_rows.clear()
            _leaderboard_df.clear()
            st.rerun()
    with bc4:
        auto_refresh = st.checkbox(
            "Auto-refresh while running",
            value=False,
            help="Re-render every 5s when any submission is in the RUNNING state.",
        )

    rows = _leaderboard_rows(
        include_anchors,
        app_types=tuple(sel_app_types) or None,
        verdict=tuple(sel_verdicts) or None,
        status=tuple(sel_status) or None,
        has_live_url=True if live_only else None,
        finalist_only=finalist_only,
        search=search.strip() or None,
        sort=sort,
    )
    if not rows:
        st.info("No submissions match the current filters.")
        return

    # --- compact scan table (read-only) over the filtered, store-sorted rows ---
    judge_identity = _judge_identity()
    st.caption(f"Acting as `{judge_identity}` for shortlist actions.")

    table_rows = []
    for idx, r in enumerate(rows, start=1):
        flags = _parse_json_list(r.get("integrity_flags_json"))
        quarantined = r.get("verdict_effective") == "quarantined" or bool(flags)
        eff = r.get("verdict_effective") or r.get("verdict") or "—"
        if r.get("verdict_override"):
            eff = f"{eff}*"
        table_rows.append(
            {
                "rank": r.get("shortlist_rank") or idx,
                "id": r.get("id"),
                "candidate": r.get("candidate_name"),
                "team": r.get("team") or "solo",
                "app_type": r.get("app_type") or "—",
                "score": r.get("total_score"),
                "verdict": eff,
                "shortlist": r.get("shortlist_state") or "none",
                "live": bool(r.get("live_url")),
                "integrity": "⚠" if quarantined else "",
                "review_items": len(_parse_json_list(r.get("judge_review_items_json"))),
                "status": r.get("status"),
            }
        )
    st.dataframe(
        pd.DataFrame(table_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "score": st.column_config.NumberColumn(format="%.2f"),
            "live": st.column_config.CheckboxColumn("live"),
        },
    )
    st.caption(
        "AutoJudge is a Shortlist Generator — verdicts are recommendations. "
        "An asterisk (`*`) marks a judge-overridden verdict; ⚠ flags "
        "quarantine/integrity. Open a row below for dimension chips and to "
        "mark finalist/winner."
    )

    # --- per-row expander: full evidence + inline shortlist actions ---
    st.markdown("### Decide from the board")
    for r in rows:
        _render_board_row(r, judge_identity)

    _evaluate_panel([], all_ids=[r.get("id") for r in rows])

    csv = pd.DataFrame(table_rows).head(top_n).to_csv(index=False)
    st.download_button(
        "Export top-N as CSV",
        data=csv,
        file_name=f"agrim_top{top_n}.csv",
        mime="text/csv",
    )

    if auto_refresh and any((r.get("status") or "").lower() == "running" for r in rows):
        import time as _time

        _time.sleep(5)
        _leaderboard_rows.clear()
        _leaderboard_df.clear()
        st.rerun()


def _render_board_row(r: dict[str, Any], judge_identity: str) -> None:
    """One submission, fully decided-from-here: chips + shortlist buttons."""
    sid = r.get("id")
    eff = r.get("verdict_effective") or r.get("verdict") or "—"
    flags = _parse_json_list(r.get("integrity_flags_json"))
    review_items = _parse_json_list(r.get("judge_review_items_json"))
    quarantined = eff == "quarantined" or bool(flags)
    shortlist_state = r.get("shortlist_state") or "none"
    rank = r.get("shortlist_rank")
    score = _fmt_score(r.get("total_score"))

    state_tag = SHORTLIST_STATE_BADGE.get(shortlist_state, "")
    header = (
        f"#{rank if rank is not None else '—'}  ·  {r.get('candidate_name')} "
        f"({r.get('team') or 'solo'})  ·  {score}  ·  {eff}"
        + (f"  ·  {shortlist_state.upper()}" if state_tag else "")
        + ("  ·  ⚠" if quarantined else "")
    )
    with st.expander(header, expanded=False):
        chips = [
            f":blue-background[{r.get('app_type') or '—'}]",
            VERDICT_EFFECTIVE_BADGE.get(eff, eff),
        ]
        if state_tag:
            chips.append(state_tag)
        if quarantined:
            chips.append(":red-background[INTEGRITY]")
        st.markdown("  ".join(chips))

        meta = st.columns(4)
        meta[0].metric("Total", score)
        meta[1].metric("Evaluable wt", f"{r.get('evaluable_weight', 100)}/100")
        meta[2].metric("Review items", len(review_items))
        meta[3].metric("Live URL", "yes" if r.get("live_url") else "no")

        # Six dimension chips (— for None / insufficient).
        dims = r.get("dimensions") or {}
        dim_chips = []
        for dim in DIMENSIONS:
            v = dims.get(dim.id.value) if isinstance(dims, dict) else None
            label = f"{v:.1f}" if isinstance(v, (int, float)) else "—"
            dim_chips.append(f"**{dim.name}** `{label}`")
        st.markdown("  ·  ".join(dim_chips))

        if quarantined and flags:
            st.warning("Integrity flags:\n" + "\n".join(f"- {f}" for f in flags))
        if review_items:
            st.caption(f"{len(review_items)} judge-review item(s) deferred to humans.")
        if r.get("summary"):
            st.write(r["summary"])
        if r.get("repo_url"):
            st.caption(f"Repo: {r['repo_url']}")
        if r.get("live_url"):
            st.caption(f"Live: {r['live_url']}")
        if r.get("judge_notes"):
            st.info(f"Judge notes: {r['judge_notes']}")

        st.markdown(
            f"Shortlist state: **{shortlist_state}**"
            + (f"  (by `{r.get('finalized_by')}`)" if r.get("finalized_by") else "")
        )
        ac1, ac2, ac3, _ = st.columns([1, 1, 1, 3])
        with ac1:
            if st.button("Mark finalist", key=f"finalist-{sid}", disabled=shortlist_state == "finalist"):
                store.set_finalist(sid, state="finalist", finalized_by=judge_identity)
                _leaderboard_rows.clear()
                _leaderboard_df.clear()
                st.rerun()
        with ac2:
            if st.button("Mark winner", key=f"winner-{sid}", type="primary", disabled=shortlist_state == "winner"):
                store.set_finalist(sid, state="winner", finalized_by=judge_identity)
                _leaderboard_rows.clear()
                _leaderboard_df.clear()
                st.rerun()
        with ac3:
            if st.button("Clear", key=f"clear-finalist-{sid}", disabled=shortlist_state == "none"):
                store.set_finalist(sid, state="none", finalized_by=judge_identity)
                _leaderboard_rows.clear()
                _leaderboard_df.clear()
                st.rerun()


def _evaluate_panel(selected_ids: list[str], *, all_ids: list[str]) -> None:
    """Render the 'Evaluate selected' UI directly under the leaderboard.

    Selected ids → spawn one background subprocess per submission (the worker
    is the same ``autojudge run <id>`` invocation the override panel uses, so
    behaviour is identical for re-runs). Postgres status reflects RUNNING /
    SCORED / FAILED back to the table. ``Refresh`` or auto-refresh re-renders.
    """
    st.markdown("### Run evaluations")
    if not all_ids:
        st.info("Nothing to evaluate yet.")
        return

    btn_cols = st.columns([2, 2, 2, 4])
    with btn_cols[0]:
        run_selected = st.button(
            f"Evaluate selected ({len(selected_ids)})",
            type="primary",
            disabled=not selected_ids,
            help="Re-run the AI pipeline on every ticked row.",
            key="evaluate_selected_btn",
        )
    with btn_cols[1]:
        pending_ids = [
            sid for sid in get_store().list_pending_submission_ids()
            if sid in all_ids
        ]
        run_pending = st.button(
            f"Evaluate all pending ({len(pending_ids)})",
            disabled=not pending_ids,
            help="Run every submission whose status is `pending` or `failed`.",
            key="evaluate_pending_btn",
        )
    with btn_cols[2]:
        run_all = st.button(
            f"Evaluate all ({len(all_ids)})",
            help=(
                "Full re-score for every submission shown — useful after "
                "you change weights, rubric anchors, or judge overrides."
            ),
            key="evaluate_all_btn",
        )
    with btn_cols[3]:
        st.caption(
            "Each submission runs in the background on this dashboard "
            "service. Watch the **status** column update; the row turns "
            "`running` while the agents are working and `scored`/`failed` "
            "when done."
        )

    ids_to_run: list[str] = []
    if run_selected:
        ids_to_run = list(selected_ids)
    elif run_pending:
        ids_to_run = pending_ids
    elif run_all:
        ids_to_run = list(all_ids)

    if not ids_to_run:
        return

    started, skipped = _launch_evaluations(ids_to_run)
    if started:
        st.success(
            f"Queued {len(started)} evaluation(s). Refresh (or tick "
            "auto-refresh) to track progress."
        )
        with st.expander("Queued submissions", expanded=False):
            for sid in started:
                st.write(f"- `{sid}`")
    if skipped:
        st.warning(
            f"Skipped {len(skipped)} submission(s) already in `running` state:\n"
            + "\n".join(f"- `{sid}`" for sid in skipped)
        )
    _leaderboard_df.clear()


def _launch_evaluations(submission_ids: list[str]) -> tuple[list[str], list[str]]:
    """Spawn one ``autojudge run <id>`` subprocess per id, skipping RUNNING rows.

    Returns ``(started, skipped)``. The subprocess approach mirrors the
    existing ``Save & re-run`` button — robust to Streamlit auto-reloads,
    and the only thing the dashboard needs to do afterwards is poll the
    store for status changes.
    """
    store = get_store()
    started: list[str] = []
    skipped: list[str] = []
    for sid in submission_ids:
        sub = store.get_submission(sid)
        if not sub:
            continue
        if (sub.get("status") or "").lower() == "running":
            skipped.append(sid)
            continue
        try:
            _spawn_rerun(sid)
            started.append(sid)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to launch `{sid}`: {exc}")
    return started, skipped


def _inference_output_for(submission_id: str) -> dict[str, Any] | None:
    """Pull the most recent inference run output to surface gaps + summary."""
    runs = store.get_runs(submission_id)
    for run in reversed(runs):
        if run["agent"] == "inference":
            try:
                return json.loads(run["output_json"])
            except Exception:
                return None
    return None


def render_submission(submission_id: str) -> None:
    sub = store.get_submission(submission_id)
    if not sub:
        st.error(f"Submission {submission_id} not found.")
        return
    total = store.get_total(submission_id)
    scores = store.get_scores(submission_id)
    runs = store.get_runs(submission_id)
    cost_info = store.get_submission_cost(submission_id)

    st.subheader(f"{submission_id}")
    st.caption(
        f"Candidate: **{sub['candidate_name']}**  |  Team: {sub['team'] or 'solo'}  |  "
        f"Status: {sub['status']}"
    )

    cols = st.columns(6)
    cols[0].metric("Total", _fmt_score(total["total_score"]) if total else "—")
    auto_verdict = (total or {}).get("verdict") or "—"
    verdict_override = (total or {}).get("verdict_override")
    if verdict_override:
        verdict_label = f"{verdict_override}*"
        verdict_help = f"Judge override. Auto-judge said: {auto_verdict}."
    else:
        verdict_label = auto_verdict
        verdict_help = "Auto-judge recommendation. No human override."
    cols[1].metric("Verdict", verdict_label, help=verdict_help)
    cols[2].metric("Archetype", sub["archetype"])
    cols[3].metric("Live URL", "yes" if sub["live_url"] else "no")
    if total:
        cols[4].metric(
            "Evaluable weight",
            f"{total.get('evaluable_weight', 100)}/100",
        )
    else:
        cols[4].metric("Evaluable weight", "—")
    cost_label = "precise" if cost_info["all_precise"] and cost_info["run_count"] else "heuristic"
    cols[5].metric(
        "Cost (USD)",
        f"${cost_info['total_cost']:.4f}",
        help=f"{cost_label} — {cost_info['run_count']} verifier runs",
    )

    if total and total.get("normalized"):
        st.warning(
            "Score is normalised over evaluable dimensions only. "
            "See the 'insufficient' dimensions below for the unscored areas."
        )

    flags = json.loads(total["integrity_flags_json"]) if total and total.get("integrity_flags_json") else []
    cause_flags = [f for f in flags if f.startswith("insufficient_cause:")]
    if cause_flags:
        st.info(
            "⚠️ **Credential-walled — needs test credentials, not weak work.** "
            + " ".join(f[len("insufficient_cause:"):].strip() for f in cause_flags)
        )
    other_flags = [f for f in flags if not f.startswith("insufficient_cause:")]
    if other_flags:
        st.warning("Integrity flags:\n" + "\n".join(f"- {f}" for f in other_flags))

    inference_out = _inference_output_for(submission_id)

    judge_review_panel(total)
    gaps_panel(total, inference_out)

    if total and total.get("summary"):
        st.markdown("### Scorer summary")
        st.write(total["summary"])

    st.markdown("### Artifacts")
    if sub["repo_url"]:
        st.write(f"- Repo: {sub['repo_url']}")
    if sub["live_url"]:
        st.write(f"- Live URL: {sub['live_url']}")
    if sub["video_url"]:
        st.write(f"- Video: {sub['video_url']}")
    if sub["deck_path"]:
        st.write(f"- Deck path: `{sub['deck_path']}`")

    st.markdown("### Dimension breakdown")
    by_id = {s["dimension"]: s for s in scores}
    for dim in DIMENSIONS:
        s = by_id.get(dim.id.value)
        ekind = (s or {}).get("evidence_kind", "inferred")
        badge = PROVENANCE_BADGE.get(ekind, ekind)
        if s and s["raw_score"] is not None:
            header = (
                f"{dim.name} — {s['raw_score']:.1f}/10 "
                f"(weighted {s['weighted_score']:.2f}/{dim.base_weight})  {badge}"
            )
        else:
            header = f"{dim.name} — insufficient_evidence  {badge}"
        with st.expander(header, expanded=False):
            if not s:
                st.info("No score recorded.")
                continue
            st.write(s["rationale"])
            if s["cap_applied"]:
                st.warning(f"Cap applied: {s['cap_reason']}")
            evidence = json.loads(s["evidence_json"] or "[]")
            if evidence:
                st.markdown("**Evidence:**")
                for e in evidence:
                    st.write(f"- {e}")

    if inference_out:
        with st.expander("Inferred submission (provenance trail)", expanded=False):
            st.json(inference_out, expanded=False)

    st.markdown("### Agent trace")
    for run in runs:
        precise_marker = (
            " (precise)" if run.get("cost_is_precise") else " (heuristic)"
            if run["cost_usd"] else ""
        )
        with st.expander(
            f"{run['agent']}  ({run['provider'] or '-'}, model={run['model'] or '-'})  "
            f"started={run['started_at']}",
            expanded=False,
        ):
            st.caption(
                f"input summary: {run['input_summary']}  |  "
                f"cost ~${run['cost_usd']:.4f}{precise_marker}"
                + (f"  |  error: {run['error'][:200]}" if run["error"] else "")
            )
            try:
                payload = json.loads(run["output_json"])
                st.json(payload, expanded=False)
            except Exception:
                st.code(run["output_json"][:5000])

    override_panel(submission_id, sub, total)

    raw_path = json.loads(sub.get("extras_json") or "{}").get("submission_md_path")
    if raw_path and Path(raw_path).exists():
        st.markdown("### Free-form context (raw)")
        st.code(Path(raw_path).read_text(encoding="utf-8")[:20000], language="markdown")


def override_panel(
    submission_id: str,
    sub: dict[str, Any],
    total: dict[str, Any] | None,
) -> None:
    """Archetype + verdict + judge-notes overrides, with optional inline re-run.

    - Archetype writes to ``submissions.archetype`` (read by the next pipeline
      run; an explicit re-run is needed to recompute weights).
    - Verdict override + notes live on ``totals`` and are sticky across
      re-runs.
    - Inline re-run spawns ``autojudge run <id>`` as a background process so
      Streamlit stays responsive. Status polls via the Refresh button.
    """
    st.markdown("### Override")
    judge_identity = _judge_identity()
    st.caption(f"Acting as: `{judge_identity}` (captured from request headers)")

    current_archetype = sub["archetype"]
    current_verdict_override = (total or {}).get("verdict_override") or "(no override)"
    current_notes = (total or {}).get("judge_notes") or ""
    overridden_by = (total or {}).get("overridden_by")
    overridden_at = (total or {}).get("overridden_at")

    col1, col2 = st.columns(2)
    with col1:
        new_archetype = st.selectbox(
            "Archetype override",
            options=[a.value for a in Archetype],
            index=[a.value for a in Archetype].index(current_archetype),
            key=f"arch-{submission_id}",
            help="A re-score is required for the new archetype to change weights.",
        )
    with col2:
        new_verdict = st.selectbox(
            "Verdict override",
            options=VERDICT_CHOICES,
            index=VERDICT_CHOICES.index(current_verdict_override)
            if current_verdict_override in VERDICT_CHOICES
            else 0,
            key=f"verd-{submission_id}",
            help="Mark shortlist/borderline/below regardless of the auto-score.",
        )
    new_notes = st.text_area(
        "Judge notes",
        value=current_notes,
        max_chars=2000,
        height=120,
        key=f"notes-{submission_id}",
        help="Free-form rationale for the override. Surfaced in inspect/export.",
    )

    if overridden_by:
        st.caption(
            f"Last overridden by `{overridden_by}` at {overridden_at or 'unknown'}."
        )

    btn_save, btn_save_rerun, btn_clear = st.columns([1, 1, 1])

    archetype_changed = new_archetype != current_archetype
    verdict_value = None if new_verdict == "(no override)" else new_verdict
    notes_value = new_notes.strip() or None
    overrides_changed = (
        verdict_value != ((total or {}).get("verdict_override") or None)
        or notes_value != ((total or {}).get("judge_notes") or None)
        or archetype_changed
    )

    with btn_save:
        if st.button(
            "Save overrides",
            key=f"save-{submission_id}",
            disabled=not overrides_changed,
        ):
            _persist_overrides(
                submission_id=submission_id,
                archetype=new_archetype if archetype_changed else None,
                verdict=verdict_value if verdict_value != ((total or {}).get("verdict_override") or None) else None,
                notes=notes_value if notes_value != ((total or {}).get("judge_notes") or None) else None,
                overridden_by=judge_identity if (verdict_value is not None or notes_value is not None) else None,
                total=total,
            )
            _leaderboard_df.clear()
            st.success("Overrides saved.")
            st.rerun()

    with btn_save_rerun:
        if st.button(
            "Save & re-run",
            key=f"save-rerun-{submission_id}",
            type="primary",
            help="Persist overrides, then trigger a full pipeline re-run for this submission.",
        ):
            _persist_overrides(
                submission_id=submission_id,
                archetype=new_archetype if archetype_changed else None,
                verdict=verdict_value if verdict_value != ((total or {}).get("verdict_override") or None) else None,
                notes=notes_value if notes_value != ((total or {}).get("judge_notes") or None) else None,
                overridden_by=judge_identity if (verdict_value is not None or notes_value is not None) else None,
                total=total,
            )
            log_path = _spawn_rerun(submission_id)
            _leaderboard_df.clear()
            st.info(
                f"Re-run queued. Tail the worker log at `{log_path}`. "
                "Status here will update to RUNNING; refresh to track progress."
            )
            st.rerun()

    with btn_clear:
        has_overrides = bool(
            (total or {}).get("verdict_override")
            or (total or {}).get("judge_notes")
            or (total or {}).get("overridden_by")
        )
        if st.button(
            "Clear override",
            key=f"clear-{submission_id}",
            disabled=not has_overrides,
            help="Wipe verdict/notes/auditor. Archetype is not cleared.",
        ):
            store.clear_judge_override(submission_id)
            _leaderboard_df.clear()
            st.success("Override cleared.")
            st.rerun()


def _persist_overrides(
    *,
    submission_id: str,
    archetype: str | None,
    verdict: str | None,
    notes: str | None,
    overridden_by: str | None,
    total: dict[str, Any] | None,
) -> None:
    """Single entry point so 'Save' and 'Save & re-run' stay in lockstep.

    Passes only the fields that actually changed so the store doesn't bump
    ``overridden_by`` / ``overridden_at`` on a no-op.
    """
    if archetype is None and verdict is None and notes is None:
        return
    if total is None and (verdict is not None or notes is not None):
        st.warning(
            "Submission has no scored total yet; verdict and notes overrides "
            "are persisted but won't surface until the pipeline runs at least "
            "once."
        )
    store.set_judge_override(
        submission_id,
        archetype=archetype,
        verdict=verdict if verdict is not None else None,
        notes=notes if notes is not None else None,
        overridden_by=overridden_by,
    )


def _spawn_rerun(submission_id: str) -> Path:
    """Fire-and-forget ``autojudge run <id>`` so Streamlit stays responsive.

    Stdout/stderr go to ``data/submissions/<id>/last_run.log`` so the operator
    can tail it from the Railway shell.
    """
    settings = get_settings()
    log_dir = settings.submissions_dir / submission_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "last_run.log"
    log_handle = open(log_path, "ab")
    subprocess.Popen(  # noqa: S603 - controlled args
        [sys.executable, "-m", "autojudge.cli", "run", submission_id],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        cwd=Path.cwd(),
        close_fds=True,
    )
    return log_path


def judge_review_panel(total: dict[str, Any] | None) -> None:
    """Render the judge-review items: claims AutoJudge could not verify.

    These were NOT penalised in the score; they are deferred to the human
    deliberation meeting. Surfacing them prominently is the central UX move
    of the Shortlist Generator framing.
    """
    if not total or not total.get("judge_review_items_json"):
        return
    try:
        items = json.loads(total["judge_review_items_json"]) or []
    except Exception:
        return
    if not items:
        return
    st.markdown(f"### Judge-review items ({len(items)})")
    st.caption(
        "These claims were not penalised in the auto-score because AutoJudge "
        "cannot verify them from the public surface (credentials, third-party "
        "workspaces, hardware, private integrations). Human judges should "
        "verify each before the final decision."
    )
    for item in items:
        with st.container(border=True):
            st.markdown(f"**Claim:** {item.get('claim', '')}")
            if item.get("reason"):
                st.write(f"_Why human review:_ {item['reason']}")
            tag = item.get("source") or item.get("where") or "inferred_submission"
            st.caption(f"Source: `{tag}`")


def gaps_panel(
    total: dict[str, Any] | None,
    inference_out: dict[str, Any] | None,
) -> None:
    """Combine Inference Agent gaps + insufficient_evidence reasons into one panel."""
    gaps_inf = (inference_out or {}).get("gaps", []) if inference_out else []
    flags = []
    if total and total.get("integrity_flags_json"):
        flags = json.loads(total["integrity_flags_json"])
    if not gaps_inf and not flags:
        return
    st.markdown("### Gaps flagged")
    if gaps_inf:
        st.markdown("**Inference Agent noted these gaps:**")
        for g in gaps_inf:
            st.write(f"- {g}")
    insufficient = [f for f in flags if "insufficient" in f.lower() or "gap" in f.lower()]
    if insufficient:
        st.markdown("**Scorer integrity flags relevant to gaps:**")
        for f in insufficient:
            st.write(f"- {f}")


# --- layout ---

st.title("Agrim AutoJudge")
st.caption(
    "Internal judging dashboard. Provider routing is .env-driven; "
    "edit `.env` and restart this app to change provider."
)

tab_lb, tab_sub = st.tabs(["Leaderboard", "Submission detail"])

with tab_lb:
    render_leaderboard()

with tab_sub:
    df = _leaderboard_df(include_anchors=True)
    if df.empty:
        st.info("No submissions yet. Run the pipeline first.")
    else:
        selected = st.selectbox("Pick a submission", options=df["id"].tolist())
        if selected:
            render_submission(selected)
