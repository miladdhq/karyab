import json

import pytest

from karyab.browser.authed import (
    AuthTokenMissing,
    bearer_header,
    extract_token,
)


def _state(items):
    return {"cookies": [], "origins": [
        {"origin": "https://www.karlancer.com", "localStorage": items}]}


def test_extract_token_reads_the_nested_access_token():
    state = _state([{"name": "auth-token", "value": json.dumps(
        {"token_type": "Bearer", "access_token": "3755630|abc", "refresh_token": ""})}])
    assert extract_token(state) == ("Bearer", "3755630|abc")


def test_a_missing_auth_token_entry_raises():
    with pytest.raises(AuthTokenMissing):
        extract_token(_state([{"name": "user.data", "value": "{}"}]))


def test_an_unparsable_auth_token_raises():
    with pytest.raises(AuthTokenMissing):
        extract_token(_state([{"name": "auth-token", "value": "not json"}]))


def test_a_bare_string_token_is_accepted():
    # Defensive: if the app ever stores the token unwrapped.
    state = _state([{"name": "auth-token", "value": "3755630|abc"}])
    assert extract_token(state) == ("Bearer", "3755630|abc")


def test_an_empty_access_token_raises():
    state = _state([{"name": "auth-token", "value": json.dumps({"access_token": ""})}])
    with pytest.raises(AuthTokenMissing):
        extract_token(state)


def test_bearer_header_sets_accept_json():
    # Without Accept: application/json the API returns the Angular shell as
    # HTTP 200 text/html — a silent wrong answer, not an error.
    headers = bearer_header(("Bearer", "tok"))
    assert headers["Accept"] == "application/json"
    assert headers["Authorization"] == "Bearer tok"


def test_bearer_header_never_double_prefixes():
    headers = bearer_header(("Bearer", "Bearer tok"))
    assert headers["Authorization"] == "Bearer tok"


def test_the_auth_probe_requires_json_not_merely_200():
    """Cookies alone return the Angular shell as HTTP 200 text/html.

    An earlier probe treated that as authenticated, so an expired session
    passed silently and every later call failed confusingly.
    """
    import inspect

    from karyab.browser import session

    src = inspect.getsource(session._context_is_authenticated)
    assert "json" in src, "the probe must check the content type"
    assert "bearer_header" in src, "the probe must send the bearer token"
