"""Command-line interface for Agrim AutoJudge.

Commands:
- autojudge ingest-flexible        Register a submission from any combination
                                   of repo / live / video / deck / context.
- autojudge run <submission_id>    Run the full pipeline on one submission.
- autojudge run-batch              Run pending+failed submissions in store.
- autojudge run-anchors            Re-run the three calibration anchors.
- autojudge leaderboard            Print the ranked leaderboard.
- autojudge inspect <submission_id>  Dump scores + traces for one submission.
- autojudge doctor                 Print resolved provider/model/key matrix.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import get_settings
from .models import (
    CandidateInfo,
    Submission,
    SubmissionArtifacts,
    SubmissionStatus,
)
from .orchestrator import run_anchor, run_pending_batch, run_submission
from .rubric.anchors import ANCHORS, MAX_DRIFT, anchors_dir
from .trace.store import get_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = typer.Typer(help="Agrim AutoJudge command line.", no_args_is_help=True)
console = Console()


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "anon"


@app.command("ingest-flexible")
def ingest_flexible(
    name: str = typer.Option(..., "--name", help="Candidate name"),
    repo_url: str | None = typer.Option(None, "--repo", help="GitHub repo URL"),
    live_url: str | None = typer.Option(None, "--live", help="Live deployed URL"),
    video_url: str | None = typer.Option(None, "--video", help="YouTube demo URL"),
    deck_path: Path | None = typer.Option(None, "--deck", help="Slide deck PDF path"),
    context: Path | None = typer.Option(
        None, "--context", help="Optional free-form context file (any text/markdown)"
    ),
    email: str | None = typer.Option(None, "--email"),
    team: str | None = typer.Option(None, "--team"),
    credentials: str | None = typer.Option(None, "--creds"),
) -> None:
    """Register a submission from any subset of artifacts. At least one of
    --repo, --live, --video, or --deck is required. Free-form context is
    optional and may be supplied via --context.
    """
    if not any([repo_url, live_url, video_url, deck_path]):
        console.print(
            "[red]Provide at least one of --repo, --live, --video, or --deck.[/red]"
        )
        raise typer.Exit(code=1)

    settings = get_settings()
    store = get_store()
    sub_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + _slug(name)
    sub_dir = settings.submissions_dir / sub_id
    sub_dir.mkdir(parents=True, exist_ok=True)

    target_md = sub_dir / "submission.md"
    if context and context.exists():
        body = context.read_text(encoding="utf-8").strip()
    else:
        body = ""
    if not body:
        body = "(no free-form context supplied; rely on linked artifacts)"
    target_md.write_text(body + "\n", encoding="utf-8")

    target_deck: str | None = None
    deck_bytes: bytes | None = None
    if deck_path:
        deck_bytes = deck_path.read_bytes()
        target_deck = str(sub_dir / "deck.pdf")
        Path(target_deck).write_bytes(deck_bytes)

    submission = Submission(
        id=sub_id,
        candidate=CandidateInfo(name=name, email=email, team=team),
        artifacts=SubmissionArtifacts(
            submission_md_path=str(target_md),
            repo_url=repo_url,
            live_url=live_url,
            video_url=video_url,
            deck_path=target_deck,
            test_credentials=credentials,
        ),
        submission_md_raw=body,
        status=SubmissionStatus.PENDING,
    )
    store.upsert_submission(submission)
    if deck_bytes is not None:
        store.put_blob(sub_id, "deck.pdf", deck_bytes, content_type="application/pdf")
    console.print(f"[green]Registered submission[/green] {sub_id}")


@app.command()
def run(submission_id: str) -> None:
    """Run the pipeline on a single submission."""
    run_submission(submission_id)
    inspect(submission_id)


@app.command("run-batch")
def run_batch() -> None:
    """Run the pipeline on all pending and failed submissions."""
    ids = run_pending_batch()
    console.print(f"[green]Ran {len(ids)} submissions[/green]")
    leaderboard()


@app.command("run-anchors")
def run_anchors() -> None:
    """Re-run the calibration anchors; warn if any drifts beyond MAX_DRIFT."""
    base = anchors_dir()
    drifts: list[tuple[str, float, float]] = []
    for a in ANCHORS:
        md_path = base / a.filename
        if not md_path.exists():
            console.print(f"[yellow]Anchor file missing: {md_path}[/yellow]")
            continue
        run_anchor(a.id, md_path)
        total_row = get_store().get_total(a.id)
        actual = float(total_row["total_score"]) if total_row else 0.0
        drift = actual - a.expected_total
        drifts.append((a.id, actual, drift))
        marker = "[green]OK[/green]" if abs(drift) <= MAX_DRIFT else "[red]DRIFT[/red]"
        console.print(
            f"{marker} {a.id}: expected~{a.expected_total:.1f}  actual={actual:.1f}  drift={drift:+.1f}"
        )
    failing = [d for d in drifts if abs(d[2]) > MAX_DRIFT]
    if failing:
        console.print("[red]One or more anchors drifted beyond tolerance — review before publishing.[/red]")
        sys.exit(1)


@app.command()
def leaderboard(include_anchors: bool = typer.Option(False, "--anchors")) -> None:
    """Print the ranked shortlist with verdicts and review-item counts."""
    rows = get_store().leaderboard(include_anchors=include_anchors)
    table = Table(title="Agrim AutoJudge — Shortlist (recommendation, not final verdict)")
    table.add_column("Rank")
    table.add_column("Submission")
    table.add_column("Candidate")
    table.add_column("Archetype")
    table.add_column("Total", justify="right")
    table.add_column("Verdict")
    table.add_column("Review items", justify="right")
    table.add_column("Notes", overflow="fold")
    table.add_column("Status")
    verdict_color = {
        "shortlist": "green",
        "borderline": "yellow",
        "below_threshold": "red",
        "insufficient": "magenta",
    }
    for row in rows:
        score = f"{row['total_score']:.2f}" if row["total_score"] is not None else "—"
        auto_verdict = row.get("verdict") or "—"
        override = row.get("verdict_override")
        effective = override or auto_verdict
        verdict_display = (
            f"[{verdict_color.get(effective, 'white')}]{effective}*[/]"
            if override
            else f"[{verdict_color.get(auto_verdict, 'white')}]{auto_verdict}[/]"
        )
        rank = row.get("shortlist_rank")
        review_items = []
        if row.get("judge_review_items_json"):
            try:
                review_items = json.loads(row["judge_review_items_json"])
            except Exception:
                review_items = []
        notes_preview = (row.get("judge_notes") or "").strip().splitlines()
        notes_short = (notes_preview[0][:60] + "…") if notes_preview and len(notes_preview[0]) > 60 else (notes_preview[0] if notes_preview else "")
        table.add_row(
            str(rank) if rank is not None else "—",
            row["id"],
            row["candidate_name"],
            row["archetype"] or "?",
            score,
            verdict_display,
            str(len(review_items)),
            notes_short,
            row["status"],
        )
    console.print(table)
    console.print(
        "[dim]Verdicts ending in `*` were overridden by a human judge; the "
        "auto-judge's recommendation is preserved in the trace.[/dim]"
    )


@app.command()
def inspect(submission_id: str) -> None:
    """Dump scores + runs + judge-review items for one submission."""
    store = get_store()
    sub = store.get_submission(submission_id)
    if not sub:
        console.print(f"[red]Submission not found: {submission_id}[/red]")
        return
    total = store.get_total(submission_id)
    scores = store.get_scores(submission_id)
    console.print({"submission": sub, "total": total})

    table = Table(title=f"Dimension scores — {submission_id}")
    for col in ("dimension", "raw_score", "weighted_score", "evidence_kind", "cap_applied", "rationale"):
        table.add_column(col)
    for s in scores:
        raw = f"{s['raw_score']:.1f}" if s["raw_score"] is not None else "—"
        weighted = f"{s['weighted_score']:.2f}" if s["weighted_score"] is not None else "—"
        table.add_row(
            s["dimension"],
            raw,
            weighted,
            s.get("evidence_kind") or "inferred",
            "yes" if s["cap_applied"] else "no",
            (s["rationale"] or "")[:120],
        )
    console.print(table)

    if total and total.get("verdict"):
        override = total.get("verdict_override")
        if override:
            console.print(
                f"\n[bold]Verdict:[/bold] [yellow]{override}*[/yellow]  "
                f"(auto-judge said: {total['verdict']})"
            )
            if total.get("overridden_by") or total.get("overridden_at"):
                console.print(
                    f"  [dim]overridden by {total.get('overridden_by') or '?'} "
                    f"at {total.get('overridden_at') or '?'}[/dim]"
                )
            if total.get("judge_notes"):
                console.print(f"\n[bold]Judge notes:[/bold]\n{total['judge_notes']}")
        else:
            console.print(f"\n[bold]Verdict:[/bold] {total['verdict']}")
            if total.get("judge_notes"):
                console.print(f"\n[bold]Judge notes:[/bold]\n{total['judge_notes']}")

    review_items_json = (total or {}).get("judge_review_items_json")
    if review_items_json:
        try:
            review_items = json.loads(review_items_json)
        except Exception:
            review_items = []
        if review_items:
            review_table = Table(
                title=f"Judge-review items ({len(review_items)}) — not penalised, defer to humans"
            )
            review_table.add_column("Claim")
            review_table.add_column("Reason")
            review_table.add_column("Source")
            for item in review_items:
                review_table.add_row(
                    (item.get("claim") or "")[:120],
                    (item.get("reason") or "")[:120],
                    item.get("source") or "—",
                )
            console.print(review_table)


@app.command("export-top")
def export_top(
    n: int = typer.Option(10, "--n"),
    out: Path = typer.Option(Path("data/top10.json"), "--out"),
) -> None:
    """Export the top-N shortlisted submissions to JSON for human judges.

    Each row includes the auto-score, verdict, judge_review_items, and any
    human override (verdict, notes, auditor, timestamp) so the deliberation
    meeting has the full evidence pack and audit trail for each candidate.
    """
    rows = get_store().leaderboard()
    top = rows[:n]
    for row in top:
        if row.get("judge_review_items_json"):
            try:
                row["judge_review_items"] = json.loads(row["judge_review_items_json"])
            except Exception:
                row["judge_review_items"] = []
        else:
            row["judge_review_items"] = []
        row["override"] = {
            "verdict_override": row.get("verdict_override"),
            "judge_notes": row.get("judge_notes"),
            "overridden_by": row.get("overridden_by"),
            "overridden_at": row.get("overridden_at"),
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(top, indent=2, default=str), encoding="utf-8")
    console.print(f"[green]Wrote top {len(top)} shortlist entries to {out}[/green]")


@app.command("serve-healthz")
def serve_healthz(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8500, "--port"),
) -> None:
    """Run the stdlib healthz HTTP server (foreground).

    Intended for the worker container on Railway — pairs with a ``run-batch``
    loop so the container has a real healthcheck endpoint while still
    processing pending submissions.
    """
    from .server.healthz import serve

    console.print(f"[green]healthz[/green] listening on http://{host}:{port}/healthz")
    serve(host=host, port=port)


@app.command()
def gc(
    days: int | None = typer.Option(
        None,
        "--days",
        help="Override AUTOJUDGE_SNAPSHOT_TTL_DAYS for this invocation.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="List candidates without deleting."),
) -> None:
    """Evict repo snapshot tarballs older than the TTL.

    Snapshots live at ``data/submissions/<id>/repo_cache/snapshot.tar.gz`` and
    range ~3-50 MB each. On a Railway Hobby volume (10 GB) they accumulate
    fast; this command keeps the volume tidy without touching trace data.
    Submission DB rows are untouched — a re-run will simply re-download.
    """
    import time

    settings = get_settings()
    ttl_days = days if days is not None else settings.autojudge_snapshot_ttl_days
    cutoff = time.time() - ttl_days * 86_400
    submissions_root = settings.submissions_dir
    if not submissions_root.exists():
        console.print("[yellow]No submissions directory; nothing to evict.[/yellow]")
        return

    evicted = 0
    bytes_freed = 0
    for tar_path in submissions_root.glob("*/repo_cache/snapshot.tar.gz"):
        try:
            stat = tar_path.stat()
        except OSError:
            continue
        if stat.st_mtime > cutoff:
            continue
        bytes_freed += stat.st_size
        if dry_run:
            console.print(
                f"[yellow]would evict[/yellow] {tar_path} "
                f"({stat.st_size / (1024**2):.2f} MB)"
            )
        else:
            try:
                tar_path.unlink()
                evicted += 1
            except OSError as exc:
                console.print(f"[red]could not delete {tar_path}: {exc}[/red]")
                continue
    if dry_run:
        console.print(
            f"[green]Dry run:[/green] {bytes_freed / (1024**2):.1f} MB would be freed."
        )
    else:
        console.print(
            f"[green]Evicted {evicted} snapshots, freed "
            f"{bytes_freed / (1024**2):.1f} MB.[/green]"
        )


@app.command()
def purge(
    submission_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Permanently delete a submission (DB rows + on-disk artifacts).

    Used to nuke spam / test submissions before the top-N export. Cannot be
    undone — confirmation prompt unless ``--yes`` is passed.
    """
    settings = get_settings()
    store = get_store()
    sub = store.get_submission(submission_id)
    if not sub:
        console.print(f"[red]Submission not found: {submission_id}[/red]")
        raise typer.Exit(code=1)

    sub_dir = settings.submissions_dir / submission_id
    console.print(
        f"[bold red]About to purge[/bold red] {submission_id}\n"
        f"  candidate: {sub.get('candidate_name')}\n"
        f"  on-disk:   {sub_dir if sub_dir.exists() else '(not present)'}\n"
        f"  status:    {sub.get('status')}"
    )
    if not yes:
        confirmed = typer.confirm("This cannot be undone. Continue?")
        if not confirmed:
            console.print("Aborted.")
            raise typer.Exit(code=0)

    store.purge_submission(submission_id)
    if sub_dir.exists():
        import shutil

        try:
            shutil.rmtree(sub_dir)
        except OSError as exc:
            console.print(
                f"[yellow]DB rows deleted, but could not remove {sub_dir}: {exc}[/yellow]"
            )
            raise typer.Exit(code=1)
    console.print(f"[green]Purged[/green] {submission_id}")


