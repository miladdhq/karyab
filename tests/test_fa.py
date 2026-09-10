"""Reasons shown in the dashboard must read as Persian, not as machinery."""

import re

from karyab.fa import translate_reason, translate_reasons
from karyab.scoring import stage1, stage2

LATIN = re.compile(r"[A-Za-z]")


def test_a_plain_reason_is_translated():
    assert translate_reason("base") == "پایه"
    assert translate_reason("marked urgent") == "فوری"


def test_a_freshness_band_is_translated():
    assert translate_reason("posted in the last 12 hours") == "۱۲ ساعت گذشته"


def test_a_skill_match_keeps_the_terms_but_translates_the_label():
    # The terms are English on purpose: they are what the user types in the
    # config, so translating them would break the connection.
    got = translate_reason("skill match: bot, telegram bot")
    assert got.startswith("مهارت‌های مشترک:")
    assert "bot, telegram bot" in got


def test_numbers_inside_a_reason_become_persian_digits():
    got = translate_reason("inside the sweet spot band 500,000-3,500,000")
    assert "۵۰۰,۰۰۰" in got and "۳,۵۰۰,۰۰۰" in got
    assert not re.search(r"[0-9]", got)


def test_an_attachment_count_is_translated():
    assert translate_reason("client attached 2 file(s) to the brief") == \
        "کارفرما ۲ فایل پیوست کرده"


def test_a_rejection_reason_is_translated():
    assert "مجاز" in translate_reason("category 2 is not in the allowlist [6]")
    assert "ژتون" in translate_reason("costs 7 tokens, over the limit of 4")


def test_an_unknown_reason_passes_through_rather_than_vanishing():
    # Hiding a reason is worse than showing it in English.
    assert translate_reason("something new the scorer started saying") == \
        "something new the scorer started saying"


def test_empty_input_is_safe():
    assert translate_reason("") == ""
    assert translate_reason(None) == ""
    assert translate_reasons(None) == []


def test_every_reason_the_scorers_can_emit_has_a_translation():
    """A new scorer reason must not silently appear in English on the page."""
    sources = []
    for module in (stage1, stage2):
        import inspect
        sources.append(inspect.getsource(module))
    text = "\n".join(sources)

    # Reason labels are the string literals passed to Reason(...).
    literals = re.findall(r'Reason\(\s*\n?\s*"([^"]+)"', text)
    literals += re.findall(r'\(\d+(?:\.\d+)?,\s*-?\d+\.\d+,\s*"([^"]+)"\)', text)

    untranslated = []
    for literal in literals:
        # Skip f-string fragments; those are covered by the pattern tests.
        if "{" in literal:
            continue
        if LATIN.search(translate_reason(literal)):
            untranslated.append(literal)
    assert not untranslated, f"no Persian for: {untranslated}"
