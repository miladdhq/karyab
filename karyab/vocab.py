"""Derive the matcher's skill vocabulary from projects actually won.

The user's profile declares seven skills. Their 29 completed projects
contain 11 bots, 2 WireGuard panels, 2 Python jobs and a Next.js
deployment — none of which the declared list mentions. Matching on the
declared list would therefore ignore the largest cluster of work this
user actually wins, so the vocabulary is built from outcomes instead.

Persian titles do not tokenise usefully, so concepts are matched through
the shared pattern table in `karyab.terms` rather than by splitting words.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .terms import TERM_PATTERNS, term_regex

# A five-star win is full evidence; a one-star win is evidence the user can
# do the work but not that it goes well. Unrated sits between.
_OUTCOME_WEIGHT = {5: 1.0, 1: 0.4}
_UNRATED_WEIGHT = 0.8

# Fallback floor for declared-but-unproven skills, used only when there is
# no proven evidence at all to derive a floor from (an empty win record).
# Whenever proven terms exist, build_vocabulary derives the floor from
# their own distribution instead, so a term with real (if thin) evidence
# can never be outranked by a term with none.
_NO_EVIDENCE_FLOOR = 0.35

_MAX_EXAMPLES = 3


@dataclass(frozen=True)
class VocabTerm:
    term: str
    weight: float
    wins: int
    proven: bool
    examples: tuple[str, ...]


def build_vocabulary(profile: dict) -> tuple[VocabTerm, ...]:
    won = profile.get("completed_projects") or []
    declared = [
        str(s.get("name") or "").strip().lower()
        for s in ((profile.get("profile") or {}).get("skills") or [])
        if isinstance(s, dict)
    ]

    raw: dict[str, float] = {}
    wins: dict[str, int] = {}
    examples: dict[str, list[str]] = {}

    for term in TERM_PATTERNS:
        regex = term_regex(term)
        for project in won:
            title = str(project.get("title") or "")
            if not regex.search(title):
                continue
            rate = project.get("rate")
            raw[term] = raw.get(term, 0.0) + _OUTCOME_WEIGHT.get(rate, _UNRATED_WEIGHT)
            wins[term] = wins.get(term, 0) + 1
            if len(examples.setdefault(term, [])) < _MAX_EXAMPLES:
                examples[term].append(title)

    terms: list[VocabTerm] = []
    if raw:
        top = max(raw.values())
        for term, score in raw.items():
            terms.append(
                VocabTerm(
                    term=term,
                    weight=round(score / top, 2) or 0.01,
                    wins=wins[term],
                    proven=True,
                    examples=tuple(examples.get(term, ())),
                )
            )

    # Snapshot before appending: the loop below must compare declared skills
    # against proven concepts only, not against entries it just added.
    proven = tuple(terms)

    # The floor for unproven skills must sit below every proven weight at
    # any win distribution, not just this profile's — otherwise a term with
    # a couple of real wins (wireguard, python, next.js) can end up ranked
    # below a term the user only declared and never won, which is exactly
    # backwards for a vocabulary built to prefer demonstrated outcomes.
    # Derive the floor from the weakest proven term instead of hardcoding
    # it; only fall back to the fixed floor when there is no proven
    # evidence at all to derive one from.
    #
    # No 0.01 clamp here: proven weights are rounded to 2 decimals and can
    # themselves bottom out at 0.01 (round(score / top, 2) or 0.01) when one
    # dominant term compresses the rest. Clamping the floor to that same
    # 0.01 would tie it with a weak proven term instead of sitting below
    # it. Rounding the floor to 4 decimals instead keeps it on a finer
    # grid, so half of even the smallest possible proven weight (0.01) is
    # 0.005 — strictly below, never equal, with no clamp required.
    if proven:
        floor = round(min(t.weight for t in proven) / 2.0, 4)
    else:
        floor = _NO_EVIDENCE_FLOOR

    covered = {t.term for t in proven}
    for name in declared:
        if not name or name in covered:
            continue
        # Skip a declared skill already represented by a proven concept.
        if any(term_regex(t.term).search(name) for t in proven):
            continue
        terms.append(
            VocabTerm(
                term=name,
                weight=floor,
                wins=0,
                proven=False,
                examples=(),
            )
        )

    terms.sort(key=lambda t: (-t.weight, t.term))
    return tuple(terms)


def to_toml(terms: Iterable[VocabTerm]) -> str:
    """Render a [skills] table for the config file."""
    lines = ["[skills]"]
    for term in terms:
        note = (
            f"  # {term.wins} win(s): {term.examples[0][:44]}"
            if term.proven and term.examples
            else "  # declared on the profile, no win by this name"
        )
        lines.append(f'"{term.term}" = {term.weight}{note}')
    return "\n".join(lines) + "\n"
