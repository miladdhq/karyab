"""Fetch a freelancer's public profile into the shape `init` and `vocab` read.

This is what makes karyab usable by someone other than its first user. The
public profile endpoint needs no login and paginates three sub-resources —
completed projects, reviews, work samples — behind one `?page=N`, so a few
serial requests assemble the whole picture.

Output goes to the data directory, never the repository: it is one person's
history and the next user's will be different.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .api import BASE_URL, DEFAULT_USER_AGENT

_REF = re.compile(r"(?:^|/profile/)(\d+)/?$")

# karlancer.com resets connections under rapid load; pace the pages.
PAGE_PAUSE_SECONDS = 0.6
MAX_PAGES = 40


def default_profile_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "karyab" / "profile.json"


def parse_profile_ref(ref: str) -> int:
    """Accept a bare id or any form of the profile URL."""
    text = (ref or "").strip()
    m = _REF.search(text)
    if not m or not text:
        raise ValueError(
            "Give your Karlancer profile id or its URL, e.g. 12345 or "
            "https://www.karlancer.com/profile/12345"
        )
    return int(m.group(1))


def _rows(section: Any) -> list[dict]:
    if isinstance(section, dict):
        return [r for r in (section.get("data") or []) if isinstance(r, dict)]
    return [r for r in (section or []) if isinstance(r, dict)]


def _last_page(section: Any) -> int:
    if isinstance(section, dict):
        try:
            return int(section.get("last_page") or 1)
        except (TypeError, ValueError):
            return 1
    return 1


def consolidate(transport: httpx.BaseTransport | None, user_id: int, *,
                sleep: Callable[[float], None] | None = None) -> dict:
    """Walk every page of a public profile and merge it into one document."""
    pause = sleep if sleep is not None else time.sleep
    client = httpx.Client(
        base_url=BASE_URL, transport=transport, timeout=25.0, trust_env=False,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
    )
    path = f"/api/publics/profile/{user_id}"

    def fetch(page: int) -> dict:
        response = client.get(path, params={"page": page})
        if response.status_code >= 400:
            raise RuntimeError(f"profile {user_id}: HTTP {response.status_code}")
        payload = response.json()
        if payload.get("status") == "failed":
            raise RuntimeError(
                payload.get("error") or f"profile {user_id} could not be read")
        return payload.get("data") or {}

    first = fetch(1)
    projects: dict[int, dict] = {}
    reviews: list[dict] = []
    samples: dict[int, dict] = {}
    warnings: list[str] = []

    def absorb(data: dict) -> None:
        for r in _rows(data.get("completed_projects")):
            key = r.get("project_id") or r.get("id")
            if key is not None:
                projects[int(key)] = r
        reviews.extend(_rows(data.get("reviews_pg")))
        for w in _rows(data.get("worksamples")):
            if w.get("id") is not None:
                samples[int(w["id"])] = w

    absorb(first)
    last = min(MAX_PAGES, max(
        _last_page(first.get("completed_projects")),
        _last_page(first.get("reviews_pg")),
        _last_page(first.get("worksamples")),
    ))
    for page in range(2, last + 1):
        pause(PAGE_PAUSE_SECONDS)
        try:
            absorb(fetch(page))
        except Exception as exc:  # keep what was fetched; say what was lost
            warnings.append(f"page {page}: {exc}")

    keep = ("id", "username", "old_username", "country", "rate", "rate_num",
            "success_rate", "on_time", "answering_speed", "views",
            "description", "skills", "advantage_badge", "reviews_summary")
    return {
        "profile": {k: first.get(k) for k in keep},
        "worksamples": list(samples.values()),
        "completed_projects": sorted(
            projects.values(), key=lambda r: -(r.get("budget") or 0)),
        "reviews": [{k: r.get(k) for k in ("id", "rate", "title", "comment", "created_at")}
                    for r in reviews],
        "warnings": warnings,
    }
