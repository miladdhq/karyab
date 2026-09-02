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
