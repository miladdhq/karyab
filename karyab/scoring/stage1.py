"""Stage one: score the cheap listing record.

Runs on all 24 projects of every page, so it must not perform any I/O.
Most projects are rejected here, before the detail endpoint is touched.
"""

from __future__ import annotations

from ..config import Config
from ..models import Project
from ..terms import match_terms
from .types import Reason, Score, clamp

BASE_SCORE = 20.0
SKILL_MAX = 55.0
# Total matched weight at which the skill component saturates.
SKILL_SATURATION = 2.0

URGENT_BONUS = 5.0
HIGHLIGHT_BONUS = 3.0
LOW_HIRE_PENALTY = -10.0
UNKNOWN_BUDGET_PENALTY = -8.0
NO_SKILL_PENALTY = -15.0


def score_listing(project: Project, config: Config) -> Score:
    reasons: list[Reason] = []

    # --- hard rejects, cheapest first ------------------------------------
    if project.is_expired:
        reasons.append(Reason("project has expired", 0.0, fatal=True))
        return Score(value=0.0, reasons=tuple(reasons))

    if config.categories_allow and project.category_id not in config.categories_allow:
        reasons.append(
            Reason(
                f"category {project.category_id} is not in the allowlist "
                f"{list(config.categories_allow)}",
                0.0,
                fatal=True,
            )
        )
        return Score(value=0.0, reasons=tuple(reasons))

    if project.category_id in config.categories_block:
        reasons.append(
            Reason(f"category {project.category_id} is blocked", 0.0, fatal=True)
        )
        return Score(value=0.0, reasons=tuple(reasons))

    if project.max_budget and project.max_budget < config.min_budget:
        reasons.append(
            Reason(
                f"budget ceiling {project.max_budget:,} is below the floor "
                f"{config.min_budget:,}",
                0.0,
                fatal=True,
            )
        )
        return Score(value=0.0, reasons=tuple(reasons))

    if project.token > config.max_token_cost:
        reasons.append(
            Reason(
                f"costs {project.token} tokens, over the limit of "
                f"{config.max_token_cost}",
                0.0,
                fatal=True,
            )
        )
        return Score(value=0.0, reasons=tuple(reasons))

    # --- scoring ---------------------------------------------------------
    total = BASE_SCORE
    reasons.append(Reason("base", BASE_SCORE))

    # Matched through karyab.terms, not by substring: the vocabulary is
    # keyed on English terms and the projects are written in Persian.
    matched = match_terms(project.haystack, config.skills)

    if matched:
        raw = sum(matched.values())
        points = round(SKILL_MAX * min(1.0, raw / SKILL_SATURATION), 1)
        top = ", ".join(sorted(matched, key=lambda t: -matched[t])[:4])
        reasons.append(Reason(f"skill match: {top}", points))
        total += points
    else:
        reasons.append(Reason("no skill term matched", NO_SKILL_PENALTY))
        total += NO_SKILL_PENALTY

    if not project.max_budget:
        reasons.append(Reason("budget not stated", UNKNOWN_BUDGET_PENALTY))
        total += UNKNOWN_BUDGET_PENALTY
    elif config.sweet_spot_enabled:
        low, high = config.sweet_spot
        if low <= project.max_budget <= high:
            reasons.append(
                Reason(
                    f"inside the sweet spot band {low:,}-{high:,}",
                    config.sweet_spot_bonus,
                )
            )
            total += config.sweet_spot_bonus

    if project.low_hire is True:
        reasons.append(Reason("client flagged low_hire", LOW_HIRE_PENALTY))
        total += LOW_HIRE_PENALTY

    if project.is_urgent:
        reasons.append(Reason("marked urgent", URGENT_BONUS))
        total += URGENT_BONUS

    if project.is_highlight:
        reasons.append(Reason("highlighted listing", HIGHLIGHT_BONUS))
        total += HIGHLIGHT_BONUS

    return Score(value=clamp(total), reasons=tuple(reasons))