@app.command()
def doctor() -> None:
    """Health-check the runtime environment.

    Checks (in order):
    - provider routing and API-key presence
    - GITHUB_TOKEN
    - Playwright Chromium binary present
    - disk space for snapshot cache
    - anchor drift (totals already on file vs expected)
    """
    from .llm import supports_prompt_caching, supports_tool_calling

    settings = get_settings()
    primary = settings.autojudge_primary_provider
    fallback = settings.autojudge_fallback_provider

    table = Table(title="Agrim AutoJudge — env-driven routing")
    table.add_column("Provider")
    table.add_column("API key")
    table.add_column("Reasoning model")
    table.add_column("Extraction model")
    table.add_column("Caching")
    table.add_column("Tool calling")
    table.add_column("Role")

    for provider in ("groq", "gemini", "openrouter", "anthropic"):
        key = settings.api_key_for(provider)  # type: ignore[arg-type]
        role: list[str] = []
        if provider == primary:
            role.append("primary")
        if fallback and provider == fallback:
            role.append("fallback")
        table.add_row(
            provider,
            "[green]set[/green]" if key else "[red]missing[/red]",
            settings.model_for(provider, "reasoning"),  # type: ignore[arg-type]
            settings.model_for(provider, "extraction"),  # type: ignore[arg-type]
            "yes" if supports_prompt_caching(provider) else "no",  # type: ignore[arg-type]
            "yes" if supports_tool_calling(provider) else "no",  # type: ignore[arg-type]
            ", ".join(role) or "-",
        )

    console.print(table)

    failures: list[str] = []
    warnings: list[str] = []

    if not settings.api_key_for(primary):
        failures.append(
            f"Primary provider '{primary}' has no API key configured. Pipeline "
            "calls will fail until you set the key in .env and restart any "
            "long-running Streamlit processes."
        )

    # --- GitHub token ---
    if settings.github_token:
        console.print("[green]GITHUB_TOKEN[/green] set (5000 req/hr authenticated limit).")
    else:
        warnings.append(
            "GITHUB_TOKEN is not set. Unauthenticated GitHub allows only 60 "
            "requests/hour per IP — the pipeline will fail with "
            "GitHubRateLimitError after a handful of submissions. Add a "
            "fine-grained PAT (Contents:Read, Metadata:Read) to .env."
        )

    # --- Playwright Chromium binary ---
    ok, where = _playwright_chromium_status()
    if ok:
        console.print(f"[green]Playwright Chromium[/green] detected: {where}")
    else:
        warnings.append(
            f"Playwright Chromium binary not found ({where}). Run "
            "`playwright install chromium`. Browser verification will be "
            "skipped until this is fixed."
        )

    # --- Disk space for snapshot cache ---
    free_gb = _free_disk_gb(settings.autojudge_data_dir)
    if free_gb is None:
        warnings.append(f"Could not stat disk space for {settings.autojudge_data_dir}.")
    elif free_gb < 1.0:
        failures.append(
            f"Only {free_gb:.2f} GB free on {settings.autojudge_data_dir}. "
            "Snapshot cache + screenshots need ~50-100 MB per submission; "
            "clear space before running a batch."
        )
    elif free_gb < 5.0:
        warnings.append(
            f"Free disk {free_gb:.2f} GB on {settings.autojudge_data_dir} — "
            "tight for batches over ~50 submissions. Consider clearing old "
            "data/submissions/*/repo_cache/ entries."
        )
    else:
        console.print(f"[green]Disk[/green] {free_gb:.1f} GB free on {settings.autojudge_data_dir}.")

    # --- Outbound HTTPS smoke (catches Railway sandbox firewalling) ---
    out_status, out_warning, out_failure = _check_outbound_https()
    if out_status:
        console.print(out_status)
    if out_warning:
        warnings.append(out_warning)
    if out_failure:
        failures.append(out_failure)

    # --- Submission live-URL probes (warnings only) ---
    live_table = _check_submission_live_urls()
    if live_table is not None:
        console.print(live_table)

    # --- Snapshot cache footprint ---
    cache_warning = _snapshot_cache_warning(settings.autojudge_data_dir)
    if cache_warning:
        warnings.append(cache_warning)

    # --- Anchor drift ---
    drift_report = _anchor_drift_summary()
    if drift_report:
        console.print(drift_report)

    # --- Trace store backend (printed regardless of failures so the operator
    # can confirm Postgres took effect even if other probes complain). ---
    backend = get_store().backend_name()
    console.print(f"[bold cyan]Trace store backend:[/bold cyan] {backend}")
    if backend == "sqlite" and settings.database_url:
        warnings.append(
            "DATABASE_URL is set but the store is still SQLite — likely a "
            "Pydantic parsing issue or the env var was not exported. "
            "Re-export and restart the service."
        )

    for w in warnings:
        console.print(f"[yellow]warning[/yellow] {w}")
    for f in failures:
        console.print(f"[red]error[/red] {f}")
    if failures:
        raise typer.Exit(code=1)

    cache = "yes" if supports_prompt_caching(primary) else "no"
    console.print(
        f"[green]Routing OK[/green] — primary={primary}, fallback={fallback or '(none)'}; "
        f"prompt caching={cache}"
    )


