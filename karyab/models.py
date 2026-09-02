"""Immutable views over the two public Karlancer endpoints.

The API is undocumented and its records are sparse in ways that matter:
`low_hire` is null in the detail response, `users_bid` is null everywhere,
and several fields are simply absent on some records. Everything here
degrades to a safe default rather than raising, because a single odd
record must not stop the feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse an API timestamp, or return None if it is unusable.

    Two shapes are observed in the wild:
        2026-08-31T16:24:15.000000Z        (created_at, UTC)
        2026-10-01T20:09:48.000000+03:30   (hire_deadline, Tehran)
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _int(raw: dict, key: str, default: int = 0) -> int:
    value = raw.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool(raw: dict, key: str) -> bool:
    return bool(raw.get(key))


@dataclass(frozen=True)
class Project:
    """One project as it appears in the search listing."""

    id: int
    user_id: int
    title: str
    description: str
    slug: str
    min_budget: int
    max_budget: int
    category_id: int
    skills: tuple[str, ...]
    token: int
    job_duration: int
    country: str
    is_urgent: bool
    is_highlight: bool
    is_expired: bool
    # None means unknown: the field is absent from the detail response.
    low_hire: bool | None

    @classmethod
    def from_listing(cls, raw: dict) -> "Project":
        skills = tuple(
            str(s["name"])
            for s in (raw.get("skills") or [])
            if isinstance(s, dict) and s.get("name")
        )
        low_hire = raw.get("low_hire")
        return cls(
            id=_int(raw, "id"),
            user_id=_int(raw, "user_id"),
            title=str(raw.get("title") or ""),
            description=str(raw.get("description") or ""),
            slug=str(raw.get("url") or ""),
            min_budget=_int(raw, "min_budget"),
            max_budget=_int(raw, "max_budget"),
            category_id=_int(raw, "category_id"),
            skills=skills,
            token=_int(raw, "token"),
            job_duration=_int(raw, "job_duration"),
            country=str(raw.get("country") or ""),
            is_urgent=_bool(raw, "is_urgent"),
            is_highlight=_bool(raw, "is_highlight"),
            is_expired=_bool(raw, "is_expired"),
            low_hire=None if low_hire is None else bool(low_hire),
        )

    @property
    def haystack(self) -> str:
        """Everything a skill term might match against, lowercased."""
        return " ".join([self.title, self.description, *self.skills]).lower()


@dataclass(frozen=True)
class ProjectDetail:
    """The extra fields only the per-project endpoint returns."""

    id: int
    created_at: datetime | None
    hire_deadline: datetime | None
    file_count: int
    description: str

    @classmethod
    def from_detail(cls, raw: dict) -> "ProjectDetail":
        payload = raw.get("data") if "data" in raw else raw
        payload = payload or {}
        files = payload.get("files") or []
        return cls(
            id=_int(payload, "id"),
            created_at=parse_timestamp(payload.get("created_at")),
            hire_deadline=parse_timestamp(payload.get("hire_deadline")),
            file_count=len(files) if isinstance(files, list) else 0,
            description=str(payload.get("description") or ""),
        )
