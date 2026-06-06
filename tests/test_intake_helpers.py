import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
# Mock streamlit before importing form (form.py runs st.set_page_config at import time in some versions)
import unittest.mock as mock
import types
_st = types.ModuleType("streamlit")
_st.set_page_config = lambda **kw: None
sys.modules.setdefault("streamlit", _st)

from autojudge.intake.form import _parse_endpoints, _parse_journeys
from autojudge.models import ApiEndpoint, DeclaredJourney


# ---------------------------------------------------------------------------
# _parse_endpoints
# ---------------------------------------------------------------------------

def test_parse_endpoints_basic():
    result = _parse_endpoints("GET /api/health 200\nPOST /api/submit")
    assert len(result) == 2
    assert result[0].method == "GET"
    assert result[0].path == "/api/health"
    assert result[0].expected_status == 200
    assert result[1].method == "POST"
    assert result[1].path == "/api/submit"
    assert result[1].expected_status is None


def test_parse_endpoints_no_verb_defaults_to_get():
    # Unrecognised leading token treated as path; method defaults to GET
    result = _parse_endpoints("invalid line")
    assert len(result) == 1
    assert result[0].method == "GET"
    assert result[0].path == "invalid"


def test_parse_endpoints_empty():
    assert _parse_endpoints("") == []


def test_parse_endpoints_just_verb_no_path():
    # "INVALID" matches the verb regex? No — INVALID is not in the verb set.
    # After pop(0) toks is empty only if the line has a single token that IS
    # a verb. Let's test with a valid verb alone.
    result = _parse_endpoints("GET")
    assert result == []


def test_parse_endpoints_blank_lines_skipped():
    text = "GET /a\n\nPOST /b\n\n"
    result = _parse_endpoints(text)
    assert len(result) == 2
    assert result[0].path == "/a"
    assert result[1].path == "/b"


# ---------------------------------------------------------------------------
# _parse_journeys
# ---------------------------------------------------------------------------

def test_parse_journeys_two_blocks():
    text = "Login flow\nOpen /login\nEnter credentials\nClick submit\n\nSearch flow\nGo to /search\nType query"
    result = _parse_journeys(text)
    assert len(result) == 2
    assert result[0].name == "Login flow"
    assert result[0].steps == ["Open /login", "Enter credentials", "Click submit"]
    assert result[1].name == "Search flow"
    assert result[1].steps == ["Go to /search", "Type query"]


def test_parse_journeys_single_block():
    text = "Single journey\nStep one\nStep two"
    result = _parse_journeys(text)
    assert len(result) == 1
    assert result[0].name == "Single journey"
    assert result[0].steps == ["Step one", "Step two"]


def test_parse_journeys_empty():
    assert _parse_journeys("") == []


def test_parse_journeys_single_line_no_steps():
    result = _parse_journeys("Just a name")
    assert len(result) == 1
    assert result[0].name == "Just a name"
    assert result[0].steps == []


def test_parse_journeys_extra_blank_lines():
    text = "Block one\nStep A\n\n\n\nBlock two\nStep B"
    result = _parse_journeys(text)
    assert len(result) == 2
    assert result[0].name == "Block one"
    assert result[1].name == "Block two"
