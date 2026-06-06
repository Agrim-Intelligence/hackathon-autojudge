import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from autojudge.trace.store import _leaderboard_filters


def _clauses(ph="?", include_anchors=False, app_types=None, verdict=None,
             status=None, has_live_url=None, finalist_only=False, search=None):
    return _leaderboard_filters(
        ph, include_anchors, app_types, verdict, status,
        has_live_url, finalist_only, search,
    )


def test_no_filters_only_anchor_clause():
    clauses, params = _clauses()
    assert clauses == ["s.is_anchor = 0"]
    assert params == []


def test_include_anchors_drops_anchor_clause():
    clauses, params = _clauses(include_anchors=True)
    assert "s.is_anchor = 0" not in clauses
    assert params == []


def test_verdict_single_value():
    clauses, params = _clauses(verdict=["shortlist"])
    verdict_clause = next(c for c in clauses if "verdict" in c.lower())
    assert "IN (?)" in verdict_clause
    assert params[-1] == "shortlist"


def test_verdict_multi_value():
    clauses, params = _clauses(verdict=["shortlist", "borderline"])
    verdict_clause = next(c for c in clauses if "verdict" in c.lower())
    assert "IN (?,?)" in verdict_clause
    assert "shortlist" in params
    assert "borderline" in params


def test_status_multi_value():
    clauses, params = _clauses(status=["scored", "failed"])
    status_clause = next(c for c in clauses if "s.status" in c)
    assert "IN (?,?)" in status_clause
    assert "scored" in params
    assert "failed" in params


def test_app_types_multi_value():
    clauses, params = _clauses(app_types=["web", "api"])
    app_clause = next(c for c in clauses if "app_type" in c)
    assert "IN (?,?)" in app_clause
    assert "web" in params
    assert "api" in params


def test_search_produces_like_clause():
    clauses, params = _clauses(search="alice")
    like_clause = next(c for c in clauses if "LIKE" in c)
    assert "LIKE ?" in like_clause
    assert "%alice%" in params


def test_all_filters_combined():
    clauses, params = _clauses(
        app_types=["web"],
        verdict=["shortlist", "borderline"],
        status=["scored"],
        search="bob",
    )
    # anchor clause + app_types + verdict + status + search = 5
    assert len(clauses) == 5
    # 1 app_type + 2 verdict + 1 status + 2 search = 6 params
    assert len(params) == 6


def test_postgres_placeholder():
    clauses, params = _clauses(ph="%s", verdict=["shortlist"])
    verdict_clause = next(c for c in clauses if "verdict" in c.lower())
    assert "IN (%s)" in verdict_clause


def test_has_live_url_true():
    clauses, params = _clauses(has_live_url=True)
    assert any("live_url IS NOT NULL" in c for c in clauses)
    assert params == []


def test_finalist_only():
    clauses, params = _clauses(finalist_only=True)
    assert any("shortlist_state" in c for c in clauses)
