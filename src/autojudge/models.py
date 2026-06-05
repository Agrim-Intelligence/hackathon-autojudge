"""Pydantic models for submissions, verifier runs, inferred fields, and scores.

These types are the contracts between agents in the pipeline. Every agent
takes a typed input and returns a typed output, which makes the trace store
schema simple (just persist the JSON dump per agent run).

Provenance vocabulary used throughout:
- stated:               the candidate wrote this verbatim somewhere (free
                        text, deck slide, README, video transcript).
- inferred:             the agent synthesised this from artifacts without an
                        explicit statement.
- verified:             a verifier tool observed this in code, in the live
                        URL, or in repo metadata.
- insufficient_evidence: not enough signal to land any value.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Archetype(str, Enum):
    PRODUCT = "product"
    RESEARCH = "research"
    TOOL = "tool"
    DEMO = "demo"
    UNKNOWN = "unknown"


class AppType(str, Enum):
    WEB = "web"
    API = "api"
    CLI = "cli"
    NOTEBOOK = "notebook"
    ML_MODEL = "ml_model"
    MOBILE = "mobile"
    HARDWARE = "hardware"
    OTHER = "other"


class RubricDimensionId(str, Enum):
    PROBLEM = "problem_clarity"
    DEPTH = "solution_depth"
    AI_SOPHISTICATION = "ai_sophistication"
    FUNCTIONAL = "functional_correctness"
    UX = "ux_polish"
    COMMUNICATION = "communication"


class SubmissionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SCORED = "scored"
    FAILED = "failed"


Provenance = Literal["stated", "inferred", "verified", "unknown"]
EvidenceKind = Literal["stated", "inferred", "verified", "insufficient"]


class CandidateInfo(BaseModel):
    name: str
    email: str | None = None
    team: str | None = None


class ApiEndpoint(BaseModel):
    method: str = "GET"            # GET/HEAD/POST — destructive verbs rejected by the prober
    path: str                      # e.g. "/api/health" (joined to api_base_url or live_url)
    expected_status: int | None = None
    sample_body: str | None = None # only used for declared POST endpoints
    description: str | None = None


class DeclaredJourney(BaseModel):
    name: str
    steps: list[str] = Field(default_factory=list)
    expected_outcome: str = ""


class SubmissionArtifacts(BaseModel):
    submission_md_path: str
    repo_url: str | None = None
    live_url: str | None = None
    video_url: str | None = None
    deck_path: str | None = None
    test_credentials: str | None = None
    api_base_url: str | None = None
    api_endpoints: list[ApiEndpoint] = Field(default_factory=list)
    cli_command: str | None = None
    notebook_path: str | None = None
    declared_journeys: list[DeclaredJourney] = Field(default_factory=list)


class Submission(BaseModel):
    id: str
    candidate: CandidateInfo
    artifacts: SubmissionArtifacts
    submission_md_raw: str
    submission_md_sanitized: str | None = None
    archetype: Archetype = Archetype.UNKNOWN
    app_type: AppType = AppType.OTHER
    status: SubmissionStatus = SubmissionStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    is_anchor: bool = False


# --- Inference Agent output ----------------------------------------------


class InferredField(BaseModel, Generic[T]):
    """One value with provenance and confidence.

    `value` is `None` when the agent could not infer anything; in that case
    `source` should be 'unknown' and `provenance` should describe what was
    looked at and what was missing.
    """

    value: T | None = None
    source: Provenance = "unknown"
    provenance: str = ""
    confidence: float = 0.0


class InferredClaim(BaseModel):
    id: str
    text: str
    category: str = "feature"
    testable: bool = True
    expected_outcome: str | None = None
    source: Provenance = "inferred"
    provenance: str = ""
    confidence: float = 0.5


class InferredJourney(BaseModel):
    name: str
    steps: list[str] = Field(default_factory=list)
    expected_outcome: str = ""
    sample_input: str | None = None
    source: Provenance = "inferred"
    provenance: str = ""
    confidence: float = 0.5


class InferredAIComponent(BaseModel):
    name: str
    models: str | None = None
    description: str | None = None
    agentic_claim: str | None = None
    tools: list[str] = Field(default_factory=list)
    evals: str | None = None
    source: Provenance = "inferred"
    provenance: str = ""
    confidence: float = 0.5


class BuildLogEntry(BaseModel):
    timestamp: str | None = None
    task: str | None = None


class InferredSubmission(BaseModel):
    """Synthesised structured view of a submission.

    Every field carries enough provenance to let the rubric scorer and the
    dashboard cite where a value came from. Empty / unknown is a first-class
    state — we never invent.
    """

    candidate_identity: InferredField[CandidateInfo] = Field(
        default_factory=lambda: InferredField[CandidateInfo]()
    )
    problem_statement: InferredField[str] = Field(default_factory=lambda: InferredField[str]())
    tech_stack: InferredField[dict[str, str]] = Field(
        default_factory=lambda: InferredField[dict[str, str]]()
    )
    known_limitations: InferredField[list[str]] = Field(
        default_factory=lambda: InferredField[list[str]]()
    )
    build_log: InferredField[list[BuildLogEntry]] = Field(
        default_factory=lambda: InferredField[list[BuildLogEntry]]()
    )
    acknowledgements: InferredField[list[str]] = Field(
        default_factory=lambda: InferredField[list[str]]()
    )

    claims: list[InferredClaim] = Field(default_factory=list)
    user_journeys: list[InferredJourney] = Field(default_factory=list)
    ai_components: list[InferredAIComponent] = Field(default_factory=list)

    gaps: list[str] = Field(default_factory=list)
    summary_for_scorer: str = ""

    artifacts_seen: list[str] = Field(default_factory=list)
    tool_calls_made: int = 0


# --- Verifier agent outputs ----------------------------------------------


class GuardReport(BaseModel):
    sanitized_text: str
    injection_attempts: list[str] = Field(default_factory=list)
    severity: int = 0


class ArchetypeReport(BaseModel):
    archetype: Archetype
    confidence: float
    rationale: str


class RepoMetrics(BaseModel):
    repo_url: str
    default_branch: str | None = None
    languages: dict[str, int] = Field(default_factory=dict)
    total_commits: int = 0
    commits_in_window: int = 0
    commits_outside_window: int = 0
    first_commit_at: datetime | None = None
    last_commit_at: datetime | None = None
    contributors: int = 0
    has_readme: bool = False
    has_tests: bool = False
    has_ci: bool = False
    has_dockerfile: bool = False
    top_level_files: list[str] = Field(default_factory=list)
    line_count_estimate: int = 0
    notable_dependencies: list[str] = Field(default_factory=list)


class CodeAnalystReport(BaseModel):
    metrics: RepoMetrics | None = None
    quality_signals: dict[str, Any] = Field(default_factory=dict)
    integrity_flags: list[str] = Field(default_factory=list)
    summary: str = ""
    summary_for_scorer: str = ""


class JourneyResult(BaseModel):
    journey_name: str
    success: bool
    steps_completed: int
    total_steps: int
    final_observation: str
    screenshots: list[str] = Field(default_factory=list)
    failure_reason: str | None = None


class BrowserVerifierReport(BaseModel):
    live_url_reachable: bool
    journey_results: list[JourneyResult] = Field(default_factory=list)
    page_title: str | None = None
    notable_console_errors: list[str] = Field(default_factory=list)
    summary: str = ""
    summary_for_scorer: str = ""
    skipped: bool = False
    skipped_reason: str | None = None
    # True when one or more journeys could not complete because the live app is
    # gated behind a login / auth wall. Drives the legible "credential-walled"
    # insufficient reason in the scorer + dashboard.
    auth_blocked: bool = False


class AISophisticationReport(BaseModel):
    has_real_agentic_patterns: bool
    patterns_detected: list[str] = Field(default_factory=list)
    thin_wrapper_signals: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    score_band: str = "unknown"
    summary: str = ""
    summary_for_scorer: str = ""


class JudgeReviewItem(BaseModel):
    """A claim AutoJudge cannot verify from the public surface.

    Surfaced to human judges instead of penalising the candidate. Examples:
    Slack bot integrations, OAuth flows, hardware demos, paid-API features,
    enterprise SSO. The shortlist generator routes these here; humans decide.
    """

    claim: str
    reason: str = ""
    source: str = "inferred_submission"  # deck | video | repo | inferred_submission
    where: str | None = None


class CrossCheckReport(BaseModel):
    deck_summary: str = ""
    video_summary: str = ""
    discrepancies: list[dict[str, Any]] = Field(default_factory=list)
    judge_review_items: list[JudgeReviewItem] = Field(default_factory=list)
    consistent: bool = True
    summary: str = ""
    summary_for_scorer: str = ""


# --- Rubric output -------------------------------------------------------


class DimensionScore(BaseModel):
    """One rubric dimension's outcome.

    `raw_score` and `weighted_score` are None when there was not enough
    evidence to evaluate the dimension; in that case `evidence_kind` is
    'insufficient'. The total is normalised over evaluable dimensions.
    """

    dimension: RubricDimensionId
    raw_score: float | None = None
    weighted_score: float | None = None
    rationale: str = ""
    evidence: list[str] = Field(default_factory=list)
    evidence_kind: EvidenceKind = "inferred"
    cap_applied: bool = False
    cap_reason: str | None = None


Verdict = Literal["shortlist", "borderline", "below_threshold", "insufficient", "quarantined"]


class RubricScore(BaseModel):
    """Shortlist-generator output for one submission.

    `total_score` and `dimensions` are the automatable surface — what the
    pipeline could verify on its own. `judge_review_items` are everything
    we deferred to humans (credential-walled UIs, third-party integrations,
    hardware demos). `verdict` is the recommended bucket; `shortlist_rank`
    is assigned at leaderboard read time.

    AutoJudge produces a *recommendation*, not a final score. Human judges
    make the final call on the shortlisted candidates.
    """

    submission_id: str
    archetype: Archetype
    total_score: float
    dimensions: list[DimensionScore]
    summary: str = ""
    integrity_flags: list[str] = Field(default_factory=list)
    anchor_deltas: dict[str, float] = Field(default_factory=dict)
    evaluable_weight: int = 100
    normalized: bool = False
    judge_review_items: list[JudgeReviewItem] = Field(default_factory=list)
    verdict: Verdict = "borderline"


class VerifierRun(BaseModel):
    """One agent execution. Persisted to the trace store row-by-row."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    submission_id: str
    agent: str
    model: str | None = None
    provider: str | None = None
    started_at: datetime
    finished_at: datetime
    input_summary: str
    output: dict[str, Any]
    cost_usd: float = 0.0
    cost_is_precise: bool = False
    error: str | None = None
