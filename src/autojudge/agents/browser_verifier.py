"""Browser verifier: Playwright + LLM driver executing user journeys.

For each journey from the parsed SUBMISSION.md, the agent navigates to the
live URL and repeatedly:
1. Snapshots interactive elements on the page
2. Asks the LLM for the next action
3. Executes the action
4. Until success / failure / step budget exhausted

Screenshots are saved per step for evidence. Degrades gracefully if Playwright
or the live URL is unreachable.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..intake.deploy import probe as probe_deploy
from ..llm import LLMResponse, PromptPart, get_llm
from ..models import BrowserVerifierReport, InferredJourney, JourneyResult
from ..sanitize.guard import sanitize

# Archetypes whose live pages are typically SPA/JS-app heavy and need a larger
# step budget to navigate past hydration and multi-screen flows.
_SPA_ARCHETYPES = {"product", "tool", "research"}

# SPA bootstrap shell markers — a page showing only these has not hydrated.
_SPA_PLACEHOLDER = "You need to enable JavaScript to run this app."
_MIN_HYDRATED_BODY_CHARS = 60

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    return (Path(__file__).resolve().parents[3] / "prompts" / "browser_planner.md").read_text(
        encoding="utf-8"
    )


@dataclass
class StepRecord:
    step: int
    action: dict[str, Any]
    observation: str
    screenshot_path: str | None = None


@dataclass
class JourneyRun:
    journey: InferredJourney
    records: list[StepRecord] = field(default_factory=list)


# TODO(orchestrator): pass archetype=... from the parsed submission so the
# step budget is chosen per archetype. Optional kwarg keeps the existing call
# site in orchestrator.py working unchanged until then.
def verify(
    live_url: str | None,
    journeys: list[InferredJourney],
    submission_id: str,
    test_credentials: str | None,
    archetype: str | None = None,
) -> tuple[BrowserVerifierReport, list[LLMResponse]]:
    settings = get_settings()
    if not live_url:
        return (
            BrowserVerifierReport(
                live_url_reachable=False,
                skipped=True,
                skipped_reason="No live URL provided.",
                summary_for_scorer="No live URL — browser verification skipped.",
            ),
            [],
        )

    deploy = probe_deploy(live_url, timeout=settings.autojudge_browser_timeout_s)
    if not deploy.reachable:
        return (
            BrowserVerifierReport(
                live_url_reachable=False,
                skipped=True,
                skipped_reason=f"Live URL not reachable: {deploy.error or deploy.status_code}",
                summary_for_scorer=(
                    f"Live URL not reachable (status={deploy.status_code} error={deploy.error}); "
                    "no functional verification possible."
                ),
            ),
            [],
        )

    if not journeys:
        return (
            BrowserVerifierReport(
                live_url_reachable=True,
                skipped=True,
                skipped_reason="No user journeys declared by the candidate.",
                page_title=deploy.title,
                summary_for_scorer=(
                    f"Live URL reachable ({deploy.title or 'no title'}) but no user journeys "
                    "inferred; cannot evaluate functional correctness end-to-end."
                ),
            ),
            [],
        )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return (
            BrowserVerifierReport(
                live_url_reachable=True,
                skipped=True,
                skipped_reason="Playwright not installed.",
                page_title=deploy.title,
                summary_for_scorer="Playwright not installed; browser verification skipped.",
            ),
            [],
        )

    screenshots_dir = settings.submissions_dir / submission_id / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    llm = get_llm()
    system = _load_prompt()
    journey_results: list[JourneyResult] = []
    llm_calls: list[LLMResponse] = []
    console_errors: list[str] = []
    hydrated_titles: list[str] = []

    with sync_playwright() as pw:
        browser = _launch_browser(pw, settings.autojudge_browser_headless)
        if browser is None:
            reason = (
                "Chromium launch failed. Ensure Playwright's bundled Chromium is "
                "installed via `playwright install chromium`. The full Chromium "
                "channel is used (channel='chromium') so the headless_shell binary "
                "is not required."
            )
            logger.warning(reason)
            return (
                BrowserVerifierReport(
                    live_url_reachable=True,
                    skipped=True,
                    skipped_reason=reason,
                    page_title=deploy.title,
                    summary_for_scorer=(
                        "Browser verification skipped: Chromium binary unavailable on this host. "
                        "Functional and UX dimensions cannot be observed; treat any web-UI claims "
                        "as judge-review items rather than verified."
                    ),
                ),
                [],
            )
        try:
            for j_idx, journey in enumerate(journeys):
                result, calls, errs, hydrated_title = _run_journey(
                    browser=browser,
                    journey=journey,
                    j_idx=j_idx,
                    live_url=live_url,
                    test_credentials=test_credentials,
                    screenshots_dir=screenshots_dir,
                    settings=settings,
                    llm=llm,
                    system_prompt=system,
                    archetype=archetype,
                )
                journey_results.append(result)
                llm_calls.extend(calls)
                console_errors.extend(errs)
                if hydrated_title:
                    hydrated_titles.append(hydrated_title)
        finally:
            browser.close()

    page_title = _best_title(deploy.title, hydrated_titles)
    overall_summary = _summarize(journey_results)
    auth_blocked = any(_journey_blocked_by_auth(j) for j in journey_results)
    scorer_summary = overall_summary
    journeys_ran = bool(journey_results)
    none_succeeded = not any(j.success for j in journey_results)
    if auth_blocked and none_succeeded:
        scorer_summary += (
            " Journeys were blocked by a login / auth wall"
            + (
                "; no working test credentials were available."
                if not test_credentials
                else " despite provided test credentials."
            )
            + " Treat functional/UX as judge-review items, not weak work."
        )
    elif journeys_ran and none_succeeded:
        # The page reached and rendered, but the scripted journeys ran out of
        # step budget. Without this clause the scorer sees only the bare
        # "0/N journeys succeeded." count and nulls UX — discarding the
        # render evidence the verifier actually observed. Report it as
        # observed rendering, NOT journey success (grounding stays intact).
        scorer_summary += " " + _render_evidence_clause(page_title, journey_results)
    return (
        BrowserVerifierReport(
            live_url_reachable=True,
            journey_results=journey_results,
            page_title=page_title,
            notable_console_errors=console_errors[:10],
            summary=overall_summary,
            summary_for_scorer=scorer_summary,
            auth_blocked=auth_blocked,
        ),
        llm_calls,
    )


def _run_journey(
    *,
    browser,
    journey: InferredJourney,
    j_idx: int,
    live_url: str,
    test_credentials: str | None,
    screenshots_dir: Path,
    settings,
    llm,
    system_prompt: str,
    archetype: str | None = None,
) -> tuple[JourneyResult, list[LLMResponse], list[str], str | None]:
    records: list[StepRecord] = []
    calls: list[LLMResponse] = []
    console_errors: list[str] = []
    hydrated_title: str | None = None

    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="AgrimAutoJudge/0.1 (+https://agrim.ai)",
    )
    page = context.new_page()
    page.on("console", lambda msg: console_errors.append(f"{msg.type}: {msg.text}") if msg.type in {"error", "warning"} else None)

    try:
        page.goto(live_url, timeout=settings.autojudge_browser_timeout_s * 1000, wait_until="domcontentloaded")
    except Exception as exc:
        return (
            JourneyResult(
                journey_name=journey.name,
                success=False,
                steps_completed=0,
                total_steps=len(journey.steps),
                final_observation="",
                failure_reason=f"navigation failed: {exc}",
            ),
            calls,
            console_errors,
            hydrated_title,
        )

    js_shell_detected = _wait_for_hydration(page, settings.autojudge_browser_timeout_s)
    try:
        title = page.title()
        if title and title.strip().lower() != "streamlit":
            hydrated_title = title.strip()
    except Exception:
        pass

    max_steps = (
        settings.autojudge_browser_max_steps_spa
        if js_shell_detected or (archetype in _SPA_ARCHETYPES)
        else settings.autojudge_browser_max_steps
    )

    success = False
    final_observation = ""
    failure_reason: str | None = None
    screenshots: list[str] = []

    for step in range(max_steps):
        try:
            elements = _interactive_elements(page)
        except Exception as exc:
            failure_reason = f"failed to snapshot page: {exc}"
            break

        # Sanitize untrusted live-page text before it reaches the planner LLM:
        # a candidate's page must not be able to inject instructions.
        injection_note = ""
        raw_text = "\n".join(
            [elements.get("bodyText", "") or ""]
            + [h.get("text", "") for h in elements.get("headings", [])]
            + [e.get("text", "") for e in elements.get("interactive", [])]
        )
        guard, guard_resp = sanitize(raw_text, source_label="live-page")
        if guard_resp is not None:
            calls.append(guard_resp)
        elements = {**elements, "bodyText": guard.sanitized_text}
        if guard.severity >= 2:
            injection_note = (
                f" [guard: possible injection in live page, severity={guard.severity}]"
            )

        snap = {
            "url": page.url,
            "title": page.title(),
            "elements": elements,
        }
        user = (
            f"### Journey\nName: {journey.name}\nSteps:\n"
            + "\n".join(f"- {s}" for s in journey.steps)
            + f"\nExpected outcome: {journey.expected_outcome}\n"
            + (f"Sample input: {journey.sample_input}\n" if journey.sample_input else "")
            + (f"Test credentials available: {test_credentials}\n" if test_credentials else "")
            + "\n### History of actions so far\n"
            + (
                "\n".join(
                    f"step {r.step}: {json.dumps(r.action)} -> {r.observation[:200]}"
                    for r in records
                )
                or "(none yet)"
            )
            + "\n\n### Current page state\n"
            + json.dumps(snap, indent=2)[:6000]
        )

        try:
            data, resp = llm.complete_json(
                system=system_prompt, user=user, tier="reasoning", max_tokens=512
            )
            calls.append(resp)
        except Exception as exc:
            failure_reason = f"LLM planning failed: {exc}"
            break

        action = data.get("action", "done")
        observation = ""
        screenshot_path: str | None = None

        try:
            if action == "done":
                claimed = bool(data.get("success", False))
                final_observation = str(data.get("observation", ""))
                observation = final_observation
                # Always capture a final-state screenshot — the LLM's "done" is
                # the moment we most want evidence for, and the old code broke
                # here without one.
                done_shot = str(screenshots_dir / f"journey{j_idx}_done.png")
                try:
                    page.screenshot(path=done_shot, full_page=False)
                    screenshots.append(done_shot)
                except Exception:
                    done_shot = None
                # Ground the LLM's success claim in real page evidence. Journey
                # `success` is otherwise pure LLM self-report and hallucinates
                # (e.g. claiming a working UI on a bare auth-gated shell).
                if claimed:
                    grounded, why = _grounded_success(elements, records)
                    success = grounded
                    if not grounded:
                        failure_reason = (
                            f"claimed success not grounded in page evidence: {why}"
                        )
                records.append(
                    StepRecord(step=step, action=data, observation=observation, screenshot_path=done_shot)
                )
                break
            if action == "click":
                _click(page, elements, int(data.get("ref", -1)))
                observation = f"clicked element ref={data.get('ref')}"
            elif action == "type":
                _type(page, elements, int(data.get("ref", -1)), str(data.get("text", "")))
                observation = f"typed into ref={data.get('ref')}"
            elif action == "press_enter":
                ref = data.get("ref")
                if ref is not None:
                    _click(page, elements, int(ref))
                page.keyboard.press("Enter")
                observation = "pressed Enter"
            elif action == "goto":
                page.goto(str(data["url"]), timeout=settings.autojudge_browser_timeout_s * 1000)
                observation = f"navigated to {data['url']}"
            elif action == "scroll":
                direction = data.get("direction", "down")
                page.mouse.wheel(0, 800 if direction == "down" else -800)
                observation = f"scrolled {direction}"
            elif action == "wait":
                secs = min(5, max(1, int(data.get("seconds", 2))))
                time.sleep(secs)
                observation = f"waited {secs}s"
            else:
                observation = f"unknown action: {action}"
            page.wait_for_load_state("networkidle", timeout=4000)
        except Exception as exc:
            observation = f"action errored: {exc}"

        if injection_note:
            observation += injection_note

        screenshot_path = str(screenshots_dir / f"journey{j_idx}_step{step}.png")
        try:
            page.screenshot(path=screenshot_path, full_page=False)
            screenshots.append(screenshot_path)
        except Exception:
            screenshot_path = None

        records.append(
            StepRecord(step=step, action=data, observation=observation, screenshot_path=screenshot_path)
        )

    else:
        failure_reason = "step budget exhausted before reaching expected outcome"

    context.close()
    return (
        JourneyResult(
            journey_name=journey.name,
            success=success,
            steps_completed=len(records),
            total_steps=len(journey.steps),
            final_observation=final_observation,
            screenshots=screenshots,
            failure_reason=failure_reason if not success else None,
        ),
        calls,
        console_errors,
        hydrated_title,
    )


def _wait_for_hydration(page, timeout_s: int) -> bool:
    """Wait for an SPA shell to hydrate into real content.

    Streamlit/React apps serve a bootstrap shell (body == "You need to enable
    JavaScript to run this app.") that the verifier would otherwise snapshot as
    an empty page. Poll until the body has real content or the app signals
    readiness. Returns True if a JS-app shell was observed at any point (used to
    widen the step budget). Tolerates timeouts: never raises.
    """
    js_shell_detected = False
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_s * 1000)
    except Exception:
        pass

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            state = page.evaluate(
                """
                () => ({
                  text: (document.body && document.body.innerText) || '',
                  prerenderReady: window.prerenderReady === true,
                })
                """
            )
        except Exception:
            break
        text = (state.get("text") or "").strip()
        if state.get("prerenderReady"):
            return js_shell_detected
        if _SPA_PLACEHOLDER in text or len(text) < _MIN_HYDRATED_BODY_CHARS:
            js_shell_detected = True
            try:
                page.wait_for_timeout(500)
            except Exception:
                break
            continue
        return js_shell_detected
    return js_shell_detected


def _best_title(deploy_title: str | None, hydrated_titles: list[str]) -> str | None:
    """Prefer a real post-hydration title over the SPA shell title."""
    for title in hydrated_titles:
        if title and title.strip().lower() != "streamlit":
            return title.strip()
    return deploy_title


def _interactive_elements(page, limit: int = 40) -> list[dict[str, Any]]:
    """Snapshot interactive elements on the page as a numbered list."""
    js = """
    () => {
      const out = [];
      const selector = 'a, button, input, textarea, select, [role=button], [role=link], [role=tab], [role=menuitem]';
      const nodes = Array.from(document.querySelectorAll(selector));
      let i = 0;
      for (const el of nodes) {
        const rect = el.getBoundingClientRect();
        if (rect.width < 2 || rect.height < 2) continue;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none') continue;
        const tag = el.tagName.toLowerCase();
        const text = (el.innerText || el.value || el.placeholder || el.ariaLabel || '').trim().slice(0, 80);
        const type = el.getAttribute('type') || el.getAttribute('role') || tag;
        out.push({
          ref: i,
          tag: tag,
          type: type,
          text: text,
          name: el.getAttribute('name') || null,
          placeholder: el.getAttribute('placeholder') || null,
          aria: el.getAttribute('aria-label') || null,
          href: el.getAttribute('href') || null,
        });
        i++;
        if (i >= """ + str(limit) + """) break;
      }
      // Plus visible non-interactive headings to give the LLM context
      const headings = Array.from(document.querySelectorAll('h1, h2, h3')).slice(0, 6).map(h => ({
        ref: -1, tag: h.tagName.toLowerCase(), text: (h.innerText || '').trim().slice(0, 120)
      }));
      return { interactive: out, headings: headings, bodyText: document.body.innerText.slice(0, 1200) };
    }
    """
    data = page.evaluate(js)
    return data


def _click(page, elements: dict[str, Any], ref: int) -> None:
    el = _find_ref(elements, ref)
    selector = _selector_for(el)
    page.locator(selector).first.click(timeout=4000)


def _type(page, elements: dict[str, Any], ref: int, text: str) -> None:
    el = _find_ref(elements, ref)
    selector = _selector_for(el)
    locator = page.locator(selector).first
    locator.fill(text, timeout=4000)


def _find_ref(elements: dict[str, Any], ref: int) -> dict[str, Any]:
    for el in elements.get("interactive", []):
        if el["ref"] == ref:
            return el
    raise ValueError(f"element ref {ref} not found")


def _selector_for(el: dict[str, Any]) -> str:
    if el.get("name"):
        return f"{el['tag']}[name='{el['name']}']"
    if el.get("placeholder"):
        return f"{el['tag']}[placeholder='{_escape(el['placeholder'])}']"
    if el.get("aria"):
        return f"[aria-label='{_escape(el['aria'])}']"
    if el.get("href"):
        return f"{el['tag']}[href='{_escape(el['href'])}']"
    if el.get("text"):
        text = _escape(el["text"])
        return f"{el['tag']}:has-text(\"{text[:60]}\")"
    return el["tag"]


def _escape(s: str) -> str:
    return re.sub(r"['\"]", "", s)


# Grounding floors: a page must clear one of these to count as "real content".
_MIN_BODY_CHARS = 150
_MIN_INTERACTIVE = 5

# Narrow markers that a page is still an auth/login wall (not merely a "Sign in"
# link in the nav of an otherwise-rich app). Combined with a password-field
# check so logged-in dashboards don't trip.
_AUTH_GATE_TEXT = re.compile(
    r"(please\s+)?(sign\s?in|log\s?in)\s+to\s+(continue|access|use)"
    r"|unauthoriz|401\b|403\s+forbidden|authentication\s+required"
    r"|enter\s+your\s+password|login\s+required",
    re.IGNORECASE,
)

# Broader markers used only to classify why a FAILED journey failed, so the
# scorer/dashboard can say "credential-walled" rather than "weak work".
_AUTH_OBSERVATION = re.compile(
    r"\b(auth|login|log\s?in|sign\s?in|credential|unauthoriz|password|oauth|sso|401|403)\b",
    re.IGNORECASE,
)

_INTERACTIVE_ACTIONS = {"click", "type", "press_enter", "goto"}


def _looks_auth_gated(elements: dict[str, Any]) -> bool:
    """Does the current page snapshot still look like a login / auth wall?"""
    has_password = any(
        (el.get("type") or "").lower() == "password"
        for el in elements.get("interactive", [])
    )
    text = (elements.get("bodyText") or "") + " " + " ".join(
        h.get("text", "") for h in elements.get("headings", [])
    )
    return has_password or bool(_AUTH_GATE_TEXT.search(text))


def _grounded_success(elements: dict[str, Any], records: list[StepRecord]) -> tuple[bool, str]:
    """Decide whether a claimed journey success is backed by real page evidence.

    Accept only if the agent actually interacted with the app AND the resulting
    page has meaningful, non-auth-gated content. Returns (ok, reason_if_not).
    """
    reasons: list[str] = []
    interacted = any(
        r.action.get("action") in _INTERACTIVE_ACTIONS and "errored" not in r.observation
        for r in records
    )
    if not interacted:
        reasons.append("no successful interactive action was performed")
    body_len = len((elements.get("bodyText") or "").strip())
    n_interactive = len(elements.get("interactive") or [])
    if body_len < _MIN_BODY_CHARS and n_interactive < _MIN_INTERACTIVE:
        reasons.append(
            f"page has thin content (text={body_len} chars, {n_interactive} elements)"
        )
    if _looks_auth_gated(elements):
        reasons.append("page still shows a login / auth gate")
    return (not reasons, "; ".join(reasons))


def _journey_blocked_by_auth(j: JourneyResult) -> bool:
    """A failed journey that failed because the live app is credential-walled."""
    if j.success:
        return False
    text = f"{j.final_observation or ''} {j.failure_reason or ''}"
    return bool(_AUTH_OBSERVATION.search(text))


def _launch_browser(pw, headless: bool):
    """Launch Chromium across Playwright binary layouts.

    Playwright >=1.55 splits the headless install into a separate
    `chromium_headless_shell` binary which is often missing on judge laptops
    when the install pre-dates the upgrade. We prefer the full Chromium
    binary (`channel='chromium'`) which is what `playwright install chromium`
    provisions, and fall back to the default headless shell only if that
    fails. Operators get a single actionable error from `verify` if both
    paths fail; we do not raise here.
    """
    try:
        return pw.chromium.launch(channel="chromium", headless=headless)
    except Exception as exc_channel:
        logger.info(
            "Chromium channel='chromium' launch failed (%s); trying default binary",
            exc_channel,
        )
    try:
        return pw.chromium.launch(headless=headless)
    except Exception as exc:
        logger.warning("Default Chromium launch also failed: %s", exc)
        return None


def _summarize(results: list[JourneyResult]) -> str:
    if not results:
        return "No journeys executed."
    n_ok = sum(1 for r in results if r.success)
    return f"{n_ok}/{len(results)} journeys succeeded."


def _render_evidence_clause(page_title: str | None, results: list[JourneyResult]) -> str:
    """Positive render facts the verifier observed when journeys failed but the
    page rendered. Built only from already-captured report data; asserts
    rendering, never journey success."""
    shots = sum(len(r.screenshots) for r in results)
    legs = "; ".join(
        f"'{r.journey_name}' reached step {r.steps_completed}/{r.total_steps}"
        + (f" ({r.final_observation[:80]})" if r.final_observation else "")
        for r in results
    )
    return (
        f"Live app reachable and rendered (title={page_title!r}; {shots} screenshots captured); "
        f"{legs}. No declared journey completed within step budget — the UI exists and renders "
        "but the end-to-end flow was not driven to its expected outcome. Treat UX/functional as "
        "observable-but-journey-incomplete (legible signal short of verified), not absent."
    )
