"""Streamlit FlexIntake form.

Run with:
    streamlit run src/autojudge/intake/form.py

The form accepts any combination of artifacts. The candidate must provide
at least one of: GitHub repo URL, live deployed URL, demo video URL, or a
slide deck. Everything else is optional, including the SUBMISSION.md body.
The Inference Agent reads whichever artifacts were supplied and synthesises
a structured view of the submission with full provenance.

Each submission writes to data/submissions/<id>/ as:
- submission.md       (free-form context, or empty note if not supplied)
- deck.pdf            (uploaded slide deck if provided)
- meta.json           (URLs, candidate info)
- status=pending in the trace store so the batch runner picks it up
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from autojudge.auth import require_basic_auth
from autojudge.config import get_settings
from autojudge.models import (
    CandidateInfo,
    Submission,
    SubmissionArtifacts,
    SubmissionStatus,
)
from autojudge.trace.store import get_store


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "anon"


def _gen_id(name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{_slug(name)}"


def main() -> None:
    # Auth gate — no-op when AUTOJUDGE_INTAKE_BASIC_AUTH_USER / _PASS are
    # unset (open intake for candidates). When set, the shim renders a login
    # form first and short-circuits the rest of this function with st.stop().
    require_basic_auth("intake")

    settings = get_settings()
    store = get_store()
    submissions_dir = settings.submissions_dir

    st.set_page_config(page_title="Agrim AutoJudge — Intake", layout="wide")
    st.title("Agrim AutoJudge — Submission Intake")
    st.caption(
        "Submit your project. At minimum you need one of: a GitHub repo, a "
        "live URL, a demo video, or a slide deck. The auto-judge will figure "
        "out the rest and attribute every score to a specific piece of "
        "evidence."
    )

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
            email = st.text_input("Email")
        with col3:
            team = st.text_input("Team name (or 'solo')")

        st.subheader("Artifacts (provide at least one)")
        repo_url = st.text_input("GitHub repository URL")
        live_url = st.text_input("Live deployed URL")
        video_url = st.text_input("Demo video URL (YouTube only for v1.0)")
        test_credentials = st.text_area(
            "Test credentials / sample inputs (if your app is gated)",
            height=80,
        )
        deck_file = st.file_uploader("Slide deck (PDF, optional)", type=["pdf"])

        st.subheader("Free-form context (optional)")
        st.markdown(
            "Paste anything that helps a human and the auto-judge understand "
            "what you built — problem, claims, tech stack, what to test. "
            "Plain prose is fine. The auto-judge will infer structure."
        )
        submission_md = st.text_area("Notes / SUBMISSION.md content", height=400)

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

    sub_id = _gen_id(name)
    sub_dir = submissions_dir / sub_id
    sub_dir.mkdir(parents=True, exist_ok=True)

    md_path = sub_dir / "submission.md"
    body = submission_md.strip()
    if not body:
        body = "(no free-form context supplied; rely on linked artifacts)"
    md_path.write_text(body + "\n", encoding="utf-8")

    deck_path: str | None = None
    if deck_file is not None:
        deck_path = str(sub_dir / "deck.pdf")
        Path(deck_path).write_bytes(deck_file.getvalue())

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
        "deck_path": deck_path,
        "test_credentials": test_credentials.strip() or None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (sub_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    submission = Submission(
        id=sub_id,
        candidate=CandidateInfo(**meta["candidate"]),
        artifacts=SubmissionArtifacts(
            submission_md_path=str(md_path),
            repo_url=meta["repo_url"],
            live_url=meta["live_url"],
            video_url=meta["video_url"],
            deck_path=deck_path,
            test_credentials=meta["test_credentials"],
        ),
        submission_md_raw=body,
        status=SubmissionStatus.PENDING,
    )
    store.upsert_submission(submission)

    st.success(f"Submission received: `{sub_id}`")
    st.info(
        "Queued. The auto-judge will infer structure from your artifacts and "
        "internal judges will review the ranked output. Nothing else needed "
        "from you."
    )
    st.code(json.dumps(meta, indent=2), language="json")


if __name__ == "__main__":
    main()
