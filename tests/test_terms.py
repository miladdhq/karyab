from karyab.terms import TERM_PATTERNS, match_terms, term_regex


def test_an_english_term_matches_a_persian_title():
    # The whole reason this module exists.
    assert term_regex("bot").search("ساخت ربات تلگرام دانلودر")
    assert term_regex("website").search("طراحی سایت فروشگاهی")
    assert term_regex("react").search("پروژه برنامه نویسی ری اکت")


def test_an_english_term_still_matches_english_text():
    assert term_regex("react").search("React dashboard")
    assert term_regex("php").search("legacy PHP app")


def test_matching_is_case_insensitive():
    assert term_regex("php").search("PHP")


def test_word_boundaries_stop_false_positives():
    # "bot" must not fire on "bottom" or "robotics" written in English.
    assert not term_regex("bot").search("bottom of the page")


def test_an_unknown_term_falls_back_to_a_literal_match():
    assert term_regex("kubernetes").search("راه اندازی kubernetes")
    assert not term_regex("kubernetes").search("docker only")


def test_a_regex_metacharacter_in_a_user_term_is_escaped():
    # "next.js" is a known term, but an invented one with a dot must not
    # turn the dot into a wildcard.
    assert not term_regex("c++x").search("cxx")


def test_match_terms_returns_only_present_terms_with_weights():
    skills = {"bot": 1.0, "react": 0.8, "website": 0.5}
    found = match_terms("ساخت ربات تلگرام", skills)

    assert found == {"bot": 1.0}


def test_match_terms_finds_several_at_once():
    skills = {"bot": 1.0, "telegram bot": 0.9, "website": 0.5}
    found = match_terms("ربات تلگرام برای سایت فروشگاهی", skills)

    assert set(found) == {"bot", "telegram bot", "website"}


def test_match_terms_on_empty_input_is_empty():
    assert match_terms("", {"bot": 1.0}) == {}
    assert match_terms("ربات", {}) == {}


def test_every_pattern_compiles():
    import re

    for pattern in TERM_PATTERNS.values():
        re.compile(pattern)
