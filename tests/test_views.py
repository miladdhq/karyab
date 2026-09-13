from datetime import datetime, timedelta, timezone

from karyab.views import VIEWS, apply_view, view_counts

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _p(pid, *, value=60.0, seen_hours=1, budget=2_000_000, token=3,
       rejected=False, reasons=("base",), title="پروژه", draft=""):
    return {
        "project_id": pid, "value": value, "rejected": rejected, "token": token,
        "title": title, "min_budget": budget // 2, "max_budget": budget,
        "reasons": list(reasons), "draft": draft, "slug": f"s{pid}",
        "first_seen_at": (NOW - timedelta(hours=seen_hours)).isoformat(),
    }


def test_every_view_has_a_persian_label_and_a_description():
    for key, view in VIEWS.items():
        assert view["label"].strip(), key
        assert view["hint"].strip(), key


# --- all -------------------------------------------------------------------

def test_all_shows_everything_that_was_not_rejected():
    items = [_p(1), _p(2), _p(3, rejected=True)]
    assert [i["project_id"] for i in apply_view(items, "all", threshold=55.0, now=NOW)] == [1, 2]


def test_rejected_is_the_only_view_showing_rejects():
    items = [_p(1), _p(2, rejected=True)]
    assert [i["project_id"] for i in apply_view(items, "rejected", threshold=55.0, now=NOW)] == [2]


# --- candidates ------------------------------------------------------------

def test_candidates_are_only_those_above_the_threshold():
    items = [_p(1, value=70.0), _p(2, value=40.0)]
    got = apply_view(items, "candidates", threshold=55.0, now=NOW)
    assert [i["project_id"] for i in got] == [1]


def test_candidates_are_ordered_by_score():
    items = [_p(1, value=60.0), _p(2, value=90.0), _p(3, value=75.0)]
    got = apply_view(items, "candidates", threshold=55.0, now=NOW)
    assert [i["project_id"] for i in got] == [2, 3, 1]


# --- newest ----------------------------------------------------------------

def test_newest_is_ordered_by_when_it_was_first_seen():
    items = [_p(1, seen_hours=10), _p(2, seen_hours=1), _p(3, seen_hours=5)]
    got = apply_view(items, "newest", threshold=55.0, now=NOW)
    assert [i["project_id"] for i in got] == [2, 3, 1]


def test_newest_ignores_the_score_entirely():
    # Freshness is the whole point of this view: no public field says how many
    # people have already bid, so arriving early is the only edge there is.
    items = [_p(1, value=99.0, seen_hours=20), _p(2, value=20.0, seen_hours=1)]
    got = apply_view(items, "newest", threshold=55.0, now=NOW)
    assert got[0]["project_id"] == 2


def test_a_missing_timestamp_sorts_last_rather_than_crashing():
    broken = _p(1)
    broken["first_seen_at"] = None
    items = [broken, _p(2, seen_hours=9)]
    got = apply_view(items, "newest", threshold=55.0, now=NOW)
    assert [i["project_id"] for i in got] == [2, 1]


# --- bots: the user's strongest cluster ------------------------------------

def test_bots_view_selects_projects_matching_the_bot_terms():
    items = [
        _p(1, reasons=["skill match: bot, telegram bot"]),
        _p(2, reasons=["skill match: website, shop"]),
        _p(3, title="ساخت ربات تلگرام", reasons=["base"]),
    ]
    got = apply_view(items, "bots", threshold=55.0, now=NOW)
    assert {i["project_id"] for i in got} == {1, 3}


# --- money -----------------------------------------------------------------

def test_big_shows_the_largest_budgets_first():
    items = [_p(1, budget=1_000_000), _p(2, budget=50_000_000), _p(3, budget=9_000_000)]
    got = apply_view(items, "big", threshold=55.0, now=NOW)
    assert [i["project_id"] for i in got] == [2, 3, 1]


def test_cheap_tokens_prefers_the_least_expensive_bids():
    items = [_p(1, token=7), _p(2, token=2), _p(3, token=4)]
    got = apply_view(items, "cheap", threshold=55.0, now=NOW)
    assert [i["project_id"] for i in got] == [2, 3, 1]


# --- drafted ---------------------------------------------------------------

def test_drafted_shows_only_projects_with_a_written_proposal():
    items = [_p(1, draft="سلام"), _p(2), _p(3, draft="متن")]
    got = apply_view(items, "drafted", threshold=55.0, now=NOW)
    assert {i["project_id"] for i in got} == {1, 3}


# --- robustness ------------------------------------------------------------

def test_an_unknown_view_falls_back_to_all_rather_than_erroring():
    items = [_p(1), _p(2)]
    assert len(apply_view(items, "nonsense", threshold=55.0, now=NOW)) == 2


def test_counts_are_reported_for_every_view():
    items = [_p(1, value=70.0, draft="x"), _p(2, value=30.0), _p(3, rejected=True)]
    counts = view_counts(items, threshold=55.0, now=NOW)
    assert set(counts) == set(VIEWS)
    assert counts["all"] == 2
    assert counts["candidates"] == 1
    assert counts["rejected"] == 1
    assert counts["drafted"] == 1


def test_views_never_mutate_the_list_they_are_given():
    items = [_p(1, value=10.0), _p(2, value=90.0)]
    before = [i["project_id"] for i in items]
    apply_view(items, "candidates", threshold=55.0, now=NOW)
    apply_view(items, "newest", threshold=55.0, now=NOW)
    assert [i["project_id"] for i in items] == before


def test_the_drafted_view_needs_the_draft_attached_before_filtering():
    """Regression: drafts were attached after apply_view ran, so this view
    matched nothing no matter how many drafts existed."""
    rows = [_p(1), _p(2)]
    written = {1: {"text": "سلام", "source": "session"}}

    # wrong order — filter first, attach later
    late = apply_view(rows, "drafted", threshold=55.0, now=NOW)
    assert late == [], "without the draft attached the view is empty"

    # right order — attach, then filter
    for row in rows:
        d = written.get(row["project_id"])
        row["draft"] = d["text"] if d else ""
    assert [i["project_id"] for i in
            apply_view(rows, "drafted", threshold=55.0, now=NOW)] == [1]
