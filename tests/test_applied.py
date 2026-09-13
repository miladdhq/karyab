from datetime import datetime, timedelta, timezone

from karyab.models import Project
from karyab.store import Store

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _p(pid=1, token=3, title="ربات تلگرام"):
    return Project.from_listing({
        "id": pid, "url": f"slug-{pid}", "title": title, "category_id": 6,
        "min_budget": 1_000_000, "max_budget": 3_000_000, "token": token,
        "skills": [{"id": 1, "name": "bot"}],
    })


def _seed(store, *projects):
    for p in projects:
        store.first_seen(p, NOW)
        store.record_score(p.id, 1, 70.0, False, ["skill match: bot"], NOW)


def test_marking_a_project_applied_records_when_and_what_it_cost(tmp_path):
    with Store(tmp_path / "k.db") as store:
        _seed(store, _p(1, token=4))
        store.mark_applied(1, NOW)
        rows = store.applied()

    assert len(rows) == 1
    assert rows[0]["project_id"] == 1
    assert rows[0]["token"] == 4, "the token cost of the bid must be recorded"
    assert rows[0]["applied_at"] == NOW.isoformat()
    assert rows[0]["title"] == "ربات تلگرام"


def test_an_applied_project_leaves_the_review_queue(tmp_path):
    with Store(tmp_path / "k.db") as store:
        _seed(store, _p(1), _p(2))
        assert {r["project_id"] for r in store.top_scores()} == {1, 2}

        store.mark_applied(1, NOW)
        assert {r["project_id"] for r in store.top_scores()} == {2}


def test_the_applied_list_is_newest_first(tmp_path):
    with Store(tmp_path / "k.db") as store:
        _seed(store, _p(1), _p(2), _p(3))
        store.mark_applied(1, NOW)
        store.mark_applied(2, NOW + timedelta(hours=2))
        store.mark_applied(3, NOW + timedelta(hours=1))
        assert [r["project_id"] for r in store.applied()] == [2, 3, 1]


def test_unmarking_returns_a_project_to_the_queue(tmp_path):
    # Misclicks happen, and a wrongly hidden project is invisible forever.
    with Store(tmp_path / "k.db") as store:
        _seed(store, _p(1))
        store.mark_applied(1, NOW)
        assert store.top_scores() == []

        store.unmark_applied(1)
        assert [r["project_id"] for r in store.top_scores()] == [1]
        assert store.applied() == []


def test_marking_twice_does_not_duplicate_or_move_the_timestamp(tmp_path):
    with Store(tmp_path / "k.db") as store:
        _seed(store, _p(1))
        store.mark_applied(1, NOW)
        store.mark_applied(1, NOW + timedelta(days=1))
        rows = store.applied()

    assert len(rows) == 1
    assert rows[0]["applied_at"] == NOW.isoformat(), "the first application stands"


def test_the_applied_row_carries_the_draft_that_was_sent(tmp_path):
    with Store(tmp_path / "k.db") as store:
        _seed(store, _p(1))
        store.save_draft(1, "سلام، با پایتون انجام میدم. گفت و گو رو باز کنید.", NOW)
        store.mark_applied(1, NOW)
        rows = store.applied()

    assert "پایتون" in rows[0]["draft"], "what was sent must be recoverable later"


def test_spend_since_counts_only_recent_applications(tmp_path):
    with Store(tmp_path / "k.db") as store:
        _seed(store, _p(1, token=3), _p(2, token=5), _p(3, token=2))
        store.mark_applied(1, NOW - timedelta(days=2))
        store.mark_applied(2, NOW)
        store.mark_applied(3, NOW)

        assert store.spend_since(NOW - timedelta(hours=12)) == {"count": 2, "tokens": 7}
        assert store.spend_since(NOW - timedelta(days=7)) == {"count": 3, "tokens": 10}


def test_spend_on_an_empty_store_is_zero(tmp_path):
    with Store(tmp_path / "k.db") as store:
        assert store.spend_since(NOW) == {"count": 0, "tokens": 0}


def test_marking_an_unknown_project_does_not_crash(tmp_path):
    with Store(tmp_path / "k.db") as store:
        store.mark_applied(999, NOW)
        assert store.applied() == []
