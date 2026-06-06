import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from autojudge.agents.browser_verifier import (
    StepRecord,
    _grounded_success,
    _is_flaky_failure,
)
from autojudge.orchestrator import _browser_run_conclusive
from autojudge.agents.rubric_scorer import _max_evidence_kind
from autojudge.models import (
    AISophisticationReport,
    BrowserVerifierReport,
    CodeAnalystReport,
    CrossCheckReport,
    InferredSubmission,
    JourneyResult,
    RubricDimensionId,
)


# ---------------------------------------------------------------------------
# _grounded_success helpers
# ---------------------------------------------------------------------------

def _elements(body="", n_interactive=0, has_password=False, auth_text=""):
    interactive = [{"type": "password"}] if has_password else []
    interactive += [{"type": "button"} for _ in range(n_interactive)]
    return {
        "bodyText": body,
        "interactive": interactive,
        "headings": [{"text": auth_text}] if auth_text else [],
    }


def _click_record():
    return StepRecord(step=0, action={"action": "click"}, observation="button clicked")


def _noop_record():
    return StepRecord(step=0, action={"action": "done"}, observation="success")


# ---------------------------------------------------------------------------
# _grounded_success
# ---------------------------------------------------------------------------

def test_substantial_page_no_interaction_grounds():
    """A rich, non-auth page grounds a read-only journey."""
    elements = _elements(body="x" * 650, n_interactive=15)
    ok, _ = _grounded_success(elements, [_noop_record()])
    assert ok is True


def test_thin_page_with_interaction_grounds():
    """Thin page + real click satisfies the grounding requirement."""
    elements = _elements(body="x" * 200, n_interactive=6)
    ok, _ = _grounded_success(elements, [_click_record()])
    assert ok is True


def test_bare_auth_shell_rejected():
    """A password-form-only page is rejected even with interaction."""
    elements = _elements(body="", n_interactive=1, has_password=True)
    ok, reason = _grounded_success(elements, [_click_record()])
    assert ok is False
    assert "auth" in reason.lower() or "login" in reason.lower()


def test_thin_page_no_interaction_rejected():
    """Thin page + no real action = no grounding."""
    elements = _elements(body="x" * 50, n_interactive=2)
    ok, reason = _grounded_success(elements, [_noop_record()])
    assert ok is False


def test_auth_gate_text_rejects_substantial_body():
    """Auth-gate text overrides an otherwise substantial body."""
    elements = _elements(
        body="x" * 700,
        n_interactive=15,
        auth_text="sign in to continue",
    )
    ok, reason = _grounded_success(elements, [_click_record()])
    assert ok is False


# ---------------------------------------------------------------------------
# _is_flaky_failure
# ---------------------------------------------------------------------------

def _journey(success=False, failure_reason=None):
    return JourneyResult(
        journey_name="test",
        success=success,
        steps_completed=0,
        total_steps=3,
        final_observation="",
        failure_reason=failure_reason,
    )


def test_step_budget_exhausted_is_flaky():
    assert _is_flaky_failure(_journey(failure_reason="step budget exhausted after 20 steps")) is True


def test_navigation_failed_timeout_is_flaky():
    assert _is_flaky_failure(_journey(failure_reason="navigation failed: timeout")) is True


def test_none_failure_reason_not_flaky():
    assert _is_flaky_failure(_journey(success=False, failure_reason=None)) is False


def test_deliberate_negative_not_flaky():
    assert _is_flaky_failure(_journey(failure_reason="claimed success not grounded: thin page")) is False


# ---------------------------------------------------------------------------
# _browser_run_conclusive
# ---------------------------------------------------------------------------

def test_skipped_is_conclusive():
    assert _browser_run_conclusive({"skipped": True}) is True


def test_auth_blocked_is_conclusive():
    assert _browser_run_conclusive({"auth_blocked": True, "live_url_reachable": True}) is True


def test_reachable_with_success_is_conclusive():
    cached = {
        "live_url_reachable": True,
        "journey_results": [{"success": True}],
    }
    assert _browser_run_conclusive(cached) is True