def _playwright_chromium_status() -> tuple[bool, str]:
    """Detect any usable Chromium binary in the Playwright cache.

    Looks for `chromium-*` (full browser, used by channel='chromium') or
    `chromium_headless_shell-*` (older default). Returns (ok, path-or-reason).
    """
    cache_dir = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not cache_dir.exists():
        # Linux / CI fallback
        cache_dir = Path.home() / ".cache" / "ms-playwright"
    if not cache_dir.exists():
        return False, f"Playwright cache dir not found at {cache_dir}"
    found: list[str] = []
    try:
        for entry in cache_dir.iterdir():
            if entry.is_dir() and (
                entry.name.startswith("chromium-")
                or entry.name.startswith("chromium_headless_shell-")
            ):
                found.append(entry.name)
    except Exception as exc:
        return False, f"could not enumerate {cache_dir}: {exc}"
    if not found:
        return False, f"no Chromium binary in {cache_dir}"
    return True, ", ".join(sorted(found))


def _free_disk_gb(path: Path) -> float | None:
    try:
        import shutil

        path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(path)
        return usage.free / (1024**3)
    except Exception:
        return None


def _check_outbound_https() -> tuple[str | None, str | None, str | None]:
    """Probe two well-known endpoints to detect outbound-HTTPS firewalling.

    Returns ``(status_line, warning, failure)``. Failure is set only when both
    probes fail (likely a sandbox blocking outbound 443); a single failure is
    a warning because the remote could simply be down.
    """
    from .intake.deploy import probe as probe_deploy

    targets = [
        ("example.com (IANA reserved)", "https://example.com"),
        ("api.github.com (GitHub API)", "https://api.github.com"),
    ]
    statuses: list[tuple[str, bool, str]] = []
    for label, url in targets:
        result = probe_deploy(url, timeout=8)
        ok = result.reachable and (result.status_code or 0) < 500
        detail = (
            f"HTTP {result.status_code}"
            if result.status_code is not None
            else (result.error or "no response")
        )
        statuses.append((label, ok, detail))

    successes = sum(1 for _, ok, _ in statuses if ok)
    lines = [
        f"  {'OK' if ok else 'FAIL'} {label}: {detail}"
        for label, ok, detail in statuses
    ]
    table_text = "Outbound HTTPS smoke:\n" + "\n".join(lines)

    if successes == len(statuses):
        return f"[green]{table_text}[/green]", None, None
    if successes == 0:
        return (
            f"[red]{table_text}[/red]",
            None,
            "All outbound-HTTPS probes failed. Likely a Railway/sandbox network "
            "block on 443 egress. Without outbound HTTPS the pipeline cannot "
            "fetch repos, probe live URLs, or call any LLM provider.",
        )
    return (
        table_text,
        "One outbound-HTTPS probe failed. The remote may be temporarily down; "
        "re-run doctor in a few minutes. If both probes start failing, treat "
        "as outbound firewall.",
        None,
    )


