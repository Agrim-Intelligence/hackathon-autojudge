"""Trace store backends for submissions, verifier runs, scores, and blobs.

Two interchangeable implementations live behind ``TraceStoreProtocol``:

- ``TraceStore`` (SQLite): local dev default. Uses a file under
  ``AUTOJUDGE_DB_PATH``. Threadlocal connections keep the synchronous path
  simple. Suitable for single-process / single-machine runs.

- ``PostgresTraceStore`` (Postgres): Railway-deployment default once
  ``DATABASE_URL`` is set. Required for multi-service topologies (intake +
  dashboard talking to the same data) because Railway volumes are not
  shareable across services. Uses a small connection pool so concurrent
  evaluations don't serialise on one socket.

``get_store()`` picks the backend based on ``DATABASE_URL``. Callers never
import the backend class directly.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol, runtime_checkable

from ..config import get_settings
from ..models import (
    DimensionScore,
    RubricScore,
    Submission,
    SubmissionStatus,
    VerifierRun,
)
from .schema import MIGRATIONS_SQLITE, SCHEMA_SQLITE, SCORES_REBUILD_SQLITE

logger = logging.getLogger(__name__)
_local = threading.local()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@runtime_checkable
class TraceStoreProtocol(Protocol):
    """Narrow contract every trace-store backend must satisfy.

    Kept intentionally minimal: writes are idempotent, reads return plain
    dictionaries (no ORM rows), and no caller needs to know about the
    backing engine. Both SQLite and Postgres implementations conform.

    Backend-specific transactional access (``connect()`` on SQLite, the
    psycopg pool on Postgres) is intentionally NOT in the protocol — call
    sites that need raw SQL go through the typed helpers below.
    """

    def upsert_submission(self, sub: Submission) -> None: ...

    def set_status(self, submission_id: str, status: SubmissionStatus) -> None: ...

    def set_archetype(self, submission_id: str, archetype: str) -> None: ...

    def set_judge_override(
        self,
        submission_id: str,
        *,
        archetype: str | None = None,
        verdict: str | None = None,
        notes: str | None = None,
        overridden_by: str | None = None,
    ) -> None: ...

    def clear_judge_override(self, submission_id: str) -> None: ...

    def reset_stale_running(self) -> list[str]: ...

    def purge_submission(self, submission_id: str) -> None: ...

    def record_run(self, run: VerifierRun) -> int: ...

    def record_score(self, submission_id: str, score: DimensionScore) -> None: ...

    def record_total(self, rubric: RubricScore) -> None: ...

    def leaderboard(self, include_anchors: bool = False) -> list[dict[str, Any]]: ...

    def get_submission(self, submission_id: str) -> dict[str, Any] | None: ...

    def get_scores(self, submission_id: str) -> list[dict[str, Any]]: ...

    def get_total(self, submission_id: str) -> dict[str, Any] | None: ...

    def get_runs(self, submission_id: str) -> list[dict[str, Any]]: ...

    def get_submission_cost(self, submission_id: str) -> dict[str, Any]: ...

    def list_submission_ids(self, include_anchors: bool = True) -> list[str]: ...

    def list_pending_submission_ids(self) -> list[str]: ...

    def put_blob(
        self,
        submission_id: str,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None: ...

    def get_blob(self, submission_id: str, name: str) -> bytes | None: ...

    def has_blob(self, submission_id: str, name: str) -> bool: ...

    def backend_name(self) -> str: ...


class TraceStore:
    def __init__(self, db_path: Path | None = None) -> None:
        settings = get_settings()
        self.db_path = Path(db_path or settings.autojudge_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQLITE)
            for stmt in MIGRATIONS_SQLITE:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass
            self._rebuild_scores_if_legacy(conn)
            conn.commit()
        self.reset_stale_running()

    def backend_name(self) -> str:
        return "sqlite"

    def _rebuild_scores_if_legacy(self, conn: sqlite3.Connection) -> None:
        """Drop legacy NOT NULL constraints on scores.raw_score / weighted_score.

        SQLite cannot drop NOT NULL via ALTER COLUMN, so when the legacy schema
        is detected we copy rows into a v1.0-shaped table and swap it in. The
        check is cheap (one PRAGMA), the rebuild only runs on legacy DBs.
        """
        cols = conn.execute("PRAGMA table_info(scores)").fetchall()
        if not cols:
            return
        legacy = any(
            row["name"] in {"raw_score", "weighted_score"} and row["notnull"] == 1
            for row in cols
        )
        if not legacy:
            return
        logger.warning("Migrating legacy `scores` table to v1.0 nullable schema")
        conn.executescript(SCORES_REBUILD_SQLITE)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = getattr(_local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            _local.conn = conn
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise

    def upsert_submission(self, sub: Submission) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO submissions (
                    id, candidate_name, candidate_email, team,
                    repo_url, live_url, video_url, deck_path,
                    archetype, status, is_anchor, created_at, extras_json,
                    submission_md_raw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    candidate_name = excluded.candidate_name,
                    candidate_email = excluded.candidate_email,
                    team = excluded.team,
                    repo_url = excluded.repo_url,
                    live_url = excluded.live_url,
                    video_url = excluded.video_url,
                    deck_path = excluded.deck_path,
                    archetype = excluded.archetype,
                    status = excluded.status,
                    is_anchor = excluded.is_anchor,
                    extras_json = excluded.extras_json,
                    submission_md_raw = excluded.submission_md_raw
                """,
                (
                    sub.id,
                    sub.candidate.name,
                    sub.candidate.email,
                    sub.candidate.team,
                    sub.artifacts.repo_url,
                    sub.artifacts.live_url,
                    sub.artifacts.video_url,
                    sub.artifacts.deck_path,
                    sub.archetype.value,
                    sub.status.value,
                    1 if sub.is_anchor else 0,
                    sub.created_at.isoformat(),
                    json.dumps(
                        {
                            "submission_md_path": sub.artifacts.submission_md_path,
                            "test_credentials": sub.artifacts.test_credentials,
                        }
                    ),
                    sub.submission_md_raw,
                ),
            )
            conn.commit()

    def set_status(self, submission_id: str, status: SubmissionStatus) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE submissions SET status = ? WHERE id = ?",
                (status.value, submission_id),
            )
            conn.commit()

    def set_archetype(self, submission_id: str, archetype: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE submissions SET archetype = ? WHERE id = ?",
                (archetype, submission_id),
            )
            conn.commit()

    def set_judge_override(
        self,
        submission_id: str,
        *,
        archetype: str | None = None,
        verdict: str | None = None,
        notes: str | None = None,
        overridden_by: str | None = None,
    ) -> None:
        """Record a human override.

        Archetype overrides go to `submissions.archetype` (a re-score reads
        from there). Verdict + notes + auditor identity live on `totals` and
        are sticky across re-runs because `record_total()` does not touch
        those columns on conflict.
        """
        with self.connect() as conn:
            if archetype is not None:
                conn.execute(
                    "UPDATE submissions SET archetype = ? WHERE id = ?",
                    (archetype, submission_id),
                )
            if verdict is not None or notes is not None or overridden_by is not None:
                stamp = _now_iso()
                sets: list[str] = []
                params: list[Any] = []
                if verdict is not None:
                    sets.append("verdict_override = ?")
                    params.append(verdict or None)
                if notes is not None:
                    sets.append("judge_notes = ?")
                    params.append(notes or None)
                if overridden_by is not None:
                    sets.append("overridden_by = ?")
                    params.append(overridden_by or None)
                sets.append("overridden_at = ?")
                params.append(stamp)
                params.append(submission_id)
                conn.execute(
                    f"UPDATE totals SET {', '.join(sets)} WHERE submission_id = ?",
                    params,
                )
            conn.commit()

    def clear_judge_override(self, submission_id: str) -> None:
        """Wipe verdict / notes / auditor identity. Archetype is preserved."""
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE totals SET
                    verdict_override = NULL,
                    judge_notes = NULL,
                    overridden_by = NULL,
                    overridden_at = NULL
                WHERE submission_id = ?
                """,
                (submission_id,),
            )
            conn.commit()

    def reset_stale_running(self) -> list[str]:
        """Requeue submissions stuck in RUNNING (e.g. process killed mid-batch).

        Each affected submission is bounded-requeued: under
        ``autojudge_max_restart_retries`` it goes back to 'pending' (the batch
        picker re-runs it, and checkpoint resume skips already-completed
        agents); at/above the limit it is dead-lettered to 'failed'.

        The retry counter is derived from the trace itself — the number of
        prior ``restart_during_run`` synthetic rows for the submission — so no
        schema column is needed. A synthetic ``verifier_runs`` row is always
        emitted so the trace shows what happened. Returns the list of affected
        submission ids. Called once on store construction.
        """
        max_retries = get_settings().autojudge_max_restart_retries
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM submissions WHERE status = 'running'"
            ).fetchall()
            ids = [r["id"] for r in rows]
            if not ids:
                return []
            now = _now_iso()
            requeued = 0
            dead_lettered = 0
            for sid in ids:
                prior = conn.execute(
                    "SELECT COUNT(*) AS n FROM verifier_runs "
                    "WHERE submission_id = ? AND error = 'restart_during_run'",
                    (sid,),
                ).fetchone()["n"]
                attempt = prior + 1
                if prior < max_retries:
                    new_status = "pending"
                    output = {
                        "reason": "restart_during_run",
                        "action": "restart_requeued",
                        "attempt": attempt,
                    }
                    requeued += 1
                else:
                    new_status = "failed"
                    output = {
                        "reason": "restart_during_run",
                        "action": "dead_letter",
                        "attempt": attempt,
                    }
                    dead_lettered += 1
                conn.execute(
                    "UPDATE submissions SET status = ? WHERE id = ?",
                    (new_status, sid),
                )
                conn.execute(
                    """
                    INSERT INTO verifier_runs (
                        submission_id, agent, model, provider,
                        started_at, finished_at, input_summary,
                        output_json, cost_usd, cost_is_precise, error
                    ) VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, 0, 0, ?)
                    """,
                    (
                        sid,
                        "orchestrator",
                        now,
                        now,
                        "stale_running_reset",
                        json.dumps(output),
                        "restart_during_run",
                    ),
                )
            conn.commit()
            logger.warning(
                "Stale RUNNING reset on store boot: %d requeued -> pending, "
                "%d dead-lettered -> failed (max_retries=%d)",
                requeued,
                dead_lettered,
                max_retries,
            )
            return ids

    def purge_submission(self, submission_id: str) -> None:
        """Delete every DB row for a submission. Filesystem cleanup is callers' job."""
        with self.connect() as conn:
            conn.execute("DELETE FROM totals WHERE submission_id = ?", (submission_id,))
            conn.execute("DELETE FROM scores WHERE submission_id = ?", (submission_id,))
            conn.execute("DELETE FROM verifier_runs WHERE submission_id = ?", (submission_id,))
            conn.execute("DELETE FROM submission_blobs WHERE submission_id = ?", (submission_id,))
            conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
            conn.commit()

    def put_blob(
        self,
        submission_id: str,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None:
        """Upsert a binary attachment for a submission (e.g. deck PDF).

        Replaces any prior blob with the same ``(submission_id, name)``. The
        intake form is the canonical writer; the orchestrator materialises
        blobs back to ``/tmp`` per-evaluation.
        """
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO submission_blobs (
                    submission_id, name, content_type, data, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(submission_id, name) DO UPDATE SET
                    content_type = excluded.content_type,
                    data = excluded.data,
                    created_at = excluded.created_at
                """,
                (submission_id, name, content_type, data, _now_iso()),
            )
            conn.commit()

    def get_blob(self, submission_id: str, name: str) -> bytes | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT data FROM submission_blobs WHERE submission_id = ? AND name = ?",
                (submission_id, name),
            ).fetchone()
            if row is None:
                return None
            return bytes(row["data"])

    def has_blob(self, submission_id: str, name: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM submission_blobs WHERE submission_id = ? AND name = ?",
                (submission_id, name),
            ).fetchone()
            return row is not None

    def record_run(self, run: VerifierRun) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO verifier_runs (
                    submission_id, agent, model, provider,
                    started_at, finished_at, input_summary,
                    output_json, cost_usd, cost_is_precise, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.submission_id,
                    run.agent,
                    run.model,
                    run.provider,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat(),
                    run.input_summary,
                    json.dumps(run.output, default=str),
                    run.cost_usd,
                    1 if run.cost_is_precise else 0,
                    run.error,
                ),
            )
            conn.commit()
            return cur.lastrowid or 0

    def record_score(self, submission_id: str, score: DimensionScore) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO scores (
                    submission_id, dimension, raw_score, weighted_score,
                    evidence_kind, rationale, evidence_json,
                    cap_applied, cap_reason, anchor_delta, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    score.dimension.value,
                    score.raw_score,
                    score.weighted_score,
                    score.evidence_kind,
                    score.rationale,
                    json.dumps(score.evidence),
                    1 if score.cap_applied else 0,
                    score.cap_reason,
                    None,
                    _now_iso(),
                ),
            )
            conn.commit()

    def record_total(self, rubric: RubricScore) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM scores WHERE submission_id = ?", (rubric.submission_id,))
            for dim in rubric.dimensions:
                conn.execute(
                    """
                    INSERT INTO scores (
                        submission_id, dimension, raw_score, weighted_score,
                        evidence_kind, rationale, evidence_json,
                        cap_applied, cap_reason, anchor_delta, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rubric.submission_id,
                        dim.dimension.value,
                        dim.raw_score,
                        dim.weighted_score,
                        dim.evidence_kind,
                        dim.rationale,
                        json.dumps(dim.evidence),
                        1 if dim.cap_applied else 0,
                        dim.cap_reason,
                        rubric.anchor_deltas.get(dim.dimension.value),
                        _now_iso(),
                    ),
                )
            judge_items_json = json.dumps(
                [item.model_dump(mode="json") for item in rubric.judge_review_items]
            )
            conn.execute(
                """
                INSERT INTO totals (
                    submission_id, total_score, archetype, summary,
                    integrity_flags_json, anchor_deltas_json,
                    evaluable_weight, normalized, verdict,
                    judge_review_items_json, finalized_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(submission_id) DO UPDATE SET
                    total_score = excluded.total_score,
                    archetype = excluded.archetype,
                    summary = excluded.summary,
                    integrity_flags_json = excluded.integrity_flags_json,
                    anchor_deltas_json = excluded.anchor_deltas_json,
                    evaluable_weight = excluded.evaluable_weight,
                    normalized = excluded.normalized,
                    verdict = excluded.verdict,
                    judge_review_items_json = excluded.judge_review_items_json,
                    finalized_at = excluded.finalized_at
                """,
                (
                    rubric.submission_id,
                    rubric.total_score,
                    rubric.archetype.value,
                    rubric.summary,
                    json.dumps(rubric.integrity_flags),
                    json.dumps(rubric.anchor_deltas),
                    rubric.evaluable_weight,
                    1 if rubric.normalized else 0,
                    rubric.verdict,
                    judge_items_json,
                    _now_iso(),
                ),
            )
            conn.commit()

    # --- read helpers used by the dashboard ---

    def leaderboard(self, include_anchors: bool = False) -> list[dict[str, Any]]:
        with self.connect() as conn:
            sql = """
                SELECT s.id, s.candidate_name, s.team, s.archetype, s.status,
                       s.repo_url, s.live_url, s.is_anchor,
                       t.total_score, t.summary, t.integrity_flags_json,
                       t.evaluable_weight, t.normalized, t.verdict,
                       t.judge_review_items_json,
                       t.verdict_override, t.judge_notes,
                       t.overridden_by, t.overridden_at
                FROM submissions s
                LEFT JOIN totals t ON s.id = t.submission_id
            """
            if not include_anchors:
                sql += " WHERE s.is_anchor = 0"
            sql += " ORDER BY t.total_score DESC NULLS LAST"
            rows = conn.execute(sql).fetchall()
            out: list[dict[str, Any]] = []
            for idx, r in enumerate(rows, start=1):
                d = dict(r)
                # verdict_effective lets the dashboard and CLI display the
                # human's decision (when overridden) while still preserving
                # the auto-judge recommendation for audit.
                d["verdict_effective"] = d.get("verdict_override") or d.get("verdict")
                # Shortlist rank is presentation-only; computed on read so
                # operators can change verdict thresholds without rewriting
                # rows. Anchors get no rank.
                d["shortlist_rank"] = idx if not d.get("is_anchor") else None
                out.append(d)
            return out

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM submissions WHERE id = ?", (submission_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_scores(self, submission_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scores WHERE submission_id = ? ORDER BY dimension",
                (submission_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_total(self, submission_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM totals WHERE submission_id = ?", (submission_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_runs(self, submission_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM verifier_runs WHERE submission_id = ? ORDER BY started_at",
                (submission_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_submission_cost(self, submission_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    SUM(cost_usd) AS total_cost,
                    MIN(cost_is_precise) AS min_precise,
                    COUNT(*) AS run_count
                FROM verifier_runs
                WHERE submission_id = ?
                """,
                (submission_id,),
            ).fetchone()
            if row is None:
                return {"total_cost": 0.0, "all_precise": False, "run_count": 0}
            return {
                "total_cost": float(row["total_cost"] or 0.0),
                "all_precise": bool(row["min_precise"]) if row["min_precise"] is not None else False,
                "run_count": int(row["run_count"] or 0),
            }

    def list_submission_ids(self, include_anchors: bool = True) -> list[str]:
        with self.connect() as conn:
            sql = "SELECT id FROM submissions"
            if not include_anchors:
                sql += " WHERE is_anchor = 0"
            sql += " ORDER BY created_at"
            return [r["id"] for r in conn.execute(sql).fetchall()]

    def list_pending_submission_ids(self) -> list[str]:
        """Submissions still pending or previously failed, oldest first."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM submissions WHERE status IN ('pending', 'failed') ORDER BY created_at"
            ).fetchall()
            return [r["id"] for r in rows]


def completed_agent_outputs(
    store: TraceStoreProtocol, submission_id: str
) -> dict[str, dict[str, Any]]:
    """Map ``{agent: output_dict}`` of prior *successful* agent runs.

    Used by the orchestrator to resume a pipeline from the first agent that
    has no successful row yet, instead of re-running everything from guard.
    An agent counts as done only when it has at least one row with no error
    and a parseable ``output_json``; later successful rows win (re-runs append
    rather than overwrite). Synthetic ``orchestrator`` rows are ignored — they
    record failures/restarts, not resumable agent state.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in store.get_runs(submission_id):
        agent = row.get("agent")
        if not agent or agent == "orchestrator":
            continue
        if row.get("error"):
            continue
        raw = row.get("output_json")
        if not raw:
            continue
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            out[agent] = parsed
    return out


_store: TraceStoreProtocol | None = None


def get_store() -> TraceStoreProtocol:
    """Return the active trace store backend.

    Picks Postgres when ``DATABASE_URL`` is set in the environment, else
    falls back to SQLite at ``AUTOJUDGE_DB_PATH``. The choice is made on
    first call and memoised for the lifetime of the process.
    """
    global _store
    if _store is None:
        settings = get_settings()
        if settings.database_url:
            # Local import keeps psycopg out of the SQLite-only code paths.
            from .postgres_store import PostgresTraceStore

            logger.info("Trace store backend: postgres")
            _store = PostgresTraceStore(settings.database_url)
        else:
            logger.info("Trace store backend: sqlite at %s", settings.autojudge_db_path)
            _store = TraceStore()
    return _store


def set_store_for_tests(store: TraceStoreProtocol | None) -> None:
    """Override the active store. Intended for tests and the Phase-2 backend swap."""
    global _store
    _store = store
