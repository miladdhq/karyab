import json
from datetime import datetime, timezone

from karyab.harvest import fetch_bids, harvest
from karyab.store import Store

NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)
H = {"Accept": "application/json", "Authorization": "Bearer x"}


class FakeResponse:
    def __init__(self, status, payload=None, raises=False):
        self.status = status
        self._payload = payload
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("not json")
        return self._payload


class FakeRequest:
    """Stands in for Playwright's APIRequestContext."""

    def __init__(self, pages, fail_on=(), non_json=()):
        self.pages = pages
        self.fail_on = fail_on
        self.non_json = non_json
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append((url, headers))
        page = int(url.split("page=")[1])
        if page in self.fail_on:
            return FakeResponse(500)
        if page in self.non_json:
            return FakeResponse(200, raises=True)
        return FakeResponse(200, {
            "status": "success",
            "data": {"last_page": len(self.pages), "current_page": page,
                     "data": self.pages[page - 1]},
        })


def _bid(i, status="completed"):
    return {"id": i, "project_id": 100 + i, "budget": 1_000_000, "duration": 5,
            "status": status, "description": "سلام با react انجام میدم برای شما",
            "created_at": "2026-08-01T10:00:00.000000Z", "token": 3,
            "project": {"title": "t", "category_id": 6, "skills": []}}


def test_every_page_is_walked():
    req = FakeRequest([[_bid(1), _bid(2)], [_bid(3)]])
    rows, pages, errors = fetch_bids(req, H, sleep=lambda s: None)

    assert len(rows) == 3
    assert pages == 2
    assert errors == []


def test_requests_are_paced_between_pages():
    slept = []
    req = FakeRequest([[_bid(1)], [_bid(2)], [_bid(3)]])
    fetch_bids(req, H, sleep=slept.append)

    assert slept, "karlancer resets connections under parallel/rapid load"
    assert all(s > 0 for s in slept)


def test_the_auth_headers_are_sent_on_every_request():
    req = FakeRequest([[_bid(1)], [_bid(2)]])
    fetch_bids(req, H, sleep=lambda s: None)

    assert all(h == H for _, h in req.calls)


def test_a_failed_middle_page_is_reported_and_skipped():
    req = FakeRequest([[_bid(1)], [_bid(2)], [_bid(3)]], fail_on=(2,))
    rows, _, errors = fetch_bids(req, H, sleep=lambda s: None)

    assert len(rows) == 2
    assert errors and "page 2" in errors[0]


def test_a_non_json_page_does_not_abort_the_walk():
    req = FakeRequest([[_bid(1)], [_bid(2)], [_bid(3)]], non_json=(2,))
    rows, _, errors = fetch_bids(req, H, sleep=lambda s: None)

    assert len(rows) == 2
    assert errors


def test_a_failed_first_page_returns_nothing_with_a_reason():
    req = FakeRequest([[_bid(1)]], fail_on=(1,))
    rows, pages, errors = fetch_bids(req, H, sleep=lambda s: None)

    assert rows == [] and pages == 0 and errors


def test_max_pages_limits_the_walk():
    req = FakeRequest([[_bid(1)], [_bid(2)], [_bid(3)]])
    rows, pages, _ = fetch_bids(req, H, max_pages=2, sleep=lambda s: None)

    assert pages == 2
    assert len(rows) == 2


def test_harvest_stores_a_usable_corpus(tmp_path):
    req = FakeRequest([[_bid(1), _bid(2, "declined")], [_bid(3, "pending")]])
    with Store(tmp_path / "k.db") as store:
        result = harvest(req, H, store, NOW, sleep=lambda s: None)
        stats = store.voice_stats()

    assert result.fetched == 3
    assert result.stored == 3
    assert stats["won"] == 1
    assert stats["teachable"] == 1


def test_harvest_is_idempotent(tmp_path):
    req = FakeRequest([[_bid(1), _bid(2)]])
    with Store(tmp_path / "k.db") as store:
        harvest(req, H, store, NOW, sleep=lambda s: None)
        harvest(req, H, store, NOW, sleep=lambda s: None)
        assert store.voice_stats()["total"] == 2


def test_a_malformed_bid_does_not_stop_the_harvest(tmp_path):
    req = FakeRequest([[_bid(1), {"id": "not-a-dict-project", "project": 7}, _bid(3)]])
    with Store(tmp_path / "k.db") as store:
        result = harvest(req, H, store, NOW, sleep=lambda s: None)

    assert result.fetched == 3
    assert result.stored == 3, "a bid with an odd project still parses defensively"
