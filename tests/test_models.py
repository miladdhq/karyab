from datetime import datetime, timezone

from karyab.models import Project, ProjectDetail, parse_timestamp


def test_project_parses_a_real_listing_record(listing_raw):
    project = Project.from_listing(listing_raw)

    assert project.id == 322128
    assert project.category_id == 2
    assert project.min_budget == 500_000
    assert project.max_budget == 2_000_000
    assert project.token == 2
    assert "طراحی لوگو" in project.skills
    assert project.is_urgent is False
    assert project.low_hire is False


def test_project_keeps_the_slug_for_the_detail_fetch(listing_raw):
    project = Project.from_listing(listing_raw)
    assert project.slug == listing_raw["url"]
    assert project.slug


def test_every_project_on_the_page_parses(listing_page):
    rows = listing_page["data"]["data"]
    projects = [Project.from_listing(row) for row in rows]

    assert len(projects) == 24
    assert all(p.id > 0 for p in projects)
    assert all(isinstance(p.skills, tuple) for p in projects)


def test_low_hire_null_becomes_none_not_false():
    project = Project.from_listing(
        {"id": 1, "url": "x", "title": "t", "low_hire": None}
    )
    assert project.low_hire is None


def test_missing_fields_fall_back_to_safe_defaults():
    project = Project.from_listing({"id": 7, "url": "slug", "title": "t"})

    assert project.min_budget == 0
    assert project.max_budget == 0
    assert project.skills == ()
    assert project.token == 0
    assert project.description == ""


def test_detail_parses_timestamps_and_counts_files(detail_raw):
    detail = ProjectDetail.from_detail(detail_raw)

    assert detail.id == 322126
    assert detail.created_at == datetime(2026, 8, 31, 16, 24, 15, tzinfo=timezone.utc)
    assert detail.hire_deadline is not None
    # The committed fixture's "files" array has 2 entries (1.png, 2.png).
    assert detail.file_count == 2


def test_parse_timestamp_handles_both_observed_shapes():
    utc = parse_timestamp("2026-08-31T16:24:15.000000Z")
    tehran = parse_timestamp("2026-10-01T20:09:48.000000+03:30")

    assert utc == datetime(2026, 8, 31, 16, 24, 15, tzinfo=timezone.utc)
    assert tehran is not None
    assert tehran.utcoffset().total_seconds() == 3.5 * 3600


def test_parse_timestamp_tolerates_missing_values():
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None
    assert parse_timestamp("not a date") is None
