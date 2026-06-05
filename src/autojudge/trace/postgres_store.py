"""Postgres backend for the trace store.

Implements the same ``TraceStoreProtocol`` surface as the SQLite default so
the rest of the codebase (CLI, orchestrator, agents, dashboard) is backend-
agnostic. Activated when ``DATABASE_URL`` is set in the environment — see
``trace/store.py::get_store``.

Design notes:
- Uses ``psycopg`` (v3) with a tiny ``ConnectionPool`` so the dashboard's
  background evaluation threads and the intake form's request handlers
  don't serialise on a single socket.
- The schema is created on first connect via ``schema.SCHEMA_POSTGRES``;
  every table uses ``IF NOT EXISTS`` so either service is safe to be the
  first to boot against a fresh Postgres.
- A small ``information_schema`` probe runs once per startup to add any
  forward-compat columns (mirrors the SQLite migrations list).
- Reads return ``dict[str, Any]`` rows. Bool-like INTEGER columns
  (``cost_is_precise``, ``normalized``, ``cap_applied``) stay int for
  byte-for-byte parity with the SQLite backend; the dashboard treats them
  with Python truthiness in either case.
- Schema changes ship in :mod:`autojudge.trace.schema` exactly once for
  both dialects; never special-case Postgres-only DDL in agent code.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from ..config import get_settings
from ..models import (
    DimensionScore,
    RubricScore,
    Submission,
    SubmissionStatus,
    VerifierRun,
)
from .schema import SCHEMA_POSTGRES
from .store import (
    _artifacts_extras,
    _LEADERBOARD_SELECT,
    _leaderboard_filters,
    _leaderboard_order,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Columns we may need to add to a pre-existing Postgres database, mirrored
# from MIGRATIONS_SQLITE. Each tuple is ``(table, column, ddl_fragment)``;
# the fragment is ``DDL_TYPE [DEFAULT ...]`` (no column name).
_POSTGRES_COLUMN_ADDS: list[tuple[str, str, str]] = [
    ("verifier_runs", "cost_is_precise", "INTEGER DEFAULT 0"),
    ("scores", "evidence_kind", "TEXT DEFAULT 'inferred'"),
    ("totals", "evaluable_weight", "INTEGER DEFAULT 100"),
    ("totals", "normalized", "INTEGER DEFAULT 0"),
    ("totals", "verdict", "TEXT DEFAULT 'borderline'"),
    ("totals", "judge_review_items_json", "TEXT"),
    ("totals", "verdict_override", "TEXT"),
    ("totals", "judge_notes", "TEXT"),
    ("totals", "overridden_by", "TEXT"),
    ("totals", "overridden_at", "TEXT"),
    ("submissions", "submission_md_raw", "TEXT"),
    ("submissions", "app_type", "TEXT DEFAULT 'other'"),
    ("totals", "shortlist_state", "TEXT DEFAULT 'none'"),
    ("totals", "finalized_by", "TEXT"),
    ("totals", "finalized_at_shortlist", "TEXT"),
]


class PostgresTraceStore:
    """Concrete Postgres implementation of :class:`TraceStoreProtocol`."""

    def __init__(self, database_url: str, *, pool_min: int = 1, pool_max: int = 5) -> None:
        # psycopg ships ``ConnectionPool`` in the ``psycopg_pool`` package.
        # Both are available via the ``psycopg[binary]`` extra pinned in
        # pyproject.toml.
        from psycopg_pool import ConnectionPool

        # Railway hands out URLs as ``postgres://``; psycopg expects
        # ``postgresql://``. Normalise so both forms work.
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://") :]

        self._database_url = database_url
        # ``open=True`` ensures the pool's worker thread starts immediately
        # (suppresses the psycopg 3.2 deprecation warning).
        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=pool_min,
            max_size=pool_max,
            kwargs={"autocommit": False},
            open=True,
        )
        self._bootstrap_schema()
        self.reset_stale_running()

    def backend_name(self) -> str:
        return "postgres"

    # ---- connection helpers -------------------------------------------------

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        """Borrow a connection from the pool, dict-rowed, with commit/rollback."""
        from psycopg.rows import dict_row

        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _bootstrap_schema(self) -> None:
        """Create base tables (idempotent) then add any missing columns."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_POSTGRES)
            # Forward-compat: probe ``information_schema`` and add missing
            # columns. Pass over the same list every boot — cheap, runs once.
            for table, column, ddl in _POSTGRES_COLUMN_ADDS:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = %s AND column_name = %s
                        """,
                        (table, column),
                    )
                    exists = cur.fetchone() is not None
                if not exists:
                    logger.info("postgres: adding column %s.%s", table, column)
                    with conn.cursor() as cur:
                        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # ---- write API ----------------------------------------------------------

    def upsert_submission(self, sub: Submission) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO submissions (
                        id, candidate_name, candidate_email, team,
                        repo_url, live_url, video_url, deck_path,
                        archetype, app_type, status, is_anchor, created_at, extras_json,
                        submission_md_raw
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        candidate_name = EXCLUDED.candidate_name,
                        candidate_email = EXCLUDED.candidate_email,
                        team = EXCLUDED.team,
                        repo_url = EXCLUDED.repo_url,
                        live_url = EXCLUDED.live_url,
                        video_url = EXCLUDED.video_url,
                        deck_path = EXCLUDED.deck_path,
                        archetype = EXCLUDED.archetype,
                        app_type = EXCLUDED.app_type,
                        status = EXCLUDED.status,
                        is_anchor = EXCLUDED.is_anchor,
                        extras_json = EXCLUDED.extras_json,
                        submission_md_raw = EXCLUDED.submission_md_raw
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
                        sub.app_type.value,
                        sub.status.value,
                        1 if sub.is_anchor else 0,
                        sub.created_at.isoformat(),
                        json.dumps(_artifacts_extras(sub)),
                        sub.submission_md_raw,
                    ),
                )

    def set_status(self, submission_id: str, status: SubmissionStatus) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE submissions SET status = %s WHERE id = %s",
                    (status.value, submission_id),
                )

    def set_archetype(self, submission_id: str, archetype: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE submissions SET archetype = %s WHERE id = %s",
                    (archetype, submission_id),
                )

    def set_app_type(self, submission_id: str, app_type: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE submissions SET app_type = %s WHERE id = %s",
                    (app_type, submission_id),
                )

    def set_finalist(
        self, submission_id: str, *, state: str, finalized_by: str | None = None
    ) -> None:
        """Record a judge's shortlist decision. ``state`` ∈ {none,finalist,winner}.

        ``none`` clears the finalist provenance; any other state stamps it.
        Sticky across re-scores because ``record_total`` excludes these columns
        from its conflict update.
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                if state == "none":
                    cur.execute(
                        """
                        UPDATE totals SET
                            shortlist_state = %s,
                            finalized_by = NULL,
                            finalized_at_shortlist = NULL
                        WHERE submission_id = %s
                        """,
                        (state, submission_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE totals SET
                            shortlist_state = %s,
                            finalized_by = %s,
                            finalized_at_shortlist = %s
                        WHERE submission_id = %s
                        """,
                        (state, finalized_by, _now_iso(), submission_id),
                    )

    def set_judge_override(
        self,
        submission_id: str,
        *,
        archetype: str | None = None,
        verdict: str | None = None,
        notes: str | None = None,
        overridden_by: str | None = None,
    ) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                if archetype is not None:
                    cur.execute(
                        "UPDATE submissions SET archetype = %s WHERE id = %s",
                        (archetype, submission_id),
                    )
                if (
                    verdict is not None
                    or notes is not None
                    or overridden_by is not None
                ):
                    stamp = _now_iso()
                    sets: list[str] = []
                    params: list[Any] = []
                    if verdict is not None:
                        sets.append("verdict_override = %s")
                        params.append(verdict or None)
                    if notes is not None:
                        sets.append("judge_notes = %s")
                        params.append(notes or None)
                    if overridden_by is not None:
                        sets.append("overridden_by = %s")
                        params.append(overridden_by or None)
                    sets.append("overridden_at = %s")
                    params.append(stamp)
                    params.append(submission_id)
                    cur.execute(
                        f"UPDATE totals SET {', '.join(sets)} WHERE submission_id = %s",
                        params,
                    )

    def clear_judge_override(self, submission_id: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE totals SET
                        verdict_override = NULL,
                        judge_notes = NULL,
                        overridden_by = NULL,
                        overridden_at = NULL
                    WHERE submission_id = %s
                    """,
                    (submission_id,),
                )

    def reset_stale_running(self) -> list[str]:
        """Bounded-requeue submissions stuck in RUNNING (process killed mid-run).

        Same contract as the SQLite implementation: under
        ``autojudge_max_restart_retries`` (counted from prior
        ``restart_during_run`` synthetic rows) a submission goes back to
        'pending' for checkpoint-resumed re-run; at/above the limit it is
        dead-lettered to 'failed'. A synthetic ``verifier_runs`` row is always
        emitted so the trace is preserved.
        """
        max_retries = get_settings().autojudge_max_restart_retries
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM submissions WHERE status = 'running'")
                rows = cur.fetchall()
            ids = [r["id"] for r in rows]
            if not ids:
                return []
            now = _now_iso()
            requeued = 0
            dead_lettered = 0
            for sid in ids:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) AS n FROM verifier_runs "
                        "WHERE submission_id = %s AND error = 'restart_during_run'",
                        (sid,),
                    )
                    prior = cur.fetchone()["n"]
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
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE submissions SET status = %s WHERE id = %s",
                        (new_status, sid),
                    )
                    cur.execute(
                        """
                        INSERT INTO verifier_runs (
                            submission_id, agent, model, provider,
                            started_at, finished_at, input_summary,
                            output_json, cost_usd, cost_is_precise, error
                        ) VALUES (%s, %s, NULL, NULL, %s, %s, %s, %s, 0, 0, %s)
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
            logger.warning(
                "postgres: stale RUNNING reset on boot: %d requeued -> pending, "
                "%d dead-lettered -> failed (max_retries=%d)",
                requeued,
                dead_lettered,
                max_retries,
            )
            return ids

    def purge_submission(self, submission_id: str) -> None:
        # ``ON DELETE CASCADE`` on FKs would also work, but explicit deletes
        # keep the behaviour identical to the SQLite path.
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM totals WHERE submission_id = %s", (submission_id,)
                )
                cur.execute(
                    "DELETE FROM scores WHERE submission_id = %s", (submission_id,)
                )
                cur.execute(
                    "DELETE FROM verifier_runs WHERE submission_id = %s", (submission_id,)
                )
                cur.execute(
                    "DELETE FROM submission_blobs WHERE submission_id = %s",
                    (submission_id,),
                )
                cur.execute(
                    "DELETE FROM submissions WHERE id = %s", (submission_id,)
                )

    def record_run(self, run: VerifierRun) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO verifier_runs (
                        submission_id, agent, model, provider,
                        started_at, finished_at, input_summary,
                        output_json, cost_usd, cost_is_precise, error
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
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
                row = cur.fetchone()
                return int(row["id"]) if row else 0

    def record_score(self, submission_id: str, score: DimensionScore) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO scores (
                        submission_id, dimension, raw_score, weighted_score,
                        evidence_kind, rationale, evidence_json,
                        cap_applied, cap_reason, anchor_delta, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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

    def record_total(self, rubric: RubricScore) -> None:
        # Replace-then-insert keeps the leaderboard semantically equivalent to
        # the SQLite ``DELETE + INSERT`` pattern, which the dashboard expects.
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM scores WHERE submission_id = %s",
                    (rubric.submission_id,),
                )
                for dim in rubric.dimensions:
                    cur.execute(
                        """
                        INSERT INTO scores (
                            submission_id, dimension, raw_score, weighted_score,
                            evidence_kind, rationale, evidence_json,
                            cap_applied, cap_reason, anchor_delta, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                cur.execute(
                    """
                    INSERT INTO totals (
                        submission_id, total_score, archetype, summary,
                        integrity_flags_json, anchor_deltas_json,
                        evaluable_weight, normalized, verdict,
                        judge_review_items_json,
                        shortlist_state, finalized_by, finalized_at_shortlist,
                        finalized_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'none', NULL, NULL, %s)
                    ON CONFLICT (submission_id) DO UPDATE SET
                        total_score = EXCLUDED.total_score,
                        archetype = EXCLUDED.archetype,
                        summary = EXCLUDED.summary,
                        integrity_flags_json = EXCLUDED.integrity_flags_json,
                        anchor_deltas_json = EXCLUDED.anchor_deltas_json,
                        evaluable_weight = EXCLUDED.evaluable_weight,
                        normalized = EXCLUDED.normalized,
                        verdict = EXCLUDED.verdict,
                        judge_review_items_json = EXCLUDED.judge_review_items_json,
                        finalized_at = EXCLUDED.finalized_at
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

    # ---- blob API -----------------------------------------------------------

    def put_blob(
        self,
        submission_id: str,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO submission_blobs (
                        submission_id, name, content_type, data, created_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (submission_id, name) DO UPDATE SET
                        content_type = EXCLUDED.content_type,
                        data = EXCLUDED.data,
                        created_at = EXCLUDED.created_at
                    """,
                    (submission_id, name, content_type, data, _now_iso()),
                )

    def get_blob(self, submission_id: str, name: str) -> bytes | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data FROM submission_blobs WHERE submission_id = %s AND name = %s",
                    (submission_id, name),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return bytes(row["data"])

    def has_blob(self, submission_id: str, name: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM submission_blobs WHERE submission_id = %s AND name = %s",
                    (submission_id, name),
                )
                return cur.fetchone() is not None

    # ---- read API -----------------------------------------------------------

    def leaderboard(self, include_anchors: bool = False, *,
                    app_types: list[str] | None = None,
                    verdict: str | None = None,
                    status: str | None = None,
                    has_live_url: bool | None = None,
                    finalist_only: bool = False,
                    search: str | None = None,
                    sort: str = "score") -> list[dict[str, Any]]:
        clauses, params = _leaderboard_filters(
            "%s", include_anchors, app_types, verdict, status,
            has_live_url, finalist_only, search,
        )
        sql = _LEADERBOARD_SELECT
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += _leaderboard_order(sort)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            out: list[dict[str, Any]] = []
            for idx, r in enumerate(rows, start=1):
                d = dict(r)
                d["verdict_effective"] = d.get("verdict_override") or d.get("verdict")
                d["shortlist_rank"] = idx if not d.get("is_anchor") else None
                out.append(d)
            ids = [d["id"] for d in out]
            dims: dict[str, dict[str, float | None]] = {}
            if ids:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT submission_id, dimension, raw_score FROM scores "
                        "WHERE submission_id = ANY(%s)",
                        (ids,),
                    )
                    for sr in cur.fetchall():
                        dims.setdefault(sr["submission_id"], {})[sr["dimension"]] = sr["raw_score"]
            for d in out:
                d["dimensions"] = dims.get(d["id"], {})
            return out

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM submissions WHERE id = %s", (submission_id,)
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_scores(self, submission_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM scores WHERE submission_id = %s ORDER BY dimension",
                    (submission_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_total(self, submission_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM totals WHERE submission_id = %s", (submission_id,)
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_runs(self, submission_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM verifier_runs WHERE submission_id = %s ORDER BY started_at",
                    (submission_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_submission_cost(self, submission_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        SUM(cost_usd) AS total_cost,
                        MIN(cost_is_precise) AS min_precise,
                        COUNT(*) AS run_count
                    FROM verifier_runs
                    WHERE submission_id = %s
                    """,
                    (submission_id,),
                )
                row = cur.fetchone()
            if row is None:
                return {"total_cost": 0.0, "all_precise": False, "run_count": 0}
            return {
                "total_cost": float(row["total_cost"] or 0.0),
                "all_precise": bool(row["min_precise"]) if row["min_precise"] is not None else False,
                "run_count": int(row["run_count"] or 0),
            }

    def list_submission_ids(self, include_anchors: bool = True) -> list[str]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                sql = "SELECT id FROM submissions"
                if not include_anchors:
                    sql += " WHERE is_anchor = 0"
                sql += " ORDER BY created_at"
                cur.execute(sql)
                return [r["id"] for r in cur.fetchall()]

    def list_pending_submission_ids(self) -> list[str]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM submissions WHERE status IN ('pending', 'failed') ORDER BY created_at"
                )
                return [r["id"] for r in cur.fetchall()]
