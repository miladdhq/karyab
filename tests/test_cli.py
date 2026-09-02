import json
from pathlib import Path

import karyab.cli as cli
from karyab.cli import main, render_report
from karyab.store import Store


def _rows():
    return [
        {
            "project_id": 1,
            "stage": 2,
            "value": 78.0,
            "rejected": False,
            "reasons": ["base", "skill match: bot", "posted in the last 10 minutes"],
            "title": "ساخت ربات تلگرام فروشگاهی",
            "slug": "sakht-robot-abc",
            "min_budget": 1_000_000,
            "max_budget": 3_000_000,
            "token": 3,
            "category_id": 6,
            "first_seen_at": "2026-09-01T12:00:00+00:00",
            "scored_at": "2026-09-01T12:00:00+00:00",
        },
        {
            "project_id": 2,
            "stage": 1,
            "value": 0.0,
            "rejected": True,
            "reasons": ["category 2 is not in the allowlist [6]"],
            "title": "طراحی لوگو",
            "slug": "logo-xyz",
            "min_budget": 500_000,
            "max_budget": 2_000_000,
            "token": 2,
            "category_id": 2,
            "first_seen_at": "2026-09-01T12:00:00+00:00",
            "scored_at": "2026-09-01T12:00:00+00:00",
        },
    ]


def test_the_report_shows_candidates_with_their_reasons():
    text = render_report(_rows(), threshold=55.0, show_rejected=False)

    assert "ربات تلگرام" in text
    assert "78" in text
    assert "skill match: bot" in text
    assert "3 tokens" in text or "tokens: 3" in text


def test_rejected_projects_are_hidden_by_default_and_shown_on_request():
    hidden = render_report(_rows(), threshold=55.0, show_rejected=False)
    shown = render_report(_rows(), threshold=55.0, show_rejected=True)

    assert "طراحی لوگو" not in hidden
    assert "طراحی لوگو" in shown
    assert "not in the allowlist" in shown


def test_the_report_links_each_project():
    text = render_report(_rows(), threshold=55.0, show_rejected=False)
    assert "karlancer.com" in text
    assert "sakht-robot-abc" in text


def test_an_empty_report_says_so_rather_than_printing_nothing():
    text = render_report([], threshold=55.0, show_rejected=False)
    assert text.strip()


def test_init_writes_a_config_seeded_from_the_profile(tmp_path, capsys):
    cfg_path = tmp_path / "config.toml"
    profile = Path("docs/research/profile-65389.json")

    code = main(["init", "--config", str(cfg_path), "--profile", str(profile)])

    assert code == 0
    assert cfg_path.exists()
    body = cfg_path.read_text(encoding="utf-8")
    assert "[skills]" in body
    assert "categories_allow" in body

    from karyab.config import Config

    cfg = Config.load(cfg_path)
    assert cfg.skills, "the generated config must carry a skill vocabulary"
    assert cfg.categories_allow == (6,)


def test_init_refuses_to_clobber_an_existing_config(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("min_budget = 1\n", encoding="utf-8")
    profile = Path("docs/research/profile-65389.json")

    code = main(["init", "--config", str(cfg_path), "--profile", str(profile)])

    assert code != 0
    assert cfg_path.read_text(encoding="utf-8") == "min_budget = 1\n"


def test_vocab_prints_a_skills_table(tmp_path, capsys):
    code = main(["vocab", "--profile", "docs/research/profile-65389.json"])
    out = capsys.readouterr().out

    assert code == 0
    assert "[skills]" in out
    assert "bot" in out


def test_report_reads_the_database(tmp_path, capsys):
    from datetime import datetime, timezone

    from karyab.models import Project
    from karyab.store import Store

    db = tmp_path / "k.db"
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    project = Project.from_listing(
        {"id": 5, "url": "s", "title": "ربات", "category_id": 6, "max_budget": 2_000_000}
    )
    with Store(db) as store:
        store.first_seen(project, now)
        store.record_score(5, 1, 80.0, False, ["skill match: bot"], now)

    code = main(["report", "--db", str(db)])
    out = capsys.readouterr().out

    assert code == 0
    assert "ربات" in out


def test_cmd_scan_stores_projects_and_prints_a_report_without_the_network(
    tmp_path, monkeypatch, capsys, listing_page
):
    """cmd_scan is the only subcommand with no automated test; the full
    wiring has only ever been checked by one manual live run. KarlancerClient
    is monkeypatched with an in-process fake built from the same fixture
    data every other test uses, so this never touches the network."""

    class FakeKarlancerClient:
        """Stands in for KarlancerClient: no I/O, just the fixture data."""

        def __init__(self):
            self.detail_calls: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def search_projects(self, page: int = 1):
            return listing_page["data"]["data"] if page == 1 else []

        def project_detail(self, slug: str):
            # The config below (defaults, no skills) can never score a
            # listing above run_scan's detail-fetch cutoff, so stage two
            # must never be reached here.
            self.detail_calls.append(slug)
            raise AssertionError("stage two should not be reached in this test")

    monkeypatch.setattr(cli, "KarlancerClient", FakeKarlancerClient)

    db = tmp_path / "k.db"
    missing_config = tmp_path / "no-such-config.toml"  # falls back to Config.default()

    code = main(
        ["scan", "--config", str(missing_config), "--db", str(db), "--pages", "1"]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "Saw 24 projects" in out
    assert "fetched 0 details" in out

    with Store(db) as store:
        rows = store.latest_scores(limit=100)
    assert len(rows) == 24, "every seen project must be stored, rejects included"


def test_unknown_command_exits_nonzero(capsys):
    try:
        main(["nonsense"])
    except SystemExit as exc:
        assert exc.code != 0
