from datetime import datetime, timezone

from karyab.harvest import Outcome, VoiceSample
from karyab.store import Store

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def _sample(bid_id=1, outcome=Outcome.WON, opening=True, text="سلام با react انجام میدم",
            title="ساخت اپ", skills=("react",), budget=2_000_000, words=5) -> VoiceSample:
    return VoiceSample(
        bid_id=bid_id, project_id=100 + bid_id, text=text, outcome=outcome,
        is_opening_pitch=opening, word_count=words, budget=budget, duration=7,
        token=3, created_at=NOW, project_title=title, category_id=6,
        project_skills=skills,
    )


def test_saving_and_reading_back_a_sample(tmp_path):
    with Store(tmp_path / "k.db") as store:
        store.save_voice_samples([_sample()], NOW)
        rows = store.voice_samples()

    assert len(rows) == 1
    assert rows[0]["bid_id"] == 1
    assert rows[0]["outcome"] == "won"
    assert rows[0]["is_opening_pitch"] is True
    assert rows[0]["project_skills"] == ["react"]


def test_reharvesting_updates_rather_than_duplicating(tmp_path):
    with Store(tmp_path / "k.db") as store:
        store.save_voice_samples([_sample(text="first")], NOW)
        store.save_voice_samples([_sample(text="second")], NOW)
        rows = store.voice_samples()

    assert len(rows) == 1, "bid_id is the identity; re-harvest must not duplicate"
    assert rows[0]["text"] == "second"


def test_teachable_returns_only_clean_winning_pitches(tmp_path):
    with Store(tmp_path / "k.db") as store:
        store.save_voice_samples([
            _sample(bid_id=1, outcome=Outcome.WON, opening=True),
            _sample(bid_id=2, outcome=Outcome.WON, opening=False),      # negotiated
            _sample(bid_id=3, outcome=Outcome.DECLINED, opening=True),  # lost
            _sample(bid_id=4, outcome=Outcome.PENDING, opening=True),   # unresolved
        ], NOW)
        rows = store.teachable_samples()

    assert [r["bid_id"] for r in rows] == [1]


def test_teachable_prefers_samples_matching_the_target_skills(tmp_path):
    with Store(tmp_path / "k.db") as store:
        store.save_voice_samples([
            _sample(bid_id=1, skills=("react",), title="سایت"),
            _sample(bid_id=2, skills=("bot", "telegram bot"), title="ربات تلگرام"),
            _sample(bid_id=3, skills=("php",), title="وردپرس"),
        ], NOW)
        rows = store.teachable_samples(match_skills=("bot",), limit=2)

    assert rows[0]["bid_id"] == 2, "the bot sample must rank first for a bot project"
    assert len(rows) == 2


def test_teachable_still_returns_samples_when_nothing_matches(tmp_path):
    with Store(tmp_path / "k.db") as store:
        store.save_voice_samples([_sample(bid_id=1, skills=("react",))], NOW)
        rows = store.teachable_samples(match_skills=("wireguard",), limit=3)

    assert len(rows) == 1, "an unmatched project still needs voice examples"


def test_harvest_stats_summarise_the_corpus(tmp_path):
    with Store(tmp_path / "k.db") as store:
        store.save_voice_samples([
            _sample(bid_id=1, outcome=Outcome.WON, opening=True, words=28),
            _sample(bid_id=2, outcome=Outcome.WON, opening=False, words=9),
            _sample(bid_id=3, outcome=Outcome.DECLINED, opening=True, words=39),
        ], NOW)
        stats = store.voice_stats()

    assert stats["total"] == 3
    assert stats["won"] == 2
    assert stats["teachable"] == 1
    assert stats["declined_pitches"] == 1
    assert stats["median_won_words"] == 28
