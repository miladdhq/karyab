import json

import httpx
import pytest

from karyab.api import ApiError, KarlancerClient


def _client(handler) -> KarlancerClient:
    return KarlancerClient(transport=httpx.MockTransport(handler))


def test_search_projects_returns_the_inner_row_list(listing_page):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=listing_page)

    with _client(handler) as client:
        rows = client.search_projects(page=3)

    assert len(rows) == 24
    assert rows[0]["id"] == 322128
    assert "page=3" in seen["url"]
    assert seen["url"].startswith("https://www.karlancer.com/api/publics/search/projects")


def test_search_sends_a_browser_user_agent_and_accepts_json():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(200, json={"status": "success", "data": {"data": []}})

    with _client(handler) as client:
        client.search_projects()

    assert "Mozilla" in captured["user-agent"]
    assert captured["accept"] == "application/json"


def test_project_detail_unwraps_the_envelope(detail_raw):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/publics/projects/" in str(request.url)
        return httpx.Response(200, json=detail_raw)

    with _client(handler) as client:
        payload = client.project_detail("some-slug-abc123")

    assert payload["id"] == 322126


def test_a_persian_slug_is_url_encoded():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"status": "success", "data": {"id": 1}})

    with _client(handler) as client:
        client.project_detail("طراحی-سایت-abc")

    assert " " not in seen["url"]
    assert "%D8" in seen["url"]


def test_http_error_raises_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with _client(handler) as client:
        with pytest.raises(ApiError) as exc:
            client.search_projects()

    assert "500" in str(exc.value)


def test_a_failed_status_envelope_raises_with_the_server_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "failed", "data": None, "error": "وب سرویس مورد نظر وجود ندارد."},
        )

    with _client(handler) as client:
        with pytest.raises(ApiError) as exc:
            client.project_detail("missing")

    assert "وب سرویس" in str(exc.value)


def test_non_json_body_raises_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with _client(handler) as client:
        with pytest.raises(ApiError):
            client.search_projects()