def test_reachable_all_fail_not_conclusive():
    cached = {
        "live_url_reachable": True,
        "journey_results": [{"success": False}],
    }
    assert _browser_run_conclusive(cached) is False


def test_unreachable_is_conclusive():
    cached = {"live_url_reachable": False, "journey_results": []}
    assert _browser_run_conclusive(cached) is True


# ---------------------------------------------------------------------------
# _max_evidence_kind
# ---------------------------------------------------------------------------

def _make_browser(reachable=False, page_title=None, auth_blocked=False, journey_ok=False):
    results = []
    if journey_ok:
        results.append(JourneyResult(
            journey_name="j",
            success=True,
            steps_completed=1,
            total_steps=1,
            final_observation="done",
        ))
    return BrowserVerifierReport(
        live_url_reachable=reachable,
        page_title=page_title,
        auth_blocked=auth_blocked,
        journey_results=results,
    )


def _make_inferred(stated=False):
    sub = InferredSubmission()
    if stated:
        from autojudge.models import InferredField
        sub.problem_statement = InferredField[str](value="A real problem", source="stated", confidence=0.9)
    return sub


def test_functional_verified_when_browser_journey_succeeds():
    browser = _make_browser(reachable=True, page_title="App", journey_ok=True)
    kind = _max_evidence_kind(
        RubricDimensionId.FUNCTIONAL,
        inferred=_make_inferred(),
        code=CodeAnalystReport(),
        ai_soph=AISophisticationReport(has_real_agentic_patterns=False),
        browser=browser,
        cross=CrossCheckReport(),
    )
    assert kind == "verified"


def test_functional_inferred_when_page_renders_no_success():
    browser = _make_browser(reachable=True, page_title="App", auth_blocked=False)
    kind = _max_evidence_kind(
        RubricDimensionId.FUNCTIONAL,
        inferred=_make_inferred(),
        code=CodeAnalystReport(),
        ai_soph=AISophisticationReport(has_real_agentic_patterns=False),
        browser=browser,
        cross=CrossCheckReport(),
    )
    assert kind == "inferred"


def test_ux_verified_when_browser_journey_succeeds():
    browser = _make_browser(reachable=True, page_title="App", journey_ok=True)
    kind = _max_evidence_kind(
        RubricDimensionId.UX,
        inferred=_make_inferred(),
        code=CodeAnalystReport(),
        ai_soph=AISophisticationReport(has_real_agentic_patterns=False),
        browser=browser,
        cross=CrossCheckReport(),
    )
    assert kind == "verified"


def test_ux_inferred_when_rendered_but_no_journey():
    browser = _make_browser(reachable=True, page_title="App", auth_blocked=False)
    kind = _max_evidence_kind(
        RubricDimensionId.UX,
        inferred=_make_inferred(),
        code=CodeAnalystReport(),
        ai_soph=AISophisticationReport(has_real_agentic_patterns=False),
        browser=browser,
        cross=CrossCheckReport(),
    )
    assert kind == "inferred"


def test_functional_stated_when_unreachable_and_words_present():
    browser = _make_browser(reachable=False)
    kind = _max_evidence_kind(
        RubricDimensionId.FUNCTIONAL,
        inferred=_make_inferred(stated=True),
        code=CodeAnalystReport(),
        ai_soph=AISophisticationReport(has_real_agentic_patterns=False),
        browser=browser,
        cross=CrossCheckReport(),
    )
    assert kind == "stated"


def test_functional_inferred_when_unreachable_no_words():
    browser = _make_browser(reachable=False)
    kind = _max_evidence_kind(
        RubricDimensionId.FUNCTIONAL,
        inferred=_make_inferred(stated=False),
        code=CodeAnalystReport(),
        ai_soph=AISophisticationReport(has_real_agentic_patterns=False),
        browser=browser,
        cross=CrossCheckReport(),
    )
    assert kind == "inferred"
