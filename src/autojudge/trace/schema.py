"""SQLite schema for the trace store.

Four tables, all with JSON blob extras so we don't need migrations as new
agents arrive. v1.0 adds `evidence_kind` to scores, `cost_is_precise` to
verifier_runs, and allows `raw_score` / `weighted_score` to be NULL when a
dimension was marked as insufficient_evidence by the tolerant scorer.
"""
from __future__ import annotations

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY,
    candidate_name TEXT NOT NULL,
    candidate_email TEXT,
    team TEXT,
    repo_url TEXT,
    live_url TEXT,
    video_url TEXT,
    deck_path TEXT,
    archetype TEXT DEFAULT 'unknown',
    status TEXT DEFAULT 'pending',
    is_anchor INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    extras_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);

CREATE TABLE IF NOT EXISTS verifier_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    model TEXT,
    provider TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    input_summary TEXT,
    output_json TEXT NOT NULL,
    cost_usd REAL DEFAULT 0,
    cost_is_precise INTEGER DEFAULT 0,
    error TEXT,
    FOREIGN KEY (submission_id) REFERENCES submissions(id)
);

CREATE INDEX IF NOT EXISTS idx_runs_submission ON verifier_runs(submission_id);
CREATE INDEX IF NOT EXISTS idx_runs_agent ON verifier_runs(agent);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL,
    dimension TEXT NOT NULL,
    raw_score REAL,
    weighted_score REAL,
    evidence_kind TEXT DEFAULT 'inferred',
    rationale TEXT,
    evidence_json TEXT,
    cap_applied INTEGER DEFAULT 0,
    cap_reason TEXT,
    anchor_delta REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES submissions(id)
);

CREATE INDEX IF NOT EXISTS idx_scores_submission ON scores(submission_id);
CREATE INDEX IF NOT EXISTS idx_scores_dimension ON scores(dimension);

CREATE TABLE IF NOT EXISTS totals (
    submission_id TEXT PRIMARY KEY,
    total_score REAL NOT NULL,
    archetype TEXT,
    summary TEXT,
    integrity_flags_json TEXT,
    anchor_deltas_json TEXT,
    evaluable_weight INTEGER DEFAULT 100,
    normalized INTEGER DEFAULT 0,
    verdict TEXT DEFAULT 'borderline',
    judge_review_items_json TEXT,
    verdict_override TEXT,
    judge_notes TEXT,
    overridden_by TEXT,
    overridden_at TEXT,
    finalized_at TEXT NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES submissions(id)
);
"""

# Idempotent column additions for databases created on the v0.1 schema.
# Each statement is wrapped in a try at runtime (see TraceStore.__init__).
MIGRATIONS: list[str] = [
    "ALTER TABLE verifier_runs ADD COLUMN cost_is_precise INTEGER DEFAULT 0",
    "ALTER TABLE scores ADD COLUMN evidence_kind TEXT DEFAULT 'inferred'",
    "ALTER TABLE totals ADD COLUMN evaluable_weight INTEGER DEFAULT 100",
    "ALTER TABLE totals ADD COLUMN normalized INTEGER DEFAULT 0",
    "ALTER TABLE totals ADD COLUMN verdict TEXT DEFAULT 'borderline'",
    "ALTER TABLE totals ADD COLUMN judge_review_items_json TEXT",
    "ALTER TABLE totals ADD COLUMN verdict_override TEXT",
    "ALTER TABLE totals ADD COLUMN judge_notes TEXT",
    "ALTER TABLE totals ADD COLUMN overridden_by TEXT",
    "ALTER TABLE totals ADD COLUMN overridden_at TEXT",
]

# Rebuild blocks for tables whose column constraints changed in v1.0.
# SQLite cannot drop a NOT NULL constraint via ALTER COLUMN, so when we detect
# the legacy schema we rename the old table, recreate it with the v1.0 shape,
# copy the rows over, and drop the legacy table. Runs at most once per DB.
SCORES_REBUILD = """
CREATE TABLE scores_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL,
    dimension TEXT NOT NULL,
    raw_score REAL,
    weighted_score REAL,
    evidence_kind TEXT DEFAULT 'inferred',
    rationale TEXT,
    evidence_json TEXT,
    cap_applied INTEGER DEFAULT 0,
    cap_reason TEXT,
    anchor_delta REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES submissions(id)
);
INSERT INTO scores_v1 (
    id, submission_id, dimension, raw_score, weighted_score, evidence_kind,
    rationale, evidence_json, cap_applied, cap_reason, anchor_delta, created_at
)
SELECT
    id, submission_id, dimension, raw_score, weighted_score,
    COALESCE(evidence_kind, 'inferred'),
    rationale, evidence_json, cap_applied, cap_reason, anchor_delta, created_at
FROM scores;
DROP TABLE scores;
ALTER TABLE scores_v1 RENAME TO scores;
CREATE INDEX IF NOT EXISTS idx_scores_submission ON scores(submission_id);
CREATE INDEX IF NOT EXISTS idx_scores_dimension ON scores(dimension);
"""
