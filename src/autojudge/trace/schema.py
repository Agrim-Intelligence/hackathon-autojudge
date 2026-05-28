"""DDL for the trace store, in two dialects.

v1.x default is SQLite. Multi-service Railway deployments use Postgres so
intake and the judges' dashboard share the same submissions, scores, and
deck blobs. Both backends are interchangeable behind ``TraceStoreProtocol``.

Tables:
- submissions          submission metadata + free-form context body
- submission_blobs     binary attachments (deck PDFs) keyed by submission_id
- verifier_runs        one row per agent execution with cost + error trace
- scores               per-dimension rubric outputs (nullable for insufficient)
- totals               final shortlist-generator output incl. judge overrides

v1.0 introduced ``evidence_kind``, ``cost_is_precise``, and nullable
``raw_score`` / ``weighted_score``. v1.2 added ``submission_blobs`` and
inlined ``submission_md_raw`` on submissions so the orchestrator no longer
needs a shared filesystem to find a submission's body or deck.
"""
from __future__ import annotations

# -----------------------------------------------------------------------------
# SQLite dialect
# -----------------------------------------------------------------------------

SCHEMA_SQLITE = """
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
    extras_json TEXT,
    submission_md_raw TEXT
);

CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);

CREATE TABLE IF NOT EXISTS submission_blobs (
    submission_id TEXT NOT NULL,
    name TEXT NOT NULL,
    content_type TEXT,
    data BLOB NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (submission_id, name),
    FOREIGN KEY (submission_id) REFERENCES submissions(id)
);

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

# Idempotent column additions so older SQLite files keep working.
MIGRATIONS_SQLITE: list[str] = [
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
    "ALTER TABLE submissions ADD COLUMN submission_md_raw TEXT",
]

# Rebuild block: SQLite can't drop NOT NULL via ALTER COLUMN, so when we detect
# the legacy v0.1 schema we rename → recreate → copy → drop. Runs at most once.
SCORES_REBUILD_SQLITE = """
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


# -----------------------------------------------------------------------------
# Postgres dialect
#
# Differences from SQLite:
# - SERIAL replaces AUTOINCREMENT.
# - BYTEA replaces BLOB.
# - BOOLEAN replaces INTEGER 0/1 columns where it improves readability —
#   we keep INTEGER on legacy bool-like columns (cost_is_precise, normalized)
#   so the application code can stay dialect-agnostic (Python truthiness
#   handles both).
# - JSON columns stay TEXT to preserve identical Python types across backends.
# - All ``CREATE TABLE`` statements use ``IF NOT EXISTS`` so the schema is
#   self-installing — the dashboard service can be the first to connect and
#   the table will be created in place.
# -----------------------------------------------------------------------------

SCHEMA_POSTGRES = """
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
    extras_json TEXT,
    submission_md_raw TEXT
);

CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);

CREATE TABLE IF NOT EXISTS submission_blobs (
    submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    content_type TEXT,
    data BYTEA NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (submission_id, name)
);

CREATE TABLE IF NOT EXISTS verifier_runs (
    id BIGSERIAL PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    agent TEXT NOT NULL,
    model TEXT,
    provider TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    input_summary TEXT,
    output_json TEXT NOT NULL,
    cost_usd REAL DEFAULT 0,
    cost_is_precise INTEGER DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_submission ON verifier_runs(submission_id);
CREATE INDEX IF NOT EXISTS idx_runs_agent ON verifier_runs(agent);

CREATE TABLE IF NOT EXISTS scores (
    id BIGSERIAL PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    dimension TEXT NOT NULL,
    raw_score DOUBLE PRECISION,
    weighted_score DOUBLE PRECISION,
    evidence_kind TEXT DEFAULT 'inferred',
    rationale TEXT,
    evidence_json TEXT,
    cap_applied INTEGER DEFAULT 0,
    cap_reason TEXT,
    anchor_delta DOUBLE PRECISION,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scores_submission ON scores(submission_id);
CREATE INDEX IF NOT EXISTS idx_scores_dimension ON scores(dimension);

CREATE TABLE IF NOT EXISTS totals (
    submission_id TEXT PRIMARY KEY REFERENCES submissions(id) ON DELETE CASCADE,
    total_score DOUBLE PRECISION NOT NULL,
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
    finalized_at TEXT NOT NULL
);
"""

# Postgres handles forward-compat by inspecting ``information_schema`` rather
# than catching errors; PostgresTraceStore does the column-add probes in code.


# -----------------------------------------------------------------------------
# Compat aliases — older callers import SCHEMA / MIGRATIONS / SCORES_REBUILD.
# Keep them pointing at the SQLite definitions so existing imports keep working.
# -----------------------------------------------------------------------------
SCHEMA = SCHEMA_SQLITE
MIGRATIONS = MIGRATIONS_SQLITE
SCORES_REBUILD = SCORES_REBUILD_SQLITE
