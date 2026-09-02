from datetime import datetime, timedelta, timezone

from karyab.models import Project
from karyab.store import Store

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _project(listing_raw: dict) -> Project:
    return Project.from_listing(listing_raw)


def test_first_seen_records_the_first_time_and_is_stable(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        first = store.first_seen(project, NOW)
        later = store.first_seen(project, NOW + timedelta(hours=3))

    assert first == NOW
    assert later == NOW, "a project's first_seen must never move"


def test_has_seen_reports_novelty(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        assert store.has_seen(project.id) is False
        store.first_seen(project, NOW)
        assert store.has_seen(project.id) is True


def test_the_project_row_keeps_enough_to_explain_a_decision(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        store.first_seen(project, NOW)
        rows = store.top_scores()

    assert rows == []  # nothing scored yet


def test_rejected_projects_are_stored_not_discarded(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        store.first_seen(project, NOW)
        store.record_score(
            project.id,
            stage=1,
            value=0.0,
            rejected=True,
            reasons=["category 2 not in allowlist"],
            now=NOW,
        )
        rows = store.top_scores()

    assert len(rows) == 1
    assert rows[0]["rejected"] is True
    assert rows[0]["reasons"] == ["category 2 not in allowlist"]
    assert rows[0]["title"] == project.title


def test_rescoring_replaces_the_previous_score_for_that_stage(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        store.first_seen(project, NOW)
        store.record_score(project.id, 1, 40.0, False, ["first"], NOW)
        store.record_score(project.id, 1, 72.0, False, ["second"], NOW)
        rows = store.top_scores()

    assert len(rows) == 1
    assert rows[0]["value"] == 72.0
    assert rows[0]["reasons"] == ["second"]


def test_both_stages_coexist_for_one_project(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        store.first_seen(project, NOW)
        store.record_score(project.id, 1, 60.0, False, ["stage one"], NOW)
        store.record_score(project.id, 2, 78.0, False, ["stage two"], NOW)
        rows = store.top_scores()

    assert {r["stage"] for r in rows} == {1, 2}


def test_reopening_the_database_keeps_everything(tmp_path, listing_raw):
    project = _project(listing_raw)
    path = tmp_path / "k.db"

    with Store(path) as store:
        store.first_seen(project, NOW)
        store.record_score(project.id, 1, 51.0, False, ["kept"], NOW)

    with Store(path) as store:
        rows = store.top_scores()

    assert len(rows) == 1
    assert rows[0]["value"] == 51.0


def test_the_parent_directory_is_created(tmp_path, listing_raw):
    path = tmp_path / "nested" / "deeper" / "k.db"

    with Store(path) as store:
        store.first_seen(_project(listing_raw), NOW)

    assert path.exists()