def _check_submission_live_urls(max_probes: int = 25) -> Table | None:
    """Probe every non-anchor submission's `live_url` and render a small table.

    Warnings only — a candidate's URL being down at doctor time isn't a system
    failure, but the table makes it obvious which URLs need a heads-up before
    a batch run.
    """
    from .intake.deploy import probe as probe_deploy

    store = get_store()
    rows: list[tuple[str, str, str, bool, str]] = []
    probed = 0
    for sid in store.list_submission_ids(include_anchors=False):
        sub = store.get_submission(sid)
        if not sub or not sub.get("live_url"):
            continue
        if probed >= max_probes:
            rows.append(
                (
                    sid,
                    sub.get("candidate_name") or "?",
                    sub["live_url"],
                    True,
                    f"skipped (cap={max_probes})",
                )
            )
            continue
        result = probe_deploy(sub["live_url"], timeout=8)
        ok = result.reachable and (result.status_code or 0) < 400
        detail = (
            f"HTTP {result.status_code}"
            if result.status_code is not None
            else (result.error or "no response")
        )
        rows.append((sid, sub.get("candidate_name") or "?", sub["live_url"], ok, detail))
        probed += 1
    if not rows:
        return None

    table = Table(title=f"Submission live URLs ({probed} probed)")
    table.add_column("Submission")
    table.add_column("Candidate")
    table.add_column("URL")
    table.add_column("Reachable")
    table.add_column("Detail")
    for sid, name, url, ok, detail in rows:
        table.add_row(
            sid,
            name,
            url,
            "[green]yes[/green]" if ok else "[yellow]no[/yellow]",
            detail,
        )
    return table


