"""The gate is checked against the user's real corpus, not just fixtures.

These tests read the harvested voice corpus if it exists. They are the reason
the hard/soft split exists: an earlier gate rejected 12 of 15 real winners and
every unit test still passed.
"""

import os

import pytest

from karyab.store import Store
from karyab.writer.rules import assess, validate

DB = os.environ.get("KARYAB_CORPUS_DB", "/tmp/kh.db")
corpus = pytest.mark.skipif(
    not os.path.exists(DB), reason="no harvested corpus; run `karyab harvest`"
)


def _corpus():
    with Store(DB) as store:
        won = store.teachable_samples(limit=200)
        every = store.voice_samples(limit=10_000)
    declined = [r for r in every
                if r["outcome"] == "declined" and r["is_opening_pitch"]]
    return won, declined


@corpus
def test_no_real_winning_pitch_is_ever_blocked():
    won, _ = _corpus()
    assert won, "corpus present but empty"
    blocked = [(r["word_count"], [v.code for v in validate(r["text"])])
               for r in won if validate(r["text"])]
    assert blocked == [], (
        f"the gate rejects {len(blocked)} proposal(s) that actually won: {blocked}"
    )


@corpus
def test_the_soft_score_separates_wins_from_declines():
    won, declined = _corpus()
    if not declined:
        pytest.skip("no declined pitches in corpus")

    def median(rows):
        v = sorted(assess(r["text"]).score for r in rows)
        return v[len(v) // 2]

    assert median(won) > median(declined), (
        "the scoring signals no longer separate winning from declined pitches"
    )
