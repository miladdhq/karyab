import os
import stat

import pytest

from karyab.web.secrets import (
    ApiKeyInvalid,
    clear_api_key,
    load_api_key,
    mask_api_key,
    save_api_key,
)

GOOD = "sk-ant-api03-" + "x" * 80


def test_saving_then_loading_round_trips(tmp_path):
    path = tmp_path / "secrets.json"
    save_api_key(GOOD, path=path)
    assert load_api_key(path=path) == GOOD


def test_the_secrets_file_is_not_world_readable(tmp_path):
    path = tmp_path / "secrets.json"
    save_api_key(GOOD, path=path)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, f"an API key must never be group/world readable, got {oct(mode)}"


def test_the_key_is_never_stored_in_plain_view_of_the_repo(tmp_path):
    # Guard the location, not just the permissions.
    from karyab.web.secrets import default_secrets_path
    assert "dev/karyab" not in str(default_secrets_path())


def test_loading_when_nothing_is_saved_returns_none(tmp_path):
    assert load_api_key(path=tmp_path / "absent.json") is None


def test_an_obviously_wrong_key_is_rejected(tmp_path):
    path = tmp_path / "secrets.json"
    for bad in ("", "   ", "hello", "sk-1234", "ghp_" + "x" * 40):
        with pytest.raises(ApiKeyInvalid):
            save_api_key(bad, path=path)
    assert not path.exists(), "a rejected key must not create a file"


def test_surrounding_whitespace_is_stripped(tmp_path):
    path = tmp_path / "secrets.json"
    save_api_key(f"  {GOOD}\n", path=path)
    assert load_api_key(path=path) == GOOD


def test_clearing_removes_the_key(tmp_path):
    path = tmp_path / "secrets.json"
    save_api_key(GOOD, path=path)
    clear_api_key(path=path)
    assert load_api_key(path=path) is None


def test_clearing_when_absent_is_not_an_error(tmp_path):
    clear_api_key(path=tmp_path / "absent.json")


def test_masking_shows_enough_to_recognise_but_not_to_use():
    masked = mask_api_key(GOOD)
    assert masked.startswith("sk-ant-")
    assert masked.endswith(GOOD[-4:])
    assert "x" * 20 not in masked, "the body of the key must not be shown"
    assert len(masked) < 30


def test_masking_nothing_says_so():
    assert mask_api_key(None) == "not set"
    assert mask_api_key("") == "not set"


def test_a_saved_file_contains_no_other_secrets(tmp_path):
    path = tmp_path / "secrets.json"
    save_api_key(GOOD, path=path)
    import json
    assert set(json.loads(path.read_text())) == {"anthropic_api_key"}
