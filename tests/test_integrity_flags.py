import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# --- _classify_flags (inlined from dashboard/app.py to avoid streamlit import) ---

_WARN_FLAG_PREFIXES = ("future_timestamp:", "duplicate_artifact:", "prompt_injection_severity=")
_QUARANTINE_FLAG_PREFIX = "quarantine_cause:"


def _classify_flags(flags, verdict_effective):
    is_quarantine = verdict_effective == "quarantined" or any(
        f.startswith(_QUARANTINE_FLAG_PREFIX) for f in flags
    )
    warn = [f for f in flags if f.startswith(_WARN_FLAG_PREFIXES)]
    notes = [
        f for f in flags
        if not f.startswith(_QUARANTINE_FLAG_PREFIX) and not f.startswith(_WARN_FLAG_PREFIXES)
    ]
    return is_quarantine, warn, notes


def test_quarantine_verdict_forces_quarantine():
    is_q, warn, notes = _classify_flags([], "quarantined")
    assert is_q is True
    assert warn == []
    assert notes == []


def test_quarantine_cause_flag_forces_quarantine():
    flags = ["quarantine_cause: prompt injection severity 3"]
    is_q, warn, notes = _classify_flags(flags, "borderline")
    assert is_q is True
    assert warn == []
    assert notes == []


def test_future_timestamp_goes_to_warn():
    flags = ["future_timestamp: 2030-01-01"]
    is_q, warn, notes = _classify_flags(flags, "borderline")
    assert is_q is False
    assert len(warn) == 1
    assert warn[0].startswith("future_timestamp:")
    assert notes == []


def test_prompt_injection_severity_goes_to_warn():
    flags = ["prompt_injection_severity=2: ignore all instructions"]
    is_q, warn, notes = _classify_flags(flags, "borderline")
    assert is_q is False
    assert len(warn) == 1
    assert notes == []


def test_duplicate_artifact_goes_to_warn():
    flags = ["duplicate_artifact: readme.md identical to submission-123"]
    is_q, warn, notes = _classify_flags(flags, "borderline")
    assert is_q is False
    assert len(warn) == 1
    assert notes == []


def test_benign_flag_goes_to_notes():
    flags = ["No README at repo root."]
    is_q, warn, notes = _classify_flags(flags, "borderline")
    assert is_q is False
    assert warn == []
    assert len(notes) == 1


def test_empty_flags():
    is_q, warn, notes = _classify_flags([], "borderline")
    assert is_q is False
    assert warn == []
    assert notes == []


def test_mixed_flags_routed_correctly():
    flags = [
        "quarantine_cause: timeline cheat",
        "future_timestamp: 2030",
        "No visible test directory.",
    ]
    is_q, warn, notes = _classify_flags(flags, "borderline")
    assert is_q is True
    assert len(warn) == 1
    assert len(notes) == 1


# --- _filter_llm_integrity_flags from code_analyst ---

from autojudge.agents.code_analyst import _filter_llm_integrity_flags


def test_drops_large_codebase_bulk_import():
    flags = ["Large codebase (402K lines) suggests bulk import of pre-existing work"]
    assert _filter_llm_integrity_flags(flags) == []


def test_drops_single_contributor_substantial():
    flags = ["Single contributor for substantial 383KB codebase raises concern"]
    assert _filter_llm_integrity_flags(flags) == []


def test_drops_zero_commits_inside_window_restatement():
    flags = ["Zero commits inside hackathon window — possible pre-existing codebase"]
    assert _filter_llm_integrity_flags(flags) == []


def test_drops_commits_suggest():
    flags = ["Commits suggest predates the hackathon window"]
    assert _filter_llm_integrity_flags(flags) == []


def test_keeps_hardcoded_api_key():
    flags = ["Hardcoded API key found in config.py"]
    assert _filter_llm_integrity_flags(flags) == flags


def test_keeps_no_test_coverage():
    flags = ["No test coverage detected"]
    assert _filter_llm_integrity_flags(flags) == flags


def test_keeps_production_without_cicd():
    flags = ["Production deployment without CI/CD pipeline"]
    assert _filter_llm_integrity_flags(flags) == flags


def test_mixed_keeps_genuine_drops_speculative():
    flags = [
        "Large codebase (402K lines) suggests bulk import",
        "Hardcoded API key found in config.py",
        "Single contributor for substantial 10MB codebase",
        "No test coverage detected",
    ]
    result = _filter_llm_integrity_flags(flags)
    assert len(result) == 2
    assert "Hardcoded API key found in config.py" in result
    assert "No test coverage detected" in result
