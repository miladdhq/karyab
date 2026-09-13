"""`karyab profile` — fetch the user's own public profile so init can use it."""

import json

import httpx
import pytest

from karyab.profile import consolidate, parse_profile_ref


# --- accepting whatever the user pastes -------------------------------------

def test_a_bare_id_is_accepted():
    assert parse_profile_ref("65389") == 65389


def test_a_full_profile_url_is_accepted():
    assert parse_profile_ref("https://www.karlancer.com/profile/65389") == 65389
    assert parse_profile_ref("karlancer.com/profile/65389/") == 65389


def test_garbage_is_refused_with_a_reason():
    for bad in ("", "hello", "https://example.com/x", "profile/"):
        with pytest.raises(ValueError):
            parse_profile_ref(bad)


# --- consolidating the paginated response ----------------------------------

def _page(n, last, projects=(), reviews=(), samples=()):
    def pag(rows):
        return {"current_page": n, "last_page": last, "data": list(rows)}
    return {"status": "success", "data": {
        "id": 1, "username": "x", "skills": [{"id": 1, "name": "react"}],
        "description": "d", "rate": 4.5, "rate_num": 2, "success_rate": 90,
        "completed_projects": pag(projects), "reviews_pg": pag(reviews),
        "worksamples": pag(samples),
    }}


def test_pages_are_walked_and_projects_deduplicated():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        calls.append(page)
        rows = {1: [{"project_id": 10, "title": "a", "budget": 1, "rate": 5}],
                2: [{"project_id": 11, "title": "b", "budget": 2, "rate": 5},
                    {"project_id": 10, "title": "a", "budget": 1, "rate": 5}]}[page]
        return httpx.Response(200, json=_page(page, 2, projects=rows))

    out = consolidate(httpx.MockTransport(handler), 1, sleep=lambda s: None)

    assert calls == [1, 2]
    assert {p["project_id"] for p in out["completed_projects"]} == {10, 11}
    assert out["profile"]["skills"][0]["name"] == "react"


def test_output_has_the_shape_the_vocabulary_generator_expects():
    def handler(request):
        return httpx.Response(200, json=_page(1, 1,
            projects=[{"project_id": 1, "title": "ربات", "budget": 5, "rate": 5}]))

    out = consolidate(httpx.MockTransport(handler), 1, sleep=lambda s: None)
    from karyab.vocab import build_vocabulary
    terms = build_vocabulary(out)
    assert any(t.term == "bot" for t in terms)


def test_a_failed_first_page_raises_a_readable_error():
    def handler(request):
        return httpx.Response(200, json={"status": "failed", "data": None,
                                         "error": "کاربر یافت نشد."})
    with pytest.raises(RuntimeError) as exc:
        consolidate(httpx.MockTransport(handler), 999999, sleep=lambda s: None)
    assert "یافت نشد" in str(exc.value) or "999999" in str(exc.value)


def test_a_failed_later_page_keeps_what_was_fetched():
    def handler(request):
        page = int(request.url.params.get("page", "1"))
        if page == 2:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=_page(1, 3,
            projects=[{"project_id": 1, "title": "a", "budget": 1, "rate": 5}]))

    out = consolidate(httpx.MockTransport(handler), 1, sleep=lambda s: None)
    assert len(out["completed_projects"]) == 1
    assert out["warnings"], "the dropped page must be reported, not hidden"
