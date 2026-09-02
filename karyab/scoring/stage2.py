"""Stage two: refine a surviving score with the per-project detail record.

Only reached for projects stage one did not reject, because it costs one
HTTP request each. Like stage one it performs no I/O of its own — `now`
and the already-fetched detail are arguments.

Freshness is the steepest signal here. No public field says how many
freelancers have already bid, so arriving early is the only defence
against competition there is.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..config import Config
from ..models import Project, ProjectDetail
from .types import Reason, Score

FILES_BONUS = 6.0
LONG_DESCRIPTION_BONUS = 4.0
THIN_DESCRIPTION_PENALTY = -6.0
IMMINENT_DEADLINE_PENALTY = -8.0

LONG_DESCRIPTION = 200
THIN_DESCRIPTION = 60
IMMINENT_DEADLINE_HOURS = 72

# (max age in minutes, points, label)
FRESHNESS_BANDS: tuple[tuple[float, float, str], ...] = (
    (10, 15.0, "posted in the last 10 minutes"),
    (30, 10.0, "posted in the last half hour"),
    (120, 4.0, "posted in the last 2 hours"),
    (720, 0.0, "posted today"),
    (2880, -10.0, "over 12 hours old"),
    (float("inf"), -20.0, "more than 2 days old"),
)


def _aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC rather than crashing on comparison."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def score_detail(
    base: Score,
    project: Project,
    detail: ProjectDetail,
    config: Config,
    *,
    now: datetime,
    first_seen_at: datetime,
) -> Score:
    if base.rejected:
        return base

    now = _aware(now)
    reasons: list[Reason] = []

    posted = _aware(detail.created_at or first_seen_at)
    age_minutes = max(0.0, (now - posted).total_seconds() / 60.0)
    for limit, points, label in FRESHNESS_BANDS:
        if age_minutes <= limit:
            if points:
                reasons.append(Reason(label, points))
            break

    if detail.file_count:
        reasons.append(
            Reason(f"client attached {detail.file_count} file(s) to the brief", FILES_BONUS)
        )

    length = len(detail.description or "")
    if length >= LONG_DESCRIPTION:
        reasons.append(Reason("detailed brief", LONG_DESCRIPTION_BONUS))
    elif length < THIN_DESCRIPTION:
        reasons.append(Reason("very thin brief", THIN_DESCRIPTION_PENALTY))

    if detail.hire_deadline is not None:
        hours_left = (_aware(detail.hire_deadline) - now).total_seconds() / 3600.0
        if hours_left <= IMMINENT_DEADLINE_HOURS:
            reasons.append(
                Reason("hiring deadline is imminent", IMMINENT_DEADLINE_PENALTY)
            )

    return base.with_extra(reasons)
