import json

import pytest
from fastapi.testclient import TestClient

from karyab.web.app import create_app, is_loopback


@pytest.fixture()
def client(tmp_path, monkeypatch):
    secrets = tmp_path / "secrets.json"
    monkeypatch.setattr("karyab.web.secrets.default_secrets_path", lambda: secrets)
    return TestClient(create_app(str(tmp_path / "k.db"), config_path=tmp_path / "c.toml"))


# --- the bind guard: this process holds an API key and has no login ---------

def test_loopback_detection():
    assert is_loopback("127.0.0.1") and is_loopback("localhost") and is_loopback("::1")
    assert not is_loopback("0.0.0.0") and not is_loopback("192.168.1.5")


def test_serving_on_a_public_interface_is_refused_without_consent(tmp_path):
    from karyab.web.app import serve
    with pytest.raises(SystemExit) as exc:
        serve(str(tmp_path / "k.db"), host="0.0.0.0")
    assert "--i-know" in str(exc.value)


# --- the page ---------------------------------------------------------------

def test_the_page_renders_right_to_left(client):
    body = client.get("/").text
    assert 'dir="rtl"' in body and 'lang="fa"' in body


def test_an_empty_queue_says_what_to_run(client):
    assert "karyab scan" in client.get("/").text


# --- the draft gate is the same one the writer uses -------------------------

def test_checking_a_good_draft_returns_no_blockers(client):
    good = ("سلام وقت بخیر، این ربات تلگرام رو با پایتون براتون مینویسم و روی "
            "سرور مستقر میکنم. لطفا گفت و گو رو باز کنید تا صحبت کنیم.")
    d = client.post("/api/check", json={"text": good}).json()
    assert d["blocking"] == []
    assert d["assessment"]["score"] >= 70


def test_checking_a_draft_with_markdown_blocks_it(client):
    d = client.post("/api/check", json={"text": "سلام **react** گفت و گو رو باز کنید"}).json()
    assert any(v["code"] == "markdown" for v in d["blocking"])


def test_a_weak_but_legal_draft_is_not_blocked(client):
    # Missing an invitation is a weakness, never a blocker — 8 of the user's
    # 15 winning pitches have no invitation.
    text = "سلام، این ربات تلگرام رو با پایتون براتون مینویسم و تحویل میدم سریع."
    d = client.post("/api/check", json={"text": text}).json()
    assert d["blocking"] == []
    assert d["assessment"]["weaknesses"]


# --- API key handling -------------------------------------------------------

def test_the_key_is_never_returned_to_the_browser(client, tmp_path):
    key = "sk-ant-api03-" + "z" * 80
    client.post("/api/settings/api-key", json={"key": key})
    body = client.get("/api/settings").text
    assert key not in body
    assert "z" * 20 not in body
    assert json.loads(body)["api_key_masked"].endswith("zzzz")


def test_saving_a_malformed_key_is_rejected_with_a_reason(client):
    r = client.post("/api/settings/api-key", json={"key": "nope"})
    assert r.status_code == 400
    assert "sk-ant-" in r.json()["detail"]


def test_settings_reports_whether_a_key_is_set(client):
    assert client.get("/api/settings").json()["api_key_set"] is False
    client.post("/api/settings/api-key", json={"key": "sk-ant-api03-" + "q" * 80})
    assert client.get("/api/settings").json()["api_key_set"] is True


def test_deleting_the_key_clears_it(client):
    client.post("/api/settings/api-key", json={"key": "sk-ant-api03-" + "q" * 80})
    client.delete("/api/settings/api-key")
    assert client.get("/api/settings").json()["api_key_set"] is False


def test_testing_without_a_key_explains_rather_than_crashing(client):
    r = client.post("/api/settings/api-key/test")
    assert r.status_code == 400
    assert "key" in r.json()["detail"].lower()


# --- queue ------------------------------------------------------------------

def test_the_queue_endpoint_works_on_an_empty_database(client):
    d = client.get("/api/queue").json()
    assert d["items"] == []
    assert "threshold" in d and "daily_cap" in d
