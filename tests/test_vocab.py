import tomllib

from karyab.vocab import VocabTerm, build_vocabulary, to_toml


def test_bots_are_the_heaviest_term(profile_raw):
    terms = build_vocabulary(profile_raw)
    by_term = {t.term: t for t in terms}

    assert "bot" in by_term
    assert by_term["bot"].wins >= 10


def test_terms_are_ordered_by_weight_descending(profile_raw):
    terms = build_vocabulary(profile_raw)
    weights = [t.weight for t in terms]
    assert weights == sorted(weights, reverse=True)


def test_the_top_term_is_normalised_to_one(profile_raw):
    terms = build_vocabulary(profile_raw)
    assert terms[0].weight == 1.0
    assert all(0.0 < t.weight <= 1.0 for t in terms)


def test_proven_terms_carry_example_titles(profile_raw):
    terms = build_vocabulary(profile_raw)
    proven = [t for t in terms if t.proven]

    assert proven
    for term in proven:
        assert term.wins > 0
        assert term.examples
        assert all(isinstance(e, str) and e for e in term.examples)


def test_declared_but_unproven_skills_are_kept_at_a_floor_weight(profile_raw):
    terms = build_vocabulary(profile_raw)
    proven = [t for t in terms if t.proven]
    unproven = [t for t in terms if not t.proven]

    # express.js is declared on the profile but wins no project by name.
    # The floor is derived from the proven distribution (see build_vocabulary),
    # so the exact number varies with the data — what must always hold is
    # that every unproven term still sits strictly below every proven one.
    assert unproven, "declared skills with no wins should still be present"
    min_proven_weight = min(t.weight for t in proven)
    for term in unproven:
        assert term.wins == 0
        assert term.weight < min_proven_weight


def test_a_weak_evidence_proven_term_still_outranks_a_zero_evidence_declaration(profile_raw):
    # wireguard has real (if few) wins; express.js is only ever declared.
    # Demonstrated outcomes must outrank mere declaration however thin the
    # evidence -- this is the whole reason the vocabulary is built from
    # outcomes instead of the declared list, and it is exactly the
    # invariant a fixed unproven floor could silently violate.
    by_term = {t.term: t for t in build_vocabulary(profile_raw)}

    assert by_term["wireguard"].proven
    assert by_term["wireguard"].wins == 2
    assert not by_term["express.js"].proven
    assert by_term["express.js"].wins == 0
    assert by_term["wireguard"].weight > by_term["express.js"].weight


def test_the_floor_never_ties_a_proven_term_at_a_dominant_win_distribution():
    # A pathological but plausible distribution: one term with a large pile
    # of wins compresses every other proven weight toward the 2-decimal
    # grid's bottom rung (0.01). A floor that also lands on 0.01 ties an
    # evidence-free declared skill with a term that has real, if thin,
    # proof -- exactly the inversion this module exists to prevent. This
    # profile is synthetic (built here, not read from docs/research/) and
    # is shaped to land a proven term's weight at exactly 0.01 so the tie
    # would be reachable if the floor were also clamped to 0.01.
    profile = {
        "profile": {"skills": [{"name": "database"}]},
        "completed_projects": (
            [
                {"title": f"ساخت ربات تلگرام شماره {i}", "budget": 1_000_000, "rate": 5}
                for i in range(200)
            ]
            + [{"title": "کار با فیگما برای پروژه", "budget": 1_000_000, "rate": 5}]
        ),
    }

    terms = build_vocabulary(profile)
    by_term = {t.term: t for t in terms}

    # Confirm the pathological grid is actually hit: figma's weight rounds
    # to the bottom of the 2-decimal grid, which is what makes the old
    # 0.01-clamped floor collide with it.
    assert by_term["figma"].weight == 0.01

    proven = [t for t in terms if t.proven]
    unproven = [t for t in terms if not t.proven]
    assert unproven
    for u in unproven:
        for p in proven:
            assert u.weight < p.weight, (
                f"{u.term}={u.weight} does not sit strictly below "
                f"{p.term}={p.weight}"
            )


def test_a_one_star_win_counts_for_less_than_a_five_star_win():
    profile = {
        "profile": {"skills": []},
        "completed_projects": [
            {"title": "ساخت ربات تلگرام الف", "budget": 1_000_000, "rate": 5},
            {"title": "ساخت ربات تلگرام ب", "budget": 1_000_000, "rate": 5},
            {"title": "طراحی سایت الف", "budget": 1_000_000, "rate": 1},
            {"title": "طراحی سایت ب", "budget": 1_000_000, "rate": 1},
        ],
    }
    by_term = {t.term: t for t in build_vocabulary(profile)}

    assert by_term["telegram bot"].wins == 2
    assert by_term["website"].wins == 2
    assert by_term["telegram bot"].weight > by_term["website"].weight


def test_to_toml_round_trips_into_a_skills_table(profile_raw):
    terms = build_vocabulary(profile_raw)
    text = to_toml(terms)
    parsed = tomllib.loads(text)

    assert set(parsed) == {"skills"}
    assert parsed["skills"]
    for name, weight in parsed["skills"].items():
        assert isinstance(name, str)
        assert 0.0 < float(weight) <= 1.0


def test_to_toml_quotes_names_containing_dots():
    terms = [VocabTerm(term="next.js", weight=0.5, wins=1, proven=True, examples=("x",))]
    parsed = tomllib.loads(to_toml(terms))
    assert parsed["skills"]["next.js"] == 0.5


def test_an_empty_profile_produces_an_empty_vocabulary():
    assert build_vocabulary({"profile": {"skills": []}, "completed_projects": []}) == ()
