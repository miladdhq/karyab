from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from karyab.api import ApiError
from karyab.config import Config
from karyab.scan import run_scan
from karyab.store import Store

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

CFG = replace(
    Config.default(),
    skills={"bot": 1.0, "react": 0.8, "website": 0.6, "server": 0.5},
)


class FakeClient:
    """Stands in for KarlancerClient without touching the network."""

    def __init__(self, pages, detail=None, detail_error=False):
        self.pages = pages
        self._detail = detail or {}
        self.detail_error = detail_error
        self.detail_calls = []
        self.page_calls = []

    def search_projects(self, page: int = 1):
        self.page_calls.append(page)
        return self.pages.get(page, [])

    def project_detail(self, slug: str):
        self.detail_calls.append(slug)
        if self.detail_error:
            raise ApiError("detail exploded")
        return dict(self._detail, url=slug)


def test_a_scan_stores_every_project_it_sees(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows})

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=1)
        stored = store.latest_scores(limit=100)

    assert result.seen == 24
    assert result.new == 24
    assert len(stored) == 24, "rejects are stored too, not discarded"


def test_rescanning_the_same_page_finds_nothing_new(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows})

    with Store(tmp_path / "k.db") as store:
        run_scan(client, store, CFG, now=NOW, pages=1)
        again = run_scan(client, store, CFG, now=NOW + timedelta(minutes=5), pages=1)

    assert again.seen == 24
    assert again.new == 0


def test_off_category_projects_are_rejected_with_reasons(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows})

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=1)
        stored = store.latest_scores(limit=100)

    assert result.rejected > 0
    for row in stored:
        if row["rejected"]:
            assert row["reasons"], "a rejection must say why"


def test_detail_is_fetched_only_for_plausible_candidates(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows}, detail={"id": 1, "created_at": None, "files": []})

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=1)

    assert result.detail_fetches == len(client.detail_calls)
    assert result.detail_fetches < 24, "stage two must not run on every row"


def test_a_detail_failure_does_not_abort_the_scan(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows}, detail_error=True)

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=1)
        stored = store.latest_scores(limit=100)

    assert result.seen == 24
    assert result.errors, "the failure should be reported, not swallowed"
    assert len(stored) == 24


def test_an_unparsable_detail_does_not_abort_the_scan(tmp_path, listing_page):
    rows = listing_page["data"]["data"]

    class Explosive:
        """A detail payload that blows up wherever models.py tries to read it."""

        def __contains__(self, item):
            raise ValueError("not a real payload")

    class BadDetail(FakeClient):
        def project_detail(self, slug: str):
            self.detail_calls.append(slug)
            return Explosive()

    client = BadDetail({1: rows})

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=1)
        stored = store.latest_scores(limit=100)

    assert result.seen == 24
    assert result.errors, "the failure should be reported, not swallowed"
    assert len(stored) == 24, "the project must still be stored, on its stage-1 score"


def test_a_page_failure_is_reported_and_the_scan_continues(tmp_path, listing_page):
    rows = listing_page["data"]["data"]

    class Flaky(FakeClient):
        def search_projects(self, page: int = 1):
            if page == 1:
                raise ApiError("page one is down")
            return super().search_projects(page)

    client = Flaky({2: rows})

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=2)

    assert result.errors
    assert result.seen == 24


def test_multiple_pages_are_walked_in_order(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows[:12], 2: rows[12:]})

    with Store(tmp_path / "k.db") as store:
        run_scan(client, store, CFG, now=NOW, pages=2)

    assert client.page_calls == [1, 2]


def test_the_scan_sleeps_between_requests(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows[:2], 2: rows[2:4]}, detail={"id": 1, "files": []})
    slept = []

    with Store(tmp_path / "k.db") as store:
        run_scan(client, store, CFG, now=NOW, pages=2, sleep=slept.append)

    assert slept, "requests to karlancer.com must be paced"
    assert all(s > 0 for s in slept)


def test_promoted_projects_clear_the_threshold(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient(
        {1: rows},
        detail={"id": 1, "created_at": "2026-09-01T11:55:00.000000Z", "files": []},
    )

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=1)
        stored = store.latest_scores(limit=100)

    clearing = [r for r in stored if not r["rejected"] and r["value"] >= CFG.threshold]
    assert result.promoted == len(clearing)
