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


def test_profile_unwraps_the_envelope(profile_raw):
    # profile_raw (from conftest) is already the unwrapped "data" payload
    # -- exactly what profile() must hand back -- so the mock response
    # wraps it in the envelope client._get expects to strip.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": profile_raw})

    with _client(handler) as client:
        payload = client.profile(65389)

    assert payload == profile_raw
    assert "completed_projects" in payload


def test_profile_sends_the_page_query_parameter(profile_raw):
    """`?page=N` is how the profile's completed_projects, reviews_pg and
    worksamples sub-resources are walked -- Phase 2's harvest depends on it."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"status": "success", "data": profile_raw})

    with _client(handler) as client:
        client.profile(65389, page=3)

    assert "page=3" in seen["url"]
    assert seen["url"].startswith(
        "https://www.karlancer.com/api/publics/profile/65389"
    )


def test_profile_defaults_to_page_one(profile_raw):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"status": "success", "data": profile_raw})

    with _client(handler) as client:
        client.profile(65389)

    assert "page=1" in seen["url"]


def test_the_client_ignores_the_ambient_proxy_environment(monkeypatch):
    """karlancer.com is domestic; a user's SOCKS tunnel must never gate it.

    A shell that permanently exports ALL_PROXY=socks://127.0.0.1:PORT/ (a
    common V2Ray setup) makes httpx raise *during construction*, before any
    request is even sent, if the client trusts the environment -- socks://
    is not even a scheme httpx accepts, proxy extra or not.

    Deliberately no `transport=` is passed to KarlancerClient() here: in
    httpx, environment proxies are only consulted when the caller has not
    supplied a transport of their own (`allow_env_proxies = trust_env and
    transport is None`, in httpx.Client.__init__). That is exactly how
    `cmd_scan` constructs this client in production. A test that always
    passed a MockTransport at construction time would never exercise this
    bug at all -- it was tried and confirmed to pass even against the
    unfixed client.

    The transport is swapped in afterwards purely so the request below
    never touches the network; construction, not this swap, is what proves
    the fix.
    """
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:10808/")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10808/")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:10808/")

    client = KarlancerClient()  # must not raise despite the proxy env above

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": {"data": []}})

    client._client._transport = httpx.MockTransport(handler)

    with client:
        rows = client.search_projects()

    assert rows == []
