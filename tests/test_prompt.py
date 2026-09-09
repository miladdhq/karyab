from karyab.writer.prompt import (
    SYSTEM_RULES,
    build_brief,
    build_messages,
    parse_drafts,
)

PROJECT = {
    "project_id": 322128, "title": "ساخت ربات تلگرام فروشگاهی",
    "description": "نیاز به رباتی دارم که محصولات رو نشون بده و سفارش بگیره.",
    "min_budget": 1_000_000, "max_budget": 3_000_000, "token": 3,
    "value": 78.0, "reasons": ["skill match: bot, telegram bot"],
    "slug": "sakht-robot-abc",
}
VOICE = [
    {"text": "سلام وقت بخیر، میتونم همچین ربات تلگرامی رو با پایتون طراحی کنم. "
             "لطفا گفت و گو رو باز کنید.", "word_count": 20, "budget": 2_000_000,
     "project_title": "ربات تلگرام"},
    {"text": "درود، ربات هاتون رو روی سرور ران میکنم. در خدمتم.",
     "word_count": 10, "budget": 800_000, "project_title": "استقرار ربات"},
]


def test_the_brief_carries_what_a_writer_needs():
    brief = build_brief(PROJECT, VOICE)
    assert "ساخت ربات تلگرام فروشگاهی" in brief
    assert "محصولات رو نشون بده" in brief, "the client's own words must be present"
    assert "پایتون" in brief, "voice samples must be included"


def test_the_brief_never_leaks_the_budget_as_a_target():
    # Quoting a price correlates with losing; the writer must not be handed one
    # to anchor on.
    brief = build_brief(PROJECT, VOICE)
    assert "1,000,000" not in brief and "3,000,000" not in brief


def test_the_brief_states_the_measured_rules():
    brief = build_brief(PROJECT, VOICE)
    assert "32" in brief, "the measured median length must be stated"
    for phrase in ("گفت و گو", "invitation", "technology"):
        assert phrase.lower() in brief.lower(), phrase


def test_the_system_rules_forbid_the_machine_tells():
    lowered = SYSTEM_RULES.lower()
    for banned in ("markdown", "em-dash", "price"):
        assert banned in lowered, banned


def test_messages_put_stable_content_first_for_caching():
    # Prompt caching is a prefix match: the corpus and rules must precede the
    # per-project text, or every draft pays full price.
    msgs = build_messages(PROJECT, VOICE)
    joined = msgs[0]["content"][0]["text"]
    assert "پایتون" in joined, "voice corpus belongs in the cached prefix"
    assert msgs[0]["content"][0].get("cache_control"), "prefix must be marked cacheable"
    assert "ساخت ربات تلگرام فروشگاهی" in msgs[0]["content"][-1]["text"]
    assert "cache_control" not in msgs[0]["content"][-1], "volatile part must not be cached"


def test_parsing_drafts_reads_back_a_written_bundle():
    bundle = {"drafts": [{"project_id": 322128, "text": "سلام، با پایتون مینویسم."}]}
    assert parse_drafts(bundle) == {322128: "سلام، با پایتون مینویسم."}


def test_parsing_ignores_entries_without_usable_text():
    bundle = {"drafts": [
        {"project_id": 1, "text": "  "},
        {"project_id": 2, "text": "متن واقعی"},
        {"project_id": 3},
    ]}
    assert parse_drafts(bundle) == {2: "متن واقعی"}


def test_parsing_a_malformed_bundle_raises_rather_than_silently_dropping():
    import pytest
    for bad in ({}, {"drafts": "nope"}, {"drafts": [{"text": "x"}]}):
        with pytest.raises(ValueError):
            parse_drafts(bad)
