"""One pass over the feed: fetch, score, store.

This is the only module in Phase 1 that performs I/O and holds the clock,
which keeps the scorers pure. A failure on one project or one page is
recorded and stepped over: a single bad record must never stop the feed.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .api import ApiError
from .config import Config
from .models import Project, ProjectDetail
from .scoring.stage1 import score_listing
from .scoring.stage2 import score_detail

# Stage two can add at most ~25 points. Anything further below the
# threshold than this cannot be rescued, so its detail is not worth fetching.
DETAIL_CUTOFF_MARGIN = 25.0

_MIN_DELAY = 0.4
_MAX_DELAY = 1.2


@dataclass(frozen=True)
class ScanResult:
    seen: int = 0
    new: int = 0
    rejected: int = 0
    promoted: int = 0
    detail_fetches: int = 0
    errors: tuple[str, ...] = ()


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)


def run_scan(
    client,
    store,
    config: Config,
    *,
    now: datetime,
    pages: int = 1,
    sleep: Callable[[float], None] | None = None,
    detail_cutoff: float | None = None,
) -> ScanResult:
    pause = sleep if sleep is not None else _default_sleep
    cutoff = (
        detail_cutoff
        if detail_cutoff is not None
        else config.threshold - DETAIL_CUTOFF_MARGIN
    )

    seen = new = rejected = promoted = detail_fetches = 0
    errors: list[str] = []

    for page in range(1, max(1, pages) + 1):
        if page > 1:
            pause(random.uniform(_MIN_DELAY, _MAX_DELAY))
        try:
            rows = client.search_projects(page=page)
        except ApiError as exc:
            errors.append(f"page {page}: {exc}")
            continue

        for raw in rows:
            try:
                project = Project.from_listing(raw)
            except Exception as exc:  # a malformed row must not stop the feed
                errors.append(f"unparsable row: {exc}")
                continue

            seen += 1
            if not store.has_seen(project.id):
                new += 1
            first_seen_at = store.first_seen(project, now)

            score = score_listing(project, config)
            stage = 1
            final = score

            # Stage two refines `score` in place rather than being recorded
            # separately: the scores table keys on (project_id, stage), so a
            # second insert under stage 2 would sit alongside the stage-1
            # row rather than replace it. One project gets one stored score
            # -- whichever stage last touched it.
            if not score.rejected and score.value >= cutoff:
                pause(random.uniform(_MIN_DELAY, _MAX_DELAY))
                try:
                    detail_raw = client.project_detail(project.slug)
                    detail_fetches += 1
                except ApiError as exc:
                    errors.append(f"detail {project.slug}: {exc}")
                else:
                    try:
                        detail = ProjectDetail.from_detail(detail_raw)
                        final = score_detail(
                            score,
                            project,
                            detail,
                            config,
                            now=now,
                            first_seen_at=first_seen_at,
                        )
                        stage = 2
                    except Exception as exc:  # a malformed detail must not stop the feed
                        errors.append(f"unparsable detail {project.slug}: {exc}")

            store.record_score(
                project.id, stage, final.value, final.rejected, final.labels, now
            )

            if final.rejected:
                rejected += 1
            elif final.value >= config.threshold:
                promoted += 1

    return ScanResult(
        seen=seen,
        new=new,
        rejected=rejected,
        promoted=promoted,
        detail_fetches=detail_fetches,
        errors=tuple(errors),
    )