def _snapshot_cache_warning(data_dir: Path) -> str | None:
    """Sum the snapshot.tar.gz footprint across submissions; warn if > 1 GB."""
    submissions_root = data_dir / "submissions"
    if not submissions_root.exists():
        return None
    total_bytes = 0
    for tar_path in submissions_root.glob("*/repo_cache/snapshot.tar.gz"):
        try:
            total_bytes += tar_path.stat().st_size
        except OSError:
            continue
    if total_bytes == 0:
        return None
    total_mb = total_bytes / (1024**2)
    if total_mb < 1024:
        return None
    return (
        f"Snapshot cache footprint is {total_mb / 1024:.2f} GB. "
        "Run `autojudge gc` to evict snapshots older than "
        "AUTOJUDGE_SNAPSHOT_TTL_DAYS (default 14)."
    )


def _anchor_drift_summary() -> str | None:
    """Compare on-file anchor totals against expected. Read-only check.

    Does NOT re-run the pipeline (that's `autojudge run-anchors`). Reports
    drift only for anchors that already have a total persisted; missing
    anchors are noted but not flagged as errors here.
    """
    store = get_store()
    rows: list[str] = []
    drifted = 0
    for anchor in ANCHORS:
        total = store.get_total(anchor.id)
        if total is None:
            rows.append(f"  {anchor.id}: no total on file — run `autojudge run-anchors`")
            continue
        actual = float(total["total_score"])
        drift = actual - anchor.expected_total
        marker = "[green]OK[/green]" if abs(drift) <= MAX_DRIFT else "[red]DRIFT[/red]"
        if abs(drift) > MAX_DRIFT:
            drifted += 1
        rows.append(
            f"  {marker} {anchor.id}: expected~{anchor.expected_total:.1f}  "
            f"actual={actual:.1f}  drift={drift:+.1f}"
        )
    if not rows:
        return None
    header = "Anchor drift (on-file vs expected, no re-run):"
    if drifted:
        header += f"  [yellow]{drifted} over MAX_DRIFT={MAX_DRIFT}[/yellow]"
    return header + "\n" + "\n".join(rows)


if __name__ == "__main__":
    app()
