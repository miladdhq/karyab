from dataclasses import replace

from karyab.config import Config
from karyab.models import Project
from karyab.scoring.stage1 import score_listing
from karyab.scoring.types import Reason, Score

CFG = replace(
    Config.default(),
    skills={"bot": 1.0, "telegram bot": 0.9, "react": 0.7, "website": 0.5},
)


def _p(**over) -> Project:
    base = {
        "id": 1,
        "url": "slug",
        "title": "ساخت ربات تلگرام دانلودر",
        "description": "",
        "min_budget": 1_000_000,
        "max_budget": 2_000_000,
        "category_id": 6,
        "skills": [],
        "token": 3,
        "low_hire": False,
    }
    base.update(over)
    return Project.from_listing(base)


def test_a_matching_project_scores_well():
    score = score_listing(_p(), CFG)
    assert not score.rejected
    assert score.value > 60


def test_score_is_clamped_to_the_zero_hundred_range():
    score = score_listing(
        _p(title="ربات تلگرام react website", is_urgent=True, is_highlight=True), CFG
    )
    assert 0.0 <= score.value <= 100.0


def test_wrong_category_is_a_hard_reject_with_a_readable_reason():
    score = score_listing(_p(category_id=2), CFG)
    assert score.rejected
    assert any("category" in label.lower() for label in score.labels)


def test_a_blocked_category_is_rejected_even_when_allowed():
    cfg = replace(CFG, categories_allow=(2, 6), categories_block=(2,))
    assert score_listing(_p(category_id=2), cfg).rejected


def test_an_empty_allowlist_permits_every_category():
    cfg = replace(CFG, categories_allow=())
    assert not score_listing(_p(category_id=11), cfg).rejected


def test_a_budget_ceiling_below_the_floor_is_rejected():
    score = score_listing(_p(min_budget=50_000, max_budget=200_000), CFG)
    assert score.rejected
    assert any("budget" in label.lower() for label in score.labels)


def test_an_unknown_budget_is_penalised_not_rejected():
    score = score_listing(_p(min_budget=0, max_budget=0), CFG)
    assert not score.rejected
    assert any("budget" in label.lower() for label in score.labels)


def test_a_project_costing_more_tokens_than_configured_is_rejected():
    cfg = replace(CFG, max_token_cost=4)
    assert score_listing(_p(token=7), cfg).rejected
    assert not score_listing(_p(token=4), cfg).rejected


def test_an_expired_project_is_rejected():
    assert score_listing(_p(is_expired=True), CFG).rejected


def test_no_skill_overlap_is_a_low_score_not_a_rejection():
    score = score_listing(_p(title="ترجمه متن انگلیسی", description=""), CFG)
    assert not score.rejected, "near-misses must stay visible for tuning"
    assert score.value < CFG.threshold
    assert any("skill" in label.lower() for label in score.labels)


def test_the_no_skill_penalty_is_pinned():
    # A saturated skill match (matched weight >= SKILL_SATURATION) always
    # earns the full SKILL_MAX bonus regardless of exactly which terms hit,
    # so holding every other component identical between the two projects
    # isolates precisely the gap NO_SKILL_PENALTY is responsible for. If
    # NO_SKILL_PENALTY were weakened toward 0.0, this gap would shrink and
    # the assertion below would catch it.
    matched = _p(
        title="یک پروژه",
        description="",
        skills=[
            {"id": 1, "name": "bot"},
            {"id": 2, "name": "telegram bot"},
            {"id": 3, "name": "react"},
            {"id": 4, "name": "website"},
        ],
    )
    unmatched = _p(title="ترجمه متن انگلیسی", description="", skills=[])

    with_match = score_listing(matched, CFG)
    without_match = score_listing(unmatched, CFG)

    assert any("skill match" in l for l in with_match.labels)
    assert any("no skill term matched" in l for l in without_match.labels)
    # SKILL_MAX (55.0, saturated) minus NO_SKILL_PENALTY (-15.0) is 70.0.
    assert with_match.value - without_match.value == 70.0


def test_an_english_vocabulary_term_matches_a_persian_title():
    # The vocabulary is keyed on English terms; the projects are Persian.
    # A substring matcher would score this zero.
    score = score_listing(_p(title="ساخت ربات تلگرام دانلودر"), CFG)
    assert any("skill match" in l for l in score.labels)
    assert score.value > 60


def test_skills_match_against_the_skills_array_too():
    bare = _p(title="یک پروژه", skills=[])
    tagged = _p(title="یک پروژه", skills=[{"id": 1, "name": "react"}])
    assert score_listing(tagged, CFG).value > score_listing(bare, CFG).value


def test_the_sweet_spot_band_adds_a_bonus_and_can_be_disabled():
    inside = _p(min_budget=800_000, max_budget=2_000_000)
    outside = _p(min_budget=20_000_000, max_budget=35_000_000)

    on = score_listing(inside, CFG).value - score_listing(outside, CFG).value
    off_cfg = replace(CFG, sweet_spot_enabled=False)
    off = score_listing(inside, off_cfg).value - score_listing(outside, off_cfg).value

    assert on > off
    assert any("sweet spot" in l.lower() for l in score_listing(inside, CFG).labels)


def test_a_large_project_outside_the_band_is_still_biddable():
    score = score_listing(_p(min_budget=20_000_000, max_budget=35_000_000), CFG)
    assert not score.rejected, "the band is a bonus, never a cap"


def test_low_hire_costs_points_but_unknown_does_not():
    weak = score_listing(_p(low_hire=True), CFG).value
    unknown = score_listing(_p(low_hire=None), CFG).value
    fine = score_listing(_p(low_hire=False), CFG).value

    assert weak < fine
    assert unknown == fine


def test_urgent_and_highlighted_projects_gain_points():
    plain = score_listing(_p(), CFG).value
    urgent = score_listing(_p(is_urgent=True), CFG).value
    assert urgent > plain


def test_every_reason_carries_a_human_readable_label():
    score = score_listing(_p(), CFG)
    assert score.reasons
    for reason in score.reasons:
        assert reason.label.strip()


def test_score_with_extra_reclamps_and_appends():
    score = Score(value=95.0, reasons=(Reason("base", 95.0),))
    grown = score.with_extra([Reason("bonus", 20.0)])

    assert grown.value == 100.0
    assert len(grown.reasons) == 2
    assert score.value == 95.0, "Score must be immutable"
