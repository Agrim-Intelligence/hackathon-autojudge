"""Streamlit FlexIntake form.

Run with:
    streamlit run src/autojudge/intake/form.py

The form accepts any combination of artifacts. The candidate must provide
at least one of: GitHub repo URL, live deployed URL, demo video URL, or a
slide deck. Everything else is optional, including the SUBMISSION.md body.
The Inference Agent reads whichever artifacts were supplied and synthesises
a structured view of the submission with full provenance.

Persistence: the form is filesystem-free on the storage backend. Free-form
context is inlined on ``submissions.submission_md_raw`` and deck PDFs land
in ``submission_blobs`` keyed by submission_id. This means the intake form
and the dashboard service can run on different Railway services and still
share data through the Postgres trace store. A copy of the body / deck is
also written to the local data dir when present (best-effort backup for
local-dev re-runs); the orchestrator always reads from the store.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from autojudge.auth import require_basic_auth
from autojudge.config import get_settings
from autojudge.models import (
    ApiEndpoint,
    AppType,
    CandidateInfo,
    DeclaredJourney,
    Submission,
    SubmissionArtifacts,
    SubmissionStatus,
)
from autojudge.sanitize.guard import sanitize as _guard_sanitize
from autojudge.trace.store import get_store

logger = logging.getLogger(__name__)


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "anon"


def _gen_id(name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{_slug(name)}"


_VERB_RE = re.compile(r"^(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)$", re.IGNORECASE)


def _parse_endpoints(text: str) -> list[ApiEndpoint]:
    """Parse ``METHOD /path [expected_status]`` lines, lenient on shape.

    A bare ``/path`` defaults to GET. A trailing integer token is the expected
    status. Unrecognised leading tokens are treated as the path (method GET).
    """
    out: list[ApiEndpoint] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        toks = line.split()
        method = "GET"
        if _VERB_RE.match(toks[0]):
            method = toks.pop(0).upper()
        if not toks:
            continue
        status: int | None = None
        if toks[-1].isdigit():
            status = int(toks.pop())
        if not toks:
            continue
        out.append(ApiEndpoint(method=method, path=toks[0], expected_status=status))
    return out


def _parse_journeys(text: str) -> list[DeclaredJourney]:
    """Parse blank-line-separated blocks: first line = name, rest = steps."""
    out: list[DeclaredJourney] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        out.append(DeclaredJourney(name=lines[0], steps=lines[1:]))
    return out


def main() -> None:
    # Auth gate — no-op when AUTOJUDGE_INTAKE_BASIC_AUTH_USER / _PASS are
    # unset (open intake for candidates). When set, the shim renders a login
    # form first and short-circuits the rest of this function with st.stop().
    require_basic_auth("intake")

    settings = get_settings()
    store = get_store()
    submissions_dir = settings.submissions_dir

    st.set_page_config(
        page_title="Agrim AutoJudge — Intake",
        page_icon="📝",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _banner_left, _banner_right = st.columns([3, 1])
    with _banner_left:
        st.markdown("## 📝 AutoJudge · Submission Intake")
        st.caption(
            "Submit your project. At minimum provide one of: a GitHub repo, "
            "live URL, demo video, or slide deck."
        )
    with _banner_right:
        try:
            store.leaderboard(include_anchors=False)
            st.success("✓ Store connected")
        except Exception:
            st.warning("Store unavailable")
    st.divider()

    with st.expander(
        "Want to be more thorough? (optional template you can paste in the body)",
        expanded=False,
    ):
        st.markdown(
            "If you have time, the template below maps each section to a "
            "scoring dimension. Submissions using it tend to score higher on "
            "Communication because evidence is easier to attribute. But it is "
            "**not required** — paste anything you have, or nothing at all."
        )

    with st.form("submission_form", clear_on_submit=False):
        st.subheader("Candidate")
        col1, col2, col3 = st.columns(3)
        with col1:
            name = st.text_input("Full name *")
        with col2:
            email = st.text_input(
                "Email",
                help="Used for post-event communication. Not shared with judges or surfaced on the scoring dashboard.",
            )
        with col3:
            team = st.text_input("Team name (or 'solo')", placeholder="solo or team name")

        st.subheader("Artifacts (provide at least one)")
        repo_url = st.text_input("GitHub repository URL")
        live_url = st.text_input("Live deployed URL")
        video_url = st.text_input(
            "Demo video URL (YouTube recommended — transcript will be extracted for scoring)"
        )
        test_credentials = st.text_area(
            "Test credentials (if your app requires login)",
            height=80,
            help="Passed to the browser automation agent to log in. Never stored in logs or shown to judges. Only used during automated testing.",
        )
        deck_file = st.file_uploader("Slide deck (PDF)", type=["pdf"])

        st.subheader("App type")
        app_type_value = st.selectbox(
            "What kind of app is this?",
            options=[t.value for t in AppType],
            index=list(AppType).index(AppType.WEB),
            help="Drives which verifier runs. Web = Playwright browser automation; API = HTTP endpoint prober; CLI/Notebook/other = routed to judge review. Web is the default.",
        )

        st.subheader("Additional details (optional — improves scoring accuracy)")
        st.caption(
            "Fill in whatever matches your app — the auto-judge uses these to "
            "probe the right surface. Leave the rest blank."
        )
        api_base_url = st.text_input("API base URL")
        api_endpoints_raw = st.text_area(
            "API endpoints (one per line: `METHOD /path [expected_status]`)",
            height=100,
        )
        cli_command = st.text_input(
            "CLI command (app-type hint)",
            help="Used to classify your submission as a CLI app. The command is NOT executed — it is a classification signal only.",
        )
        notebook_path = st.text_input(
            "Notebook path in repo (app-type hint)",
            help="E.g. notebooks/demo.ipynb. Used to classify as a notebook app. The notebook is NOT executed.",
        )
        journeys_raw = st.text_area(
            "User journeys to test (optional — overrides auto-detected journeys)",
            height=120,
            help="Each journey: first line = name, remaining lines = one step per line. Separate journeys with a blank line. These steps are what the browser automation agent will actually run on your live URL.",
        )

        st.subheader("Free-form context (optional)")
        st.markdown(
            "Paste anything that helps a human and the auto-judge understand "
            "what you built — problem, claims, tech stack, what to test. "
            "Plain prose is fine. The auto-judge will infer structure."
        )
        submission_md = st.text_area(
            "Notes / SUBMISSION.md — paste anything helpful (optional)", height=400
        )

        submitted = st.form_submit_button("Submit", type="primary")

    if not submitted:
        return

    errors: list[str] = []
    if not name.strip():
        errors.append("Candidate name is required.")
    artifacts_supplied = [
        bool(repo_url.strip()),
        bool(live_url.strip()),
        bool(video_url.strip()),
        deck_file is not None,
    ]
    if not any(artifacts_supplied):
        errors.append(
            "Provide at least one artifact: GitHub repo, live URL, demo video, or slide deck."
        )
    if errors:
        for e in errors:
            st.error(e)
        return

    if video_url.strip() and not re.search(
        r"(youtube\.com/watch|youtu\.be)", video_url, re.IGNORECASE
    ):
        st.warning(
            "⚠️ Transcript extraction supports YouTube links. Other video URLs will be "
            "referenced but not transcribed for scoring."
        )

    if journeys_raw.strip():
        _preview = _parse_journeys(journeys_raw)
        if _preview:
            st.caption(
                "Journeys parsed: "
                + ", ".join(f'"{j.name}"' for j in _preview[:3])
                + (f" +{len(_preview)-3} more" if len(_preview) > 3 else "")
            )
        else:
            st.warning(
                "⚠️ Could not parse any journeys. Check that journeys are separated by a "
                "blank line and the first line of each block is the journey name."
            )

    if api_endpoints_raw.strip():
        _ep_preview = _parse_endpoints(api_endpoints_raw)
        if _ep_preview:
            st.caption(
                "Endpoints parsed: "
                + ", ".join(f"{e.method} {e.path}" for e in _ep_preview[:5])
            )
        else:
            st.warning("⚠️ No valid endpoints parsed. Use format: GET /api/health 200")

    sub_id = _gen_id(name)
    body = submission_md.strip()
    if not body:
        body = "(no free-form context supplied; rely on linked artifacts)"

    # Best-effort local copy of the submission body and deck. When the intake
    # form runs on a dedicated Railway service without a volume mount, this
    # block silently no-ops; the canonical persistence is in the trace store.
    md_path_str: str | None = None
    deck_path_str: str | None = None
    try:
        sub_dir = submissions_dir / sub_id
        sub_dir.mkdir(parents=True, exist_ok=True)
        md_path = sub_dir / "submission.md"
        md_path.write_text(body + "\n", encoding="utf-8")
        md_path_str = str(md_path)
        if deck_file is not None:
            deck_path = sub_dir / "deck.pdf"
            deck_path.write_bytes(deck_file.getvalue())
            deck_path_str = str(deck_path)
    except OSError as exc:
        logger.info("intake: local artifact write skipped (%s)", exc)

    meta = {
        "id": sub_id,
        "candidate": {
            "name": name.strip(),
            "email": email.strip() or None,
            "team": team.strip() or None,
        },
        "repo_url": repo_url.strip() or None,
        "live_url": live_url.strip() or None,
        "video_url": video_url.strip() or None,
        "deck_path": deck_path_str,
        "test_credentials": test_credentials.strip() or None,
        "app_type": app_type_value,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Sanitize candidate-declared journey text before it reaches the DB and downstream LLMs.
    # journey steps are candidate-controlled and must go through the same guard as the submission body.
    _sanitized_journeys_raw = _guard_sanitize(journeys_raw, source_label="declared-journeys")[0].sanitized_text if journeys_raw.strip() else journeys_raw

    submission = Submission(
        id=sub_id,
        candidate=CandidateInfo(**meta["candidate"]),
        artifacts=SubmissionArtifacts(
            submission_md_path=md_path_str or "",
            repo_url=meta["repo_url"],
            live_url=meta["live_url"],
            video_url=meta["video_url"],
            deck_path=deck_path_str,
            test_credentials=meta["test_credentials"],
            api_base_url=api_base_url.strip() or None,
            api_endpoints=_parse_endpoints(api_endpoints_raw),
            cli_command=cli_command.strip() or None,
            notebook_path=notebook_path.strip() or None,
            declared_journeys=_parse_journeys(_sanitized_journeys_raw),
        ),
        app_type=AppType(app_type_value),
        submission_md_raw=body,
        status=SubmissionStatus.PENDING,
    )
    store.upsert_submission(submission)
    if deck_file is not None:
        store.put_blob(
            sub_id,
            "deck.pdf",
            deck_file.getvalue(),
            content_type="application/pdf",
        )

    st.success(f"✓ Submission received: `{sub_id}`")
    received_items = []
    if meta.get("repo_url"):
        received_items.append("GitHub repo")
    if meta.get("live_url"):
        received_items.append("Live URL")
    if meta.get("video_url"):
        received_items.append("Demo video")
    if deck_file is not None:
        received_items.append("Slide deck")
    if meta.get("test_credentials"):
        received_items.append("Test credentials")
    st.info(
        "**Received:** " + (", ".join(received_items) if received_items else "context only")
        + "\n\nThe auto-judge will run shortly. Nothing else needed from you."
    )
    st.caption(f"Submission ID: `{sub_id}`")


if __name__ == "__main__":
    main()
