from dataclasses import replace
from datetime import datetime, timedelta, timezone

from karyab.config import Config
from karyab.models import Project, ProjectDetail
from karyab.scoring.stage2 import score_detail
from karyab.scoring.types import Reason, Score

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
CFG = Config.default()
BASE = Score(value=60.0, reasons=(Reason("base", 60.0),))

PROJECT = Project.from_listing(
    {"id": 1, "url": "s", "title": "t", "category_id": 6, "max_budget": 2_000_000}
)


def _detail(**over) -> ProjectDetail:
    kwargs = {
        "id": 1,
        "created_at": NOW - timedelta(minutes=5),
        "hire_deadline": NOW + timedelta(days=30),
        "file_count": 0,
        "description": "a" * 120,
    }
    kwargs.update(over)
    return ProjectDetail(**kwargs)


def _score(detail: ProjectDetail, *, now=NOW, first_seen=None) -> Score:
    return score_detail(
        BASE,
        PROJECT,
        detail,
        CFG,
        now=now,
        first_seen_at=first_seen or (now - timedelta(minutes=5)),
    )


def test_a_brand_new_project_gains_the_most():
    fresh = _score(_detail(created_at=NOW - timedelta(minutes=3)))
    older = _score(_detail(created_at=NOW - timedelta(hours=6)))
    assert fresh.value > older.value
    assert any("fresh" in l.lower() or "minute" in l.lower() for l in fresh.labels)


def test_a_stale_project_loses_points():
    stale = _score(_detail(created_at=NOW - timedelta(days=3)))
    assert stale.value < BASE.value


def test_freshness_falls_back_to_first_seen_when_created_at_is_missing():
    scored = _score(
        _detail(created_at=None),
        first_seen=NOW - timedelta(minutes=2),
    )
    assert scored.value > BASE.value


def test_the_persian_relative_string_is_never_consulted():
    # ProjectDetail has no past_time field at all; this is a guard against
    # anyone adding one and parsing it.
    assert not hasattr(_detail(), "past_time")


def test_an_attached_brief_is_a_bonus():
    with_files = _score(_detail(file_count=2))
    without = _score(_detail(file_count=0))
    assert with_files.value > without.value
    assert any("file" in l.lower() or "brief" in l.lower() for l in with_files.labels)


def test_a_detailed_description_beats_a_one_liner():
    detailed = _score(_detail(description="x" * 400))
    thin = _score(_detail(description="کمک"))
    assert detailed.value > thin.value


def test_an_imminent_hiring_deadline_costs_points():
    soon = _score(_detail(hire_deadline=NOW + timedelta(hours=12)))
    later = _score(_detail(hire_deadline=NOW + timedelta(days=20)))
    assert soon.value < later.value


def test_a_missing_deadline_is_neutral():
    none = _score(_detail(hire_deadline=None))
    later = _score(_detail(hire_deadline=NOW + timedelta(days=20)))
    assert none.value == later.value


def test_stage_two_keeps_the_stage_one_reasons():
    scored = _score(_detail())
    assert scored.reasons[0].label == "base"
    assert len(scored.reasons) > 1


def test_a_rejected_stage_one_score_stays_rejected():
    rejected = Score(value=0.0, reasons=(Reason("category blocked", 0.0, fatal=True),))
    scored = score_detail(
        rejected,
        PROJECT,
        _detail(),
        CFG,
        now=NOW,
        first_seen_at=NOW,
    )
    assert scored.rejected
    assert scored.value == 0.0


def test_naive_timestamps_do_not_crash_the_scorer():
    naive = _detail(created_at=datetime(2026, 9, 1, 11, 55))
    scored = _score(naive)
    assert 0.0 <= scored.value <= 100.0


def test_the_result_stays_within_range():
    scored = _score(_detail(created_at=NOW, file_count=9, description="y" * 5000))
    assert 0.0 <= scored.value <= 100.0


