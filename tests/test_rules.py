"""The gate must never reject work that actually got paid.

An earlier version enforced correlations as requirements and rejected 12 of
the user's 15 real winning proposals. These tests exist so that cannot recur.
"""

from karyab.writer.rules import (
    LENGTH_BAND,
    TARGET_WORDS,
    Violation,
    assess,
    validate,
)


def _ok() -> str:
    return ("سلام وقت بخیر، این ربات تلگرام رو با پایتون براتون مینویسم و "
            "روی سرور مستقر میکنم. لطفا گفت و گو رو باز کنید تا صحبت کنیم.")


def _codes(text: str) -> set[str]:
    return {v.code for v in validate(text)}


# --- hard rules: only things NO winning pitch does --------------------------

def test_a_good_draft_passes():
    assert validate(_ok()) == []


def test_markdown_is_blocked():
    assert "markdown" in _codes("سلام، **با react** انجام میدم. گفت و گو رو باز کنید.")


def test_a_bulleted_list_is_blocked():
    assert "markdown" in _codes("سلام با react:\n- مورد اول\n- مورد دوم\nگفت و گو رو باز کنید.")


def test_an_em_dash_is_blocked():
    assert "em_dash" in _codes("سلام — با react انجام میدم. گفت و گو رو باز کنید.")


def test_an_absurdly_long_draft_is_blocked():
    assert "too_long" in _codes("سلام با react " + " ".join(["کلمه"] * 200))


def test_a_stub_is_blocked():
    assert "too_short" in _codes("با react.")
    assert "too_short" in _codes("")


def test_the_hard_band_is_wide_enough_to_admit_real_winners():
    low, high = LENGTH_BAND
    # The longest real winning pitch is 133 words; the shortest is 13.
    assert low <= 13 and high >= 133


# --- soft signals must NOT block --------------------------------------------

def test_missing_an_invitation_does_not_block():
    # 8 of the user's 15 winning pitches contain no invitation.
    text = "سلام، این ربات تلگرام رو با پایتون براتون مینویسم و تحویل میدم."
    assert validate(text) == []
    assert any("invite" in w for w in assess(text).weaknesses)


def test_missing_a_technology_does_not_block():
    # 3 of 15 winning pitches name no technology.
    text = "سلام وقت بخیر، این پروژه رو براتون انجام میدم. لطفا گفت و گو رو باز کنید."
    assert validate(text) == []
    assert any("technology" in w for w in assess(text).weaknesses)


def test_quoting_a_price_does_not_block():
    # 2 of 15 winning pitches quote one.
    text = "سلام، با react انجام میدم، ۲ میلیون تومان. لطفا گفت و گو رو باز کنید."
    assert validate(text) == []
    assert any("price" in w for w in assess(text).weaknesses)


# --- scoring ----------------------------------------------------------------

def test_a_draft_with_both_strong_signals_scores_well():
    a = assess(_ok())
    assert a.is_strong
    assert len(a.strengths) >= 2


def test_a_draft_with_neither_signal_scores_poorly():
    a = assess("سلام، انجامش میدم براتون و زود تحویل میدم و راضی خواهید بود قطعا حتما")
    assert not a.is_strong
    assert len(a.weaknesses) >= 2


def test_an_invitation_outweighs_a_technology_mention():
    """The invitation is the stronger measured signal, so it must score higher."""
    invite_only = assess("سلام، این کار رو براتون انجام میدم. لطفا گفت و گو رو باز کنید عزیز")
    tech_only = assess("سلام، این کار رو با react و node براتون انجام میدم و تحویل میدم عزیز")
    assert invite_only.score > tech_only.score


def test_the_score_stays_in_range():
    for text in ("", _ok(), "x " * 300, "بهترین کیفیت و کمترین قیمت ۲ میلیون تومان"):
        assert 0 <= assess(text).score <= 100


def test_assess_reports_the_word_count():
    assert assess("یک دو سه").word_count == 3


def test_the_target_is_the_measured_median():
    assert TARGET_WORDS == 32


def test_a_violation_explains_itself():
    for v in validate("x"):
        assert isinstance(v, Violation) and v.code.strip() and v.message.strip()
