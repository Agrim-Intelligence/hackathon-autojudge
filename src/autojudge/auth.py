"""Streamlit basic-auth shim for the dashboard + intake form.

Designed for the MVP Railway deploy where we don't yet have Cloudflare Access
or a full SSO front door. The intent is intentionally simple: a single shared
username/password per role, persisted in env vars, compared with
``hmac.compare_digest``.

Two roles are supported:

- ``dashboard`` — internal judges. Always required in production.
- ``intake`` — candidate submission form. Often left open (env vars empty)
  for the duration of the hackathon, then re-locked.

When either ``..._USER`` or ``..._PASS`` env var for a role is empty the shim
short-circuits — useful for local development and for opening intake to
candidates without re-deploying.

Phase 2 will replace this with Cloudflare Access SSO; the
``_judge_identity()`` plumbing in the dashboard already prefers CF headers
when present, so swapping the front door requires no code change here.
"""
from __future__ import annotations

import hmac
import os
from typing import Literal

import streamlit as st


Role = Literal["dashboard", "intake"]


def _creds_for(role: Role) -> tuple[str, str] | None:
    """Return (user, pass) for a role, or None when auth is disabled."""
    prefix = "AUTOJUDGE_DASHBOARD_BASIC_AUTH" if role == "dashboard" else "AUTOJUDGE_INTAKE_BASIC_AUTH"
    user = os.environ.get(f"{prefix}_USER", "").strip()
    pw = os.environ.get(f"{prefix}_PASS", "").strip()
    if not user or not pw:
        return None
    return user, pw


def require_basic_auth(role: Role) -> str | None:
    """Gate the current Streamlit page behind a username/password.

    Returns the authenticated username on success, or ``None`` when auth is
    disabled (local dev). Calls ``st.stop()`` on a failed or pending login,
    so callers can simply invoke and continue without checking the return
    value when they don't need the identity.

    The login form is rendered inline; we deliberately avoid query-string
    redirects so the page works behind Railway's TCP proxy without extra
    configuration.
    """
    creds = _creds_for(role)
    if creds is None:
        # Auth not configured for this role — open access.
        return None

    expected_user, expected_pass = creds
    session_key = f"_autojudge_auth_user_{role}"

    if st.session_state.get(session_key):
        return st.session_state[session_key]

    st.set_page_config(page_title="Agrim AutoJudge — Sign in", layout="centered")
    st.title("Agrim AutoJudge")
    st.caption(f"Sign in to access the {role} surface.")
    with st.form("login_form", clear_on_submit=False):
        user = st.text_input("Username", autocomplete="username")
        pw = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        # hmac.compare_digest avoids timing-side-channel leaks; the inputs
        # are coerced to str first because text_input returns Any-typed.
        if hmac.compare_digest(str(user), expected_user) and hmac.compare_digest(
            str(pw), expected_pass
        ):
            st.session_state[session_key] = user
            st.rerun()
        else:
            st.error("Invalid credentials. Try again.")
    st.stop()
    return None


def current_user(role: Role) -> str | None:
    """Return the cached auth user for the role, or None when not signed in."""
    session_key = f"_autojudge_auth_user_{role}"
    return st.session_state.get(session_key)