# --- freshness band boundaries -------------------------------------------
#
# A mutation test proved every band's *value* was pinned but no band's
# *edge* was: widening the 10-minute edge to 15, the 30-minute edge to 45,
# or IMMINENT_DEADLINE_HOURS from 72 to 200 all left the suite green. Each
# test below scores a project at exactly the edge and one second past it,
# and asserts the literal (hardcoded, not imported) point value on both
# sides -- so a shifted edge changes which value applies on the "past"
# side and the test catches it. Confirmed to fail when an edge is shifted;
# see the fix report.


def test_freshness_band_edge_10_minutes_is_pinned():
    at_edge = _score(_detail(created_at=NOW - timedelta(minutes=10)))
    past_edge = _score(_detail(created_at=NOW - timedelta(minutes=10, seconds=1)))
    assert at_edge.value == BASE.value + 15.0
    assert past_edge.value == BASE.value + 10.0


def test_freshness_band_edge_30_minutes_is_pinned():
    at_edge = _score(_detail(created_at=NOW - timedelta(minutes=30)))
    past_edge = _score(_detail(created_at=NOW - timedelta(minutes=30, seconds=1)))
    assert at_edge.value == BASE.value + 10.0
    assert past_edge.value == BASE.value + 4.0


def test_freshness_band_edge_120_minutes_is_pinned():
    at_edge = _score(_detail(created_at=NOW - timedelta(minutes=120)))
    past_edge = _score(_detail(created_at=NOW - timedelta(minutes=120, seconds=1)))
    assert at_edge.value == BASE.value + 4.0
    assert past_edge.value == BASE.value  # the 0.0-point band


def test_freshness_band_edge_720_minutes_is_pinned():
    at_edge = _score(_detail(created_at=NOW - timedelta(minutes=720)))
    past_edge = _score(_detail(created_at=NOW - timedelta(minutes=720, seconds=1)))
    assert at_edge.value == BASE.value  # the 0.0-point band
    assert past_edge.value == BASE.value - 10.0


def test_freshness_band_edge_2880_minutes_is_pinned():
    at_edge = _score(_detail(created_at=NOW - timedelta(minutes=2880)))
    past_edge = _score(_detail(created_at=NOW - timedelta(minutes=2880, seconds=1)))
    assert at_edge.value == BASE.value - 10.0
    assert past_edge.value == BASE.value - 20.0


def test_imminent_deadline_edge_72_hours_is_pinned():
    at_edge = _score(_detail(hire_deadline=NOW + timedelta(hours=72)))
    past_edge = _score(_detail(hire_deadline=NOW + timedelta(hours=72, seconds=1)))
    # Both use the default created_at (NOW - 5 minutes -> +15.0 freshness
    # points) and the default neutral description, so the only difference
    # between the two is whether the imminent-deadline penalty applied.
    assert at_edge.value == BASE.value + 15.0 - 8.0
    assert past_edge.value == BASE.value + 15.0


# --- description-length thresholds ----------------------------------------
#
# Same story as the freshness edges: THIN_DESCRIPTION (60) and
# LONG_DESCRIPTION (200) were unpinned. created_at=NOW pins the freshness
# contribution to a known +15.0 so the description's own contribution is
# isolated.


def test_thin_description_edge_60_chars_is_pinned():
    at_edge = _score(_detail(created_at=NOW, description="a" * 60))
    past_edge = _score(_detail(created_at=NOW, description="a" * 59))
    assert at_edge.value == BASE.value + 15.0  # neutral: no penalty at 60
    assert past_edge.value == BASE.value + 15.0 - 6.0  # thin-brief penalty


def test_long_description_edge_200_chars_is_pinned():
    at_edge = _score(_detail(created_at=NOW, description="a" * 200))
    past_edge = _score(_detail(created_at=NOW, description="a" * 199))
    assert at_edge.value == BASE.value + 15.0 + 4.0  # detailed-brief bonus
    assert past_edge.value == BASE.value + 15.0  # neutral: no bonus at 199
