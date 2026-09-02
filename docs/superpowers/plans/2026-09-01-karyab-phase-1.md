# karyab Phase 1 — Feed and Matcher — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A CLI that polls Karlancer's public project feed, scores every project against the user's measured skill profile, and reports what it would have bid on and why — with no LLM call and no browser anywhere in it.

**Architecture:** A thin httpx client over two unauthenticated JSON endpoints feeds immutable `Project` records into a two-stage scorer of pure functions. Stage one rejects most projects from the cheap listing record; stage two fetches per-project detail only for survivors. SQLite records every project seen — including rejects and their reasons — so the matcher can be tuned against real misses.

**Tech Stack:** Python 3.12, httpx, pytest, stdlib sqlite3, stdlib tomllib. No LLM SDK, no Playwright, no web framework in this phase.

**Spec:** `docs/superpowers/specs/2026-08-31-karyab-design.md`

## Global Constraints

- Python 3.12. All dependencies live in a project-local venv at `.venv/`; the system Python is externally managed (PEP 668) and must not be installed into.
- **Scoring functions are pure.** No network calls, no clock reads, no file access inside `karyab/scoring/`. The caller passes `now` and any fetched detail in as arguments. This is what makes the matcher testable.
- **Persian relative-time strings are never parsed.** `past_time` (e.g. `"۲ دقیقه  پیش"`, note the double space and Persian-Indic digits) is display text. Freshness comes from `first_seen_at` recorded locally and `created_at` from the detail endpoint.
- **Three listing fields carry no signal and must not be scored:** `users_bid` is `null` on every record, `successful_projects_percentage` is `0` on every record, and `low_hire` is `null` in the detail response (read it from the listing only, treating `null` as unknown).
- Every score carries human-readable reasons, for rejections as well as acceptances. A rejected project is stored, never discarded.
- Default category allowlist is `[6]` — all 29 of the user's completed projects are category 6.
- Requests to karlancer.com are serial, never parallel, with a jittered delay between them.
- Money is integer toman throughout. No floats for currency.

---

### Task 1: Project scaffold and configuration

**Files:**
- Create: `pyproject.toml`
- Create: `karyab/__init__.py`
- Create: `karyab/config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `karyab.config.Config` — a frozen dataclass with fields `skills: dict[str, float]`, `categories_allow: tuple[int, ...]`, `categories_block: tuple[int, ...]`, `min_budget: int`, `sweet_spot: tuple[int, int]`, `sweet_spot_bonus: float`, `sweet_spot_enabled: bool`, `max_token_cost: int`, `threshold: float`, `daily_cap: int`, `poll_seconds: int`. Class methods `Config.default() -> Config` and `Config.load(path: Path) -> Config`. Module function `default_config_path() -> Path`.

- [ ] **Step 1: Create the venv and install dependencies**

```bash
cd /home/milad/dev/karyab
python3 -m venv .venv
.venv/bin/pip install --quiet --disable-pip-version-check httpx pytest
.venv/bin/python -c "import httpx, pytest; print('ok', httpx.__version__, pytest.__version__)"
```

Expected: `ok 0.28.1 9.1.1` (versions may differ; any successful import is fine).

- [ ] **Step 2: Write `.gitignore` and `pyproject.toml`**

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
*.db
```

`pyproject.toml`:

```toml
[project]
name = "karyab"
version = "0.1.0"
description = "Selective proposal assistant for karlancer.com"
requires-python = ">=3.12"
dependencies = ["httpx>=0.27"]

[project.scripts]
karyab = "karyab.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Write the failing test**

`tests/__init__.py` is empty. `tests/test_config.py`:

```python
import textwrap
from pathlib import Path

from karyab.config import Config


def test_default_config_targets_category_six_only():
    cfg = Config.default()
    assert cfg.categories_allow == (6,)
    assert cfg.categories_block == ()


def test_default_sweet_spot_matches_the_measured_band():
    cfg = Config.default()
    assert cfg.sweet_spot == (500_000, 3_500_000)
    assert cfg.sweet_spot_enabled is True


def test_load_overrides_defaults_and_keeps_the_rest(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        textwrap.dedent(
            """
            min_budget = 900000
            threshold = 70.0

            [skills]
            "telegram bot" = 1.0
            react = 0.8
            """
        ).strip(),
        encoding="utf-8",
    )

    cfg = Config.load(path)

    assert cfg.min_budget == 900_000
    assert cfg.threshold == 70.0
    assert cfg.skills == {"telegram bot": 1.0, "react": 0.8}
    # untouched keys keep their defaults
    assert cfg.categories_allow == (6,)
    assert cfg.daily_cap == 8


def test_load_rejects_an_unknown_key(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("mn_budget = 900000\n", encoding="utf-8")

    try:
        Config.load(path)
    except ValueError as exc:
        assert "mn_budget" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown key")


def test_load_rejects_a_backwards_sweet_spot(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("sweet_spot = [3500000, 500000]\n", encoding="utf-8")

    try:
        Config.load(path)
    except ValueError as exc:
        assert "sweet_spot" in str(exc)
    else:
        raise AssertionError("expected ValueError for inverted sweet_spot")
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karyab'`

- [ ] **Step 5: Write the implementation**

`karyab/__init__.py`:

```python
"""karyab — a selective proposal assistant for karlancer.com."""

__version__ = "0.1.0"
```

`karyab/config.py`:

```python
"""User-editable configuration.

Every knob the matcher reads lives here. Defaults are measured from the
user's own 29 completed projects, not guessed — see the spec section
"The user's profile, measured".
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path


def default_config_path() -> Path:
    """Where the config lives, honouring XDG_CONFIG_HOME."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "karyab" / "config.toml"


@dataclass(frozen=True)
class Config:
    # term -> weight. Generated from won projects by `karyab vocab`.
    skills: dict[str, float] = field(default_factory=dict)

    # Category 6 is برنامه نویسی. All 29 completed projects are category 6.
    categories_allow: tuple[int, ...] = (6,)
    categories_block: tuple[int, ...] = ()

    # Hard floor: a project whose ceiling is below this is not worth a token.
    min_budget: int = 500_000

    # Where the five-star outcomes cluster. A bonus, never a cap.
    sweet_spot: tuple[int, int] = (500_000, 3_500_000)
    sweet_spot_bonus: float = 12.0
    sweet_spot_enabled: bool = True

    # Proposals cost 1-7 tokens. Refuse to spend more than this on one bid.
    max_token_cost: int = 7

    # Score below which a project is not worth drafting for.
    threshold: float = 55.0

    daily_cap: int = 8
    poll_seconds: int = 150

    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def load(cls, path: Path) -> "Config":
        """Read a TOML file over the defaults.

        Unknown keys are an error rather than a silent no-op: a typo in a
        config file is otherwise invisible and would quietly change which
        projects get bid on.
        """
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(
                f"unknown config key(s) in {path}: {', '.join(unknown)}"
            )

        overrides: dict[str, object] = {}
        for key, value in raw.items():
            if key in {"categories_allow", "categories_block"}:
                overrides[key] = tuple(int(v) for v in value)
            elif key == "sweet_spot":
                lo, hi = (int(v) for v in value)
                overrides[key] = (lo, hi)
            elif key == "skills":
                overrides[key] = {str(k): float(v) for k, v in value.items()}
            else:
                overrides[key] = value

        cfg = replace(cls.default(), **overrides)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        lo, hi = self.sweet_spot
        if lo > hi:
            raise ValueError(
                f"sweet_spot must be [low, high], got [{lo}, {hi}]"
            )
        if self.min_budget < 0:
            raise ValueError("min_budget must not be negative")
        if not 0 <= self.threshold <= 100:
            raise ValueError("threshold must be between 0 and 100")
        if self.max_token_cost < 1:
            raise ValueError("max_token_cost must be at least 1")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore karyab/__init__.py karyab/config.py tests/__init__.py tests/test_config.py
git commit -m "Add project scaffold and configuration

Defaults are measured rather than guessed: category 6 only, and a
500k-3.5M sweet-spot band where the user's five-star outcomes cluster.
Unknown config keys raise rather than being ignored, because a silent
typo would quietly change which projects get bid on."
```

---

### Task 2: Project models

**Files:**
- Create: `karyab/models.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `karyab.models.Project` — frozen dataclass, fields `id: int`, `user_id: int`, `title: str`, `description: str`, `slug: str`, `min_budget: int`, `max_budget: int`, `category_id: int`, `skills: tuple[str, ...]`, `token: int`, `job_duration: int`, `country: str`, `is_urgent: bool`, `is_highlight: bool`, `is_expired: bool`, `low_hire: bool | None`. Class method `Project.from_listing(raw: dict) -> Project`.
  - `karyab.models.ProjectDetail` — frozen dataclass, fields `id: int`, `created_at: datetime | None`, `hire_deadline: datetime | None`, `file_count: int`, `description: str`. Class method `ProjectDetail.from_detail(raw: dict) -> ProjectDetail`.
  - `karyab.models.parse_timestamp(value: str | None) -> datetime | None`.
- Fixtures produced for later tasks: `listing_page` (the parsed search response `dict`), `listing_raw` (first project `dict`), `detail_raw` (the parsed detail response `dict`), `profile_raw` (the parsed profile `dict`).

- [ ] **Step 1: Write the shared fixtures**

`tests/conftest.py`:

```python
import json
from pathlib import Path

import pytest

RESEARCH = Path(__file__).resolve().parents[1] / "docs" / "research"


def _load(name: str) -> dict:
    return json.loads((RESEARCH / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def listing_page() -> dict:
    """A real /api/publics/search/projects?page=1 response."""
    return _load("sample-search-projects.json")


@pytest.fixture(scope="session")
def listing_raw(listing_page: dict) -> dict:
    return listing_page["data"]["data"][0]


@pytest.fixture(scope="session")
def detail_raw() -> dict:
    """A real /api/publics/projects/{slug} response."""
    return _load("sample-project-detail.json")


@pytest.fixture(scope="session")
def profile_raw() -> dict:
    """The user's consolidated profile, 29 completed projects included."""
    return _load("profile-65389.json")
```

- [ ] **Step 2: Write the failing test**

`tests/test_models.py`:

```python
from datetime import datetime, timezone

from karyab.models import Project, ProjectDetail, parse_timestamp


def test_project_parses_a_real_listing_record(listing_raw):
    project = Project.from_listing(listing_raw)

    assert project.id == 322128
    assert project.category_id == 2
    assert project.min_budget == 500_000
    assert project.max_budget == 2_000_000
    assert project.token == 2
    assert "طراحی لوگو" in project.skills
    assert project.is_urgent is False
    assert project.low_hire is False


def test_project_keeps_the_slug_for_the_detail_fetch(listing_raw):
    project = Project.from_listing(listing_raw)
    assert project.slug == listing_raw["url"]
    assert project.slug


def test_every_project_on_the_page_parses(listing_page):
    rows = listing_page["data"]["data"]
    projects = [Project.from_listing(row) for row in rows]

    assert len(projects) == 24
    assert all(p.id > 0 for p in projects)
    assert all(isinstance(p.skills, tuple) for p in projects)


def test_low_hire_null_becomes_none_not_false():
    project = Project.from_listing(
        {"id": 1, "url": "x", "title": "t", "low_hire": None}
    )
    assert project.low_hire is None


def test_missing_fields_fall_back_to_safe_defaults():
    project = Project.from_listing({"id": 7, "url": "slug", "title": "t"})

    assert project.min_budget == 0
    assert project.max_budget == 0
    assert project.skills == ()
    assert project.token == 0
    assert project.description == ""


def test_detail_parses_timestamps_and_counts_files(detail_raw):
    detail = ProjectDetail.from_detail(detail_raw)

    assert detail.id == 322126
    assert detail.created_at == datetime(2026, 8, 31, 16, 24, 15, tzinfo=timezone.utc)
    assert detail.hire_deadline is not None
    assert detail.file_count == 1


def test_parse_timestamp_handles_both_observed_shapes():
    utc = parse_timestamp("2026-08-31T16:24:15.000000Z")
    tehran = parse_timestamp("2026-10-01T20:09:48.000000+03:30")

    assert utc == datetime(2026, 8, 31, 16, 24, 15, tzinfo=timezone.utc)
    assert tehran is not None
    assert tehran.utcoffset().total_seconds() == 3.5 * 3600


def test_parse_timestamp_tolerates_missing_values():
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None
    assert parse_timestamp("not a date") is None
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karyab.models'`

- [ ] **Step 4: Write the implementation**

`karyab/models.py`:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add karyab/models.py tests/conftest.py tests/test_models.py
git commit -m "Parse listing and detail records into immutable models

Tested against the real captured responses rather than invented JSON.
Every field degrades to a safe default: the API omits fields on some
records, and one odd project must not stop the feed. low_hire keeps a
three-state value because null means unknown, not false."
```

---

### Task 3: The API client

**Files:**
- Create: `karyab/api.py`
- Create: `tests/test_api.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (returns raw dicts; `Project` parsing stays the caller's job).
- Produces: `karyab.api.KarlancerClient` with `__init__(self, *, transport: httpx.BaseTransport | None = None, timeout: float = 20.0, user_agent: str = DEFAULT_USER_AGENT)`, methods `search_projects(page: int = 1) -> list[dict]`, `project_detail(slug: str) -> dict`, `profile(user_id: int, page: int = 1) -> dict`, `close() -> None`, and context-manager support. Module constants `BASE_URL`, `DEFAULT_USER_AGENT`. Exception `karyab.api.ApiError`.

- [ ] **Step 1: Write the failing test**

`tests/test_api.py`:

```python
import json

import httpx
import pytest

from karyab.api import ApiError, KarlancerClient


def _client(handler) -> KarlancerClient:
    return KarlancerClient(transport=httpx.MockTransport(handler))


def test_search_projects_returns_the_inner_row_list(listing_page):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=listing_page)

    with _client(handler) as client:
        rows = client.search_projects(page=3)

    assert len(rows) == 24
    assert rows[0]["id"] == 322128
    assert "page=3" in seen["url"]
    assert seen["url"].startswith("https://www.karlancer.com/api/publics/search/projects")


def test_search_sends_a_browser_user_agent_and_accepts_json():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(200, json={"status": "success", "data": {"data": []}})

    with _client(handler) as client:
        client.search_projects()

    assert "Mozilla" in captured["user-agent"]
    assert captured["accept"] == "application/json"


def test_project_detail_unwraps_the_envelope(detail_raw):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/publics/projects/" in str(request.url)
        return httpx.Response(200, json=detail_raw)

    with _client(handler) as client:
        payload = client.project_detail("some-slug-abc123")

    assert payload["id"] == 322126


def test_a_persian_slug_is_url_encoded():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"status": "success", "data": {"id": 1}})

    with _client(handler) as client:
        client.project_detail("طراحی-سایت-abc")

    assert " " not in seen["url"]
    assert "%D8" in seen["url"]


def test_http_error_raises_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with _client(handler) as client:
        with pytest.raises(ApiError) as exc:
            client.search_projects()

    assert "500" in str(exc.value)


def test_a_failed_status_envelope_raises_with_the_server_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "failed", "data": None, "error": "وب سرویس مورد نظر وجود ندارد."},
        )

    with _client(handler) as client:
        with pytest.raises(ApiError) as exc:
            client.project_detail("missing")

    assert "وب سرویس" in str(exc.value)


def test_non_json_body_raises_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with _client(handler) as client:
        with pytest.raises(ApiError):
            client.search_projects()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karyab.api'`

- [ ] **Step 3: Write the implementation**

`karyab/api.py`:

```python
"""Client for Karlancer's undocumented public JSON API.

Only unauthenticated endpoints live here. Anything that touches the user's
account goes through a real browser in a later phase — see the spec's
"Auth design" section.

The API wraps responses in an envelope:

    {"status": "success" | "failed", "data": ..., "error": str | None}

A failed envelope arrives with HTTP 200, so the status field has to be
checked explicitly.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

BASE_URL = "https://www.karlancer.com"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class ApiError(RuntimeError):
    """The API could not be reached, or refused the request."""


class KarlancerClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )

    def __enter__(self) -> "KarlancerClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise ApiError(f"request to {path} failed: {exc}") from exc

        if response.status_code >= 400:
            raise ApiError(f"{path} returned HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(f"{path} returned a non-JSON body") from exc

        if isinstance(payload, dict) and payload.get("status") == "failed":
            raise ApiError(payload.get("error") or f"{path} returned status=failed")

        return payload

    def search_projects(self, page: int = 1) -> list[dict]:
        """Newest-first page of the public project feed, 24 rows per page."""
        payload = self._get("/api/publics/search/projects", {"page": page})
        data = (payload or {}).get("data") or {}
        rows = data.get("data") or []
        return [row for row in rows if isinstance(row, dict)]

    def project_detail(self, slug: str) -> dict:
        """One project's detail record. Slugs are Persian and need encoding."""
        payload = self._get(f"/api/publics/projects/{quote(slug, safe='')}")
        return (payload or {}).get("data") or {}

    def profile(self, user_id: int, page: int = 1) -> dict:
        """A public freelancer profile.

        `?page=N` paginates the completed_projects, reviews_pg and
        worksamples sub-resources all at once.
        """
        payload = self._get(f"/api/publics/profile/{int(user_id)}", {"page": page})
        return (payload or {}).get("data") or {}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add karyab/api.py tests/test_api.py
git commit -m "Add the public API client

Tested entirely against httpx.MockTransport, so the suite never touches
the live site. A failed envelope arrives with HTTP 200, so status is
checked explicitly rather than trusting the status code, and Persian
slugs are percent-encoded."
```

---

### Task 4: The project store

**Files:**
- Create: `karyab/store.py`
- Create: `tests/test_store.py`

**Interfaces:**
- Consumes: `karyab.models.Project` (Task 2), `karyab.scoring.types.Score` is *not* needed yet — `record_score` takes primitives so this task stays independent of Task 5.
- Produces: `karyab.store.Store` with `Store(path: Path | str)`, `.first_seen(project: Project, now: datetime) -> datetime`, `.record_score(project_id: int, stage: int, value: float, rejected: bool, reasons: list[str], now: datetime) -> None`, `.latest_scores(limit: int = 50) -> list[dict]`, `.has_seen(project_id: int) -> bool`, `.close()`, context-manager support.

- [ ] **Step 1: Write the failing test**

`tests/test_store.py`:

```python
from datetime import datetime, timedelta, timezone

from karyab.models import Project
from karyab.store import Store

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _project(listing_raw: dict) -> Project:
    return Project.from_listing(listing_raw)


def test_first_seen_records_the_first_time_and_is_stable(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        first = store.first_seen(project, NOW)
        later = store.first_seen(project, NOW + timedelta(hours=3))

    assert first == NOW
    assert later == NOW, "a project's first_seen must never move"


def test_has_seen_reports_novelty(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        assert store.has_seen(project.id) is False
        store.first_seen(project, NOW)
        assert store.has_seen(project.id) is True


def test_the_project_row_keeps_enough_to_explain_a_decision(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        store.first_seen(project, NOW)
        rows = store.latest_scores()

    assert rows == []  # nothing scored yet


def test_rejected_projects_are_stored_not_discarded(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        store.first_seen(project, NOW)
        store.record_score(
            project.id,
            stage=1,
            value=0.0,
            rejected=True,
            reasons=["category 2 not in allowlist"],
            now=NOW,
        )
        rows = store.latest_scores()

    assert len(rows) == 1
    assert rows[0]["rejected"] is True
    assert rows[0]["reasons"] == ["category 2 not in allowlist"]
    assert rows[0]["title"] == project.title


def test_rescoring_replaces_the_previous_score_for_that_stage(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        store.first_seen(project, NOW)
        store.record_score(project.id, 1, 40.0, False, ["first"], NOW)
        store.record_score(project.id, 1, 72.0, False, ["second"], NOW)
        rows = store.latest_scores()

    assert len(rows) == 1
    assert rows[0]["value"] == 72.0
    assert rows[0]["reasons"] == ["second"]


def test_both_stages_coexist_for_one_project(tmp_path, listing_raw):
    project = _project(listing_raw)

    with Store(tmp_path / "k.db") as store:
        store.first_seen(project, NOW)
        store.record_score(project.id, 1, 60.0, False, ["stage one"], NOW)
        store.record_score(project.id, 2, 78.0, False, ["stage two"], NOW)
        rows = store.latest_scores()

    assert {r["stage"] for r in rows} == {1, 2}


def test_reopening_the_database_keeps_everything(tmp_path, listing_raw):
    project = _project(listing_raw)
    path = tmp_path / "k.db"

    with Store(path) as store:
        store.first_seen(project, NOW)
        store.record_score(project.id, 1, 51.0, False, ["kept"], NOW)

    with Store(path) as store:
        rows = store.latest_scores()

    assert len(rows) == 1
    assert rows[0]["value"] == 51.0


def test_the_parent_directory_is_created(tmp_path, listing_raw):
    path = tmp_path / "nested" / "deeper" / "k.db"

    with Store(path) as store:
        store.first_seen(_project(listing_raw), NOW)

    assert path.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karyab.store'`

- [ ] **Step 3: Write the implementation**

`karyab/store.py`:

```python
"""SQLite persistence for everything the feed has shown us.

Two invariants matter here:

  * `first_seen_at` is written once and never moves. It is the only
    trustworthy freshness signal, because the API's `past_time` is a
    localised display string and `created_at` costs a detail request.
  * Rejected projects are stored with their reasons. Tuning the matcher
    means looking at what it threw away, so throwing it away is not an
    option.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import Project

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id             INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL DEFAULT 0,
    title          TEXT    NOT NULL DEFAULT '',
    slug           TEXT    NOT NULL DEFAULT '',
    category_id    INTEGER NOT NULL DEFAULT 0,
    min_budget     INTEGER NOT NULL DEFAULT 0,
    max_budget     INTEGER NOT NULL DEFAULT 0,
    token          INTEGER NOT NULL DEFAULT 0,
    skills         TEXT    NOT NULL DEFAULT '[]',
    first_seen_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
    project_id  INTEGER NOT NULL,
    stage       INTEGER NOT NULL,
    value       REAL    NOT NULL,
    rejected    INTEGER NOT NULL,
    reasons     TEXT    NOT NULL DEFAULT '[]',
    scored_at   TEXT    NOT NULL,
    PRIMARY KEY (project_id, stage),
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS scores_by_value ON scores(value DESC);
"""


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._db.commit()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def has_seen(self, project_id: int) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return row is not None

    def first_seen(self, project: Project, now: datetime) -> datetime:
        """Record the project if new; return when we first saw it.

        The INSERT is deliberately not an upsert on first_seen_at: the
        whole point of the column is that it does not move.
        """
        self._db.execute(
            """
            INSERT INTO projects
                (id, user_id, title, slug, category_id,
                 min_budget, max_budget, token, skills, first_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title      = excluded.title,
                max_budget = excluded.max_budget,
                min_budget = excluded.min_budget,
                token      = excluded.token,
                skills     = excluded.skills
            """,
            (
                project.id,
                project.user_id,
                project.title,
                project.slug,
                project.category_id,
                project.min_budget,
                project.max_budget,
                project.token,
                json.dumps(list(project.skills), ensure_ascii=False),
                now.isoformat(),
            ),
        )
        self._db.commit()

        row = self._db.execute(
            "SELECT first_seen_at FROM projects WHERE id = ?", (project.id,)
        ).fetchone()
        return datetime.fromisoformat(row["first_seen_at"])

    def record_score(
        self,
        project_id: int,
        stage: int,
        value: float,
        rejected: bool,
        reasons: list[str],
        now: datetime,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO scores (project_id, stage, value, rejected, reasons, scored_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, stage) DO UPDATE SET
                value     = excluded.value,
                rejected  = excluded.rejected,
                reasons   = excluded.reasons,
                scored_at = excluded.scored_at
            """,
            (
                project_id,
                stage,
                float(value),
                1 if rejected else 0,
                json.dumps(reasons, ensure_ascii=False),
                now.isoformat(),
            ),
        )
        self._db.commit()

    def latest_scores(self, limit: int = 50) -> list[dict]:
        rows = self._db.execute(
            """
            SELECT s.project_id, s.stage, s.value, s.rejected, s.reasons,
                   s.scored_at, p.title, p.slug, p.min_budget, p.max_budget,
                   p.token, p.category_id, p.first_seen_at
            FROM scores s
            JOIN projects p ON p.id = s.project_id
            ORDER BY s.value DESC, s.scored_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [
            {
                "project_id": r["project_id"],
                "stage": r["stage"],
                "value": r["value"],
                "rejected": bool(r["rejected"]),
                "reasons": json.loads(r["reasons"]),
                "scored_at": r["scored_at"],
                "title": r["title"],
                "slug": r["slug"],
                "min_budget": r["min_budget"],
                "max_budget": r["max_budget"],
                "token": r["token"],
                "category_id": r["category_id"],
                "first_seen_at": r["first_seen_at"],
            }
            for r in rows
        ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_store.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add karyab/store.py tests/test_store.py
git commit -m "Add the SQLite project store

first_seen_at is written once and never updated: it is the only
freshness signal that costs nothing, since past_time is a localised
display string. Rejected projects are stored with their reasons, because
tuning the matcher means reading what it threw away."
```

---

### Task 5: Skill vocabulary generated from won projects

**Files:**
- Create: `karyab/terms.py`
- Create: `karyab/vocab.py`
- Create: `tests/test_terms.py`
- Create: `tests/test_vocab.py`

**Interfaces:**
- Consumes: the profile JSON shape captured in `docs/research/profile-65389.json` (keys `profile.skills`, `completed_projects[].{title,budget,rate}`).
- Produces:
  - `karyab.terms.TERM_PATTERNS: dict[str, str]` — canonical term to a regex covering its Persian and English spellings.
  - `karyab.terms.term_regex(term: str) -> re.Pattern` — the pattern for a known term, or an escaped literal for a user-invented one.
  - `karyab.terms.match_terms(haystack: str, skills: Mapping[str, float]) -> dict[str, float]` — the terms present in a piece of text, with their weights.
  - `karyab.vocab.VocabTerm` — frozen dataclass with `term: str`, `weight: float`, `wins: int`, `proven: bool`, `examples: tuple[str, ...]`.
  - `karyab.vocab.build_vocabulary(profile: dict) -> tuple[VocabTerm, ...]` — ordered by weight descending.
  - `karyab.vocab.to_toml(terms: Iterable[VocabTerm]) -> str` — a `[skills]` block ready to paste into the config.

**Why `terms.py` is separate:** the vocabulary's canonical terms are English
(`bot`, `telegram bot`), but the projects they must match are written in
Persian (`ربات تلگرام`). Substring matching would therefore never fire. The
regex table is the bridge, and both the generator and the scorer have to use
the same one — so it lives in a module of its own that neither owns.

**Why this task exists:** the profile declares seven skills and none of them is the word "bot", yet 11 of the 29 completed projects are bots. A matcher keyed on the declared list would miss the single largest cluster of work the user wins. The vocabulary is therefore derived from outcomes and only then handed to the user to correct.

- [ ] **Step 1: Write the failing test for the shared matcher**

`tests/test_terms.py`:

```python
from karyab.terms import TERM_PATTERNS, match_terms, term_regex


def test_an_english_term_matches_a_persian_title():
    # The whole reason this module exists.
    assert term_regex("bot").search("ساخت ربات تلگرام دانلودر")
    assert term_regex("website").search("طراحی سایت فروشگاهی")
    assert term_regex("react").search("پروژه برنامه نویسی ری اکت")


def test_an_english_term_still_matches_english_text():
    assert term_regex("react").search("React dashboard")
    assert term_regex("php").search("legacy PHP app")


def test_matching_is_case_insensitive():
    assert term_regex("php").search("PHP")


def test_word_boundaries_stop_false_positives():
    # "bot" must not fire on "bottom" or "robotics" written in English.
    assert not term_regex("bot").search("bottom of the page")


def test_an_unknown_term_falls_back_to_a_literal_match():
    assert term_regex("kubernetes").search("راه اندازی kubernetes")
    assert not term_regex("kubernetes").search("docker only")


def test_a_regex_metacharacter_in_a_user_term_is_escaped():
    # "next.js" is a known term, but an invented one with a dot must not
    # turn the dot into a wildcard.
    assert not term_regex("c++x").search("cxx")


def test_match_terms_returns_only_present_terms_with_weights():
    skills = {"bot": 1.0, "react": 0.8, "website": 0.5}
    found = match_terms("ساخت ربات تلگرام", skills)

    assert found == {"bot": 1.0}


def test_match_terms_finds_several_at_once():
    skills = {"bot": 1.0, "telegram bot": 0.9, "website": 0.5}
    found = match_terms("ربات تلگرام برای سایت فروشگاهی", skills)

    assert set(found) == {"bot", "telegram bot", "website"}


def test_match_terms_on_empty_input_is_empty():
    assert match_terms("", {"bot": 1.0}) == {}
    assert match_terms("ربات", {}) == {}


def test_every_pattern_compiles():
    import re

    for pattern in TERM_PATTERNS.values():
        re.compile(pattern)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_terms.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karyab.terms'`

- [ ] **Step 3: Write `karyab/terms.py`**

```python
"""The bridge between English skill names and Persian project text.

The vocabulary is keyed on canonical English terms because they are what a
person can read in a config file. The projects those terms have to match
are written in Persian. Substring matching would therefore never fire:
"bot" does not appear anywhere in "ساخت ربات تلگرام".

So each canonical term carries a pattern covering both spellings, and both
the vocabulary generator and the scorer match through this one table.
Anything the user invents that is not in the table falls back to a literal
match, so a hand-added term still works.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache

# Canonical term -> a pattern covering its Persian and English spellings.
TERM_PATTERNS: dict[str, str] = {
    "telegram bot": r"ربات\s*تلگرام|telegram\s*bot",
    "bot": r"ربات|\bbot\b",
    "react native": r"react\s*native|ری\s*اکت\s*نیتیو",
    "react": r"react|ری\s*اکت|ری‌اکت",
    "node": r"node|نود\s*جی\s*اس|nodejs",
    "express": r"express",
    "next.js": r"next\s*js|nextjs|next\.js",
    "php": r"\bphp\b",
    "python": r"python|پایتون|django|جنگو|flask|فلسک",
    "javascript": r"javascript|جاوااسکریپت|jquery|جی\s*کوئری",
    "website": r"طراحی\s*سایت|وب\s*سایت|website|\bسایت\b",
    "shop": r"فروشگاه|ecommerce|woocommerce|ووکامرس",
    "server": r"سرور|server|لینوکس|linux|\bvps\b|استقرار|deploy",
    "wireguard": r"wireguard|وایرگارد|\bvpn\b",
    "api": r"\bapi\b|وب\s*سرویس|ای\s*پی\s*ای",
    "admin panel": r"پنل|panel|داشبورد|dashboard",
    "scraper": r"استخراج|scrap|crawler|کرالر",
    "database": r"دیتابیس|database|mysql|postgres|mongo|\bsql\b",
    "fullstack": r"فول\s*استک|full\s*-?\s*stack",
    "frontend": r"فرانت|front\s*-?\s*end",
    "backend": r"بک\s*اند|بک‌اند|back\s*-?\s*end",
    "payment gateway": r"درگاه\s*پرداخت|زرین\s*پال|zarinpal|payment",
    "figma": r"فیگما|figma",
    "mobile app": r"اپلیکیشن|موبایل|اندروید|android|\bios\b",
}


@lru_cache(maxsize=512)
def term_regex(term: str) -> re.Pattern:
    """The matcher for one term.

    Known terms use their bilingual pattern. Anything else is escaped and
    matched literally, so a term the user invents behaves sensibly instead
    of being read as a regex.
    """
    pattern = TERM_PATTERNS.get(term.strip().lower())
    if pattern is None:
        pattern = re.escape(term.strip())
    return re.compile(pattern, re.IGNORECASE)


def match_terms(haystack: str, skills: Mapping[str, float]) -> dict[str, float]:
    """Which of these terms appear in this text, and at what weight."""
    if not haystack:
        return {}
    return {
        term: weight
        for term, weight in skills.items()
        if term_regex(term).search(haystack)
    }
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_terms.py -v`
Expected: 10 passed.

- [ ] **Step 5: Write the failing test for the vocabulary**

`tests/test_vocab.py`:

```python
import tomllib

from karyab.vocab import VocabTerm, build_vocabulary, to_toml


def test_bots_are_the_heaviest_term(profile_raw):
    terms = build_vocabulary(profile_raw)
    by_term = {t.term: t for t in terms}

    assert "bot" in by_term
    assert by_term["bot"].wins >= 10
    # The declared skill list never mentions bots; the win record is full of them.
    declared = {s["name"].lower() for s in profile_raw["profile"]["skills"]}
    assert not any("ربات" in d or "bot" in d for d in declared)


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
    unproven = [t for t in terms if not t.proven]

    # express.js is declared on the profile but wins no project by name.
    assert unproven, "declared skills with no wins should still be present"
    for term in unproven:
        assert term.wins == 0
        assert term.weight == 0.35


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
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vocab.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karyab.vocab'`

- [ ] **Step 7: Write the implementation**

`karyab/vocab.py`:

```python
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

# Declared on the profile but winning nothing by name: kept, but quietly.
_UNPROVEN_WEIGHT = 0.35

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
                weight=_UNPROVEN_WEIGHT,
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
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_vocab.py tests/test_terms.py -v`
Expected: 19 passed.

- [ ] **Step 9: Eyeball the generated vocabulary**

```bash
.venv/bin/python -c "
import json
from karyab.vocab import build_vocabulary, to_toml
p = json.load(open('docs/research/profile-65389.json'))
print(to_toml(build_vocabulary(p)))
"
```

Expected: a `[skills]` table with `bot` at or near weight 1.0 and a win count in double digits, plus lower-weighted entries for react, website, server and the rest. Sanity-check that nothing obviously wrong tops the list.

- [ ] **Step 10: Commit**

```bash
git add karyab/terms.py karyab/vocab.py tests/test_terms.py tests/test_vocab.py
git commit -m "Generate the skill vocabulary from won projects

The profile declares seven skills and none of them is 'bot', yet 11 of
29 completed projects are bots. Matching on the declared list would miss
the largest cluster of work the user wins, so terms are derived from
outcomes: five-star wins count full, one-star wins count 0.4, and
declared-but-unwon skills survive at a floor weight."
```

---

### Task 6: Stage one scoring

**Files:**
- Create: `karyab/scoring/__init__.py`
- Create: `karyab/scoring/types.py`
- Create: `karyab/scoring/stage1.py`
- Create: `tests/test_stage1.py`

**Interfaces:**
- Consumes: `karyab.models.Project` (Task 2), `karyab.config.Config` (Task 1), `karyab.terms.match_terms` (Task 5).
- Produces:
  - `karyab.scoring.types.Reason` — frozen dataclass `label: str`, `delta: float`, `fatal: bool = False`.
  - `karyab.scoring.types.Score` — frozen dataclass `value: float`, `reasons: tuple[Reason, ...]`; properties `rejected: bool` (any reason fatal) and `labels: list[str]`; method `with_extra(reasons: Iterable[Reason]) -> Score` returning a re-clamped new Score.
  - `karyab.scoring.stage1.score_listing(project: Project, config: Config) -> Score`.
  - `karyab.scoring.stage1.BASE_SCORE`, `SKILL_MAX`, `SKILL_SATURATION`.

- [ ] **Step 1: Write the failing test**

`tests/test_stage1.py`:

```python
from dataclasses import replace

from karyab.config import Config
from karyab.models import Project
from karyab.scoring.stage1 import score_listing
from karyab.scoring.types import Reason, Score

CFG = replace(
    Config.default(),
    skills={"bot": 1.0, "telegram bot": 0.9, "react": 0.7, "website": 0.5},
)


def _p(**over) -> Project:
    base = {
        "id": 1,
        "url": "slug",
        "title": "ساخت ربات تلگرام دانلودر",
        "description": "",
        "min_budget": 1_000_000,
        "max_budget": 2_000_000,
        "category_id": 6,
        "skills": [],
        "token": 3,
        "low_hire": False,
    }
    base.update(over)
    return Project.from_listing(base)


def test_a_matching_project_scores_well():
    score = score_listing(_p(), CFG)
    assert not score.rejected
    assert score.value > 60


def test_score_is_clamped_to_the_zero_hundred_range():
    score = score_listing(
        _p(title="ربات تلگرام react website", is_urgent=True, is_highlight=True), CFG
    )
    assert 0.0 <= score.value <= 100.0


def test_wrong_category_is_a_hard_reject_with_a_readable_reason():
    score = score_listing(_p(category_id=2), CFG)
    assert score.rejected
    assert any("category" in label.lower() for label in score.labels)


def test_a_blocked_category_is_rejected_even_when_allowed():
    cfg = replace(CFG, categories_allow=(2, 6), categories_block=(2,))
    assert score_listing(_p(category_id=2), cfg).rejected


def test_an_empty_allowlist_permits_every_category():
    cfg = replace(CFG, categories_allow=())
    assert not score_listing(_p(category_id=11), cfg).rejected


def test_a_budget_ceiling_below_the_floor_is_rejected():
    score = score_listing(_p(min_budget=50_000, max_budget=200_000), CFG)
    assert score.rejected
    assert any("budget" in label.lower() for label in score.labels)


def test_an_unknown_budget_is_penalised_not_rejected():
    score = score_listing(_p(min_budget=0, max_budget=0), CFG)
    assert not score.rejected
    assert any("budget" in label.lower() for label in score.labels)


def test_a_project_costing_more_tokens_than_configured_is_rejected():
    cfg = replace(CFG, max_token_cost=4)
    assert score_listing(_p(token=7), cfg).rejected
    assert not score_listing(_p(token=4), cfg).rejected


def test_an_expired_project_is_rejected():
    assert score_listing(_p(is_expired=True), CFG).rejected


def test_no_skill_overlap_is_a_low_score_not_a_rejection():
    score = score_listing(_p(title="ترجمه متن انگلیسی", description=""), CFG)
    assert not score.rejected, "near-misses must stay visible for tuning"
    assert score.value < CFG.threshold
    assert any("skill" in label.lower() for label in score.labels)


def test_an_english_vocabulary_term_matches_a_persian_title():
    # The vocabulary is keyed on English terms; the projects are Persian.
    # A substring matcher would score this zero.
    score = score_listing(_p(title="ساخت ربات تلگرام دانلودر"), CFG)
    assert any("skill match" in l for l in score.labels)
    assert score.value > 60


def test_skills_match_against_the_skills_array_too():
    bare = _p(title="یک پروژه", skills=[])
    tagged = _p(title="یک پروژه", skills=[{"id": 1, "name": "react"}])
    assert score_listing(tagged, CFG).value > score_listing(bare, CFG).value


def test_the_sweet_spot_band_adds_a_bonus_and_can_be_disabled():
    inside = _p(min_budget=800_000, max_budget=2_000_000)
    outside = _p(min_budget=20_000_000, max_budget=35_000_000)

    on = score_listing(inside, CFG).value - score_listing(outside, CFG).value
    off_cfg = replace(CFG, sweet_spot_enabled=False)
    off = score_listing(inside, off_cfg).value - score_listing(outside, off_cfg).value

    assert on > off
    assert any("sweet spot" in l.lower() for l in score_listing(inside, CFG).labels)


def test_a_large_project_outside_the_band_is_still_biddable():
    score = score_listing(_p(min_budget=20_000_000, max_budget=35_000_000), CFG)
    assert not score.rejected, "the band is a bonus, never a cap"


def test_low_hire_costs_points_but_unknown_does_not():
    weak = score_listing(_p(low_hire=True), CFG).value
    unknown = score_listing(_p(low_hire=None), CFG).value
    fine = score_listing(_p(low_hire=False), CFG).value

    assert weak < fine
    assert unknown == fine


def test_urgent_and_highlighted_projects_gain_points():
    plain = score_listing(_p(), CFG).value
    urgent = score_listing(_p(is_urgent=True), CFG).value
    assert urgent > plain


def test_every_reason_carries_a_human_readable_label():
    score = score_listing(_p(), CFG)
    assert score.reasons
    for reason in score.reasons:
        assert reason.label.strip()


def test_score_with_extra_reclamps_and_appends():
    score = Score(value=95.0, reasons=(Reason("base", 95.0),))
    grown = score.with_extra([Reason("bonus", 20.0)])

    assert grown.value == 100.0
    assert len(grown.reasons) == 2
    assert score.value == 95.0, "Score must be immutable"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_stage1.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karyab.scoring'`

- [ ] **Step 3: Write the implementation**

`karyab/scoring/__init__.py`:

```python
"""Pure scoring functions.

Nothing in this package may touch the network, the clock or the disk. The
caller passes in everything, which is what makes the matcher testable and
what lets a score be replayed months later against the same inputs.
"""

from .types import Reason, Score

__all__ = ["Reason", "Score"]
```

`karyab/scoring/types.py`:

```python
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Reason:
    """One contribution to a score, in words the user can act on."""

    label: str
    delta: float
    fatal: bool = False


@dataclass(frozen=True)
class Score:
    value: float
    reasons: tuple[Reason, ...] = ()

    @property
    def rejected(self) -> bool:
        return any(r.fatal for r in self.reasons)

    @property
    def labels(self) -> list[str]:
        return [r.label for r in self.reasons]

    def with_extra(self, reasons: Iterable[Reason]) -> "Score":
        extra = tuple(reasons)
        total = self.value + sum(r.delta for r in extra)
        return Score(value=clamp(total), reasons=self.reasons + extra)


def clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)
```

`karyab/scoring/stage1.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_stage1.py -v`
Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add karyab/scoring/ tests/test_stage1.py
git commit -m "Add stage-one scoring over the listing record

Hard rejects run cheapest-first and return immediately, so most of a
24-row page costs almost nothing. A project with no skill overlap is
scored low rather than rejected, so near-misses stay visible in the
report and the vocabulary can be tuned against real ones. The sweet-spot
band is a bonus and never a cap: large projects stay biddable."
```

---

### Task 7: Stage two scoring

**Files:**
- Create: `karyab/scoring/stage2.py`
- Create: `tests/test_stage2.py`

**Interfaces:**
- Consumes: `Score`/`Reason` (Task 6), `Project`/`ProjectDetail` (Task 2), `Config` (Task 1).
- Produces: `karyab.scoring.stage2.score_detail(base: Score, project: Project, detail: ProjectDetail, config: Config, *, now: datetime, first_seen_at: datetime) -> Score`.

- [ ] **Step 1: Write the failing test**

`tests/test_stage2.py`:

```python
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from karyab.config import Config
from karyab.models import Project, ProjectDetail
from karyab.scoring.stage2 import score_detail
from karyab.scoring.types import Reason, Score

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
CFG = Config.default()
BASE = Score(value=60.0, reasons=(Reason("base", 60.0),))

PROJECT = Project.from_listing(
    {"id": 1, "url": "s", "title": "t", "category_id": 6, "max_budget": 2_000_000}
)


def _detail(**over) -> ProjectDetail:
    kwargs = {
        "id": 1,
        "created_at": NOW - timedelta(minutes=5),
        "hire_deadline": NOW + timedelta(days=30),
        "file_count": 0,
        "description": "a" * 120,
    }
    kwargs.update(over)
    return ProjectDetail(**kwargs)


def _score(detail: ProjectDetail, *, now=NOW, first_seen=None) -> Score:
    return score_detail(
        BASE,
        PROJECT,
        detail,
        CFG,
        now=now,
        first_seen_at=first_seen or (now - timedelta(minutes=5)),
    )


def test_a_brand_new_project_gains_the_most():
    fresh = _score(_detail(created_at=NOW - timedelta(minutes=3)))
    older = _score(_detail(created_at=NOW - timedelta(hours=6)))
    assert fresh.value > older.value
    assert any("fresh" in l.lower() or "minute" in l.lower() for l in fresh.labels)


def test_a_stale_project_loses_points():
    stale = _score(_detail(created_at=NOW - timedelta(days=3)))
    assert stale.value < BASE.value


def test_freshness_falls_back_to_first_seen_when_created_at_is_missing():
    scored = _score(
        _detail(created_at=None),
        first_seen=NOW - timedelta(minutes=2),
    )
    assert scored.value > BASE.value


def test_the_persian_relative_string_is_never_consulted():
    # ProjectDetail has no past_time field at all; this is a guard against
    # anyone adding one and parsing it.
    assert not hasattr(_detail(), "past_time")


def test_an_attached_brief_is_a_bonus():
    with_files = _score(_detail(file_count=2))
    without = _score(_detail(file_count=0))
    assert with_files.value > without.value
    assert any("file" in l.lower() or "brief" in l.lower() for l in with_files.labels)


def test_a_detailed_description_beats_a_one_liner():
    detailed = _score(_detail(description="x" * 400))
    thin = _score(_detail(description="کمک"))
    assert detailed.value > thin.value


def test_an_imminent_hiring_deadline_costs_points():
    soon = _score(_detail(hire_deadline=NOW + timedelta(hours=12)))
    later = _score(_detail(hire_deadline=NOW + timedelta(days=20)))
    assert soon.value < later.value


def test_a_missing_deadline_is_neutral():
    none = _score(_detail(hire_deadline=None))
    later = _score(_detail(hire_deadline=NOW + timedelta(days=20)))
    assert none.value == later.value


def test_stage_two_keeps_the_stage_one_reasons():
    scored = _score(_detail())
    assert scored.reasons[0].label == "base"
    assert len(scored.reasons) > 1


def test_a_rejected_stage_one_score_stays_rejected():
    rejected = Score(value=0.0, reasons=(Reason("category blocked", 0.0, fatal=True),))
    scored = score_detail(
        rejected,
        PROJECT,
        _detail(),
        CFG,
        now=NOW,
        first_seen_at=NOW,
    )
    assert scored.rejected
    assert scored.value == 0.0


def test_naive_timestamps_do_not_crash_the_scorer():
    naive = _detail(created_at=datetime(2026, 9, 1, 11, 55))
    scored = _score(naive)
    assert 0.0 <= scored.value <= 100.0


def test_the_result_stays_within_range():
    scored = _score(_detail(created_at=NOW, file_count=9, description="y" * 5000))
    assert 0.0 <= scored.value <= 100.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_stage2.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karyab.scoring.stage2'`

- [ ] **Step 3: Write the implementation**

`karyab/scoring/stage2.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_stage2.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add karyab/scoring/stage2.py tests/test_stage2.py
git commit -m "Add stage-two scoring over the detail record

Freshness is the steepest signal: no public field exposes how many
freelancers have already bid, so arriving early is the only available
defence against competition. created_at is preferred and first_seen_at
is the fallback; the Persian relative-time string is never parsed."
```

---

### Task 8: Scan orchestration

**Files:**
- Create: `karyab/scan.py`
- Create: `tests/test_scan.py`

**Interfaces:**
- Consumes: `KarlancerClient` (Task 3), `Store` (Task 4), `Config` (Task 1), `Project`/`ProjectDetail` (Task 2), `score_listing` (Task 6), `score_detail` (Task 7).
- Produces:
  - `karyab.scan.ScanResult` — frozen dataclass with `seen: int`, `new: int`, `rejected: int`, `promoted: int`, `detail_fetches: int`, `errors: tuple[str, ...]`.
  - `karyab.scan.run_scan(client, store, config, *, now, pages: int = 1, sleep=None, detail_cutoff: float | None = None) -> ScanResult`.
  - `karyab.scan.DETAIL_CUTOFF_MARGIN`.

**Design note:** stage two costs one HTTP request per project, so it runs only for projects whose stage-one score is already within `DETAIL_CUTOFF_MARGIN` of the threshold. A project scoring far below the threshold cannot be rescued by a freshness bonus, so fetching its detail would be wasted.

- [ ] **Step 1: Write the failing test**

`tests/test_scan.py`:

```python
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from karyab.api import ApiError
from karyab.config import Config
from karyab.scan import run_scan
from karyab.store import Store

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

CFG = replace(
    Config.default(),
    skills={"bot": 1.0, "react": 0.8, "website": 0.6, "server": 0.5},
)


class FakeClient:
    """Stands in for KarlancerClient without touching the network."""

    def __init__(self, pages, detail=None, detail_error=False):
        self.pages = pages
        self._detail = detail or {}
        self.detail_error = detail_error
        self.detail_calls = []
        self.page_calls = []

    def search_projects(self, page: int = 1):
        self.page_calls.append(page)
        return self.pages.get(page, [])

    def project_detail(self, slug: str):
        self.detail_calls.append(slug)
        if self.detail_error:
            raise ApiError("detail exploded")
        return dict(self._detail, url=slug)


def test_a_scan_stores_every_project_it_sees(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows})

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=1)
        stored = store.latest_scores(limit=100)

    assert result.seen == 24
    assert result.new == 24
    assert len(stored) == 24, "rejects are stored too, not discarded"


def test_rescanning_the_same_page_finds_nothing_new(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows})

    with Store(tmp_path / "k.db") as store:
        run_scan(client, store, CFG, now=NOW, pages=1)
        again = run_scan(client, store, CFG, now=NOW + timedelta(minutes=5), pages=1)

    assert again.seen == 24
    assert again.new == 0


def test_off_category_projects_are_rejected_with_reasons(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows})

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=1)
        stored = store.latest_scores(limit=100)

    assert result.rejected > 0
    for row in stored:
        if row["rejected"]:
            assert row["reasons"], "a rejection must say why"


def test_detail_is_fetched_only_for_plausible_candidates(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows}, detail={"id": 1, "created_at": None, "files": []})

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=1)

    assert result.detail_fetches == len(client.detail_calls)
    assert result.detail_fetches < 24, "stage two must not run on every row"


def test_a_detail_failure_does_not_abort_the_scan(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows}, detail_error=True)

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=1)
        stored = store.latest_scores(limit=100)

    assert result.seen == 24
    assert result.errors, "the failure should be reported, not swallowed"
    assert len(stored) == 24


def test_a_page_failure_is_reported_and_the_scan_continues(tmp_path, listing_page):
    rows = listing_page["data"]["data"]

    class Flaky(FakeClient):
        def search_projects(self, page: int = 1):
            if page == 1:
                raise ApiError("page one is down")
            return super().search_projects(page)

    client = Flaky({2: rows})

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=2)

    assert result.errors
    assert result.seen == 24


def test_multiple_pages_are_walked_in_order(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows[:12], 2: rows[12:]})

    with Store(tmp_path / "k.db") as store:
        run_scan(client, store, CFG, now=NOW, pages=2)

    assert client.page_calls == [1, 2]


def test_the_scan_sleeps_between_requests(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient({1: rows[:2], 2: rows[2:4]}, detail={"id": 1, "files": []})
    slept = []

    with Store(tmp_path / "k.db") as store:
        run_scan(client, store, CFG, now=NOW, pages=2, sleep=slept.append)

    assert slept, "requests to karlancer.com must be paced"
    assert all(s > 0 for s in slept)


def test_promoted_projects_clear_the_threshold(tmp_path, listing_page):
    rows = listing_page["data"]["data"]
    client = FakeClient(
        {1: rows},
        detail={"id": 1, "created_at": "2026-09-01T11:55:00.000000Z", "files": []},
    )

    with Store(tmp_path / "k.db") as store:
        result = run_scan(client, store, CFG, now=NOW, pages=1)
        stored = store.latest_scores(limit=100)

    clearing = [r for r in stored if not r["rejected"] and r["value"] >= CFG.threshold]
    assert result.promoted == len(clearing)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_scan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karyab.scan'`

- [ ] **Step 3: Write the implementation**

`karyab/scan.py`:

```python
"""One pass over the feed: fetch, score, store.

This is the only module in Phase 1 that performs I/O and holds the clock,
which keeps the scorers pure. A failure on one project or one page is
recorded and stepped over: a single bad record must never stop the feed.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
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
            store.record_score(
                project.id, 1, score.value, score.rejected, score.labels, now
            )

            if score.rejected:
                rejected += 1
                continue

            if score.value < cutoff:
                continue

            pause(random.uniform(_MIN_DELAY, _MAX_DELAY))
            try:
                detail_raw = client.project_detail(project.slug)
                detail_fetches += 1
            except ApiError as exc:
                errors.append(f"detail {project.slug}: {exc}")
                if score.value >= config.threshold:
                    promoted += 1
                continue

            detail = ProjectDetail.from_detail(detail_raw)
            refined = score_detail(
                score,
                project,
                detail,
                config,
                now=now,
                first_seen_at=first_seen_at,
            )
            store.record_score(
                project.id, 2, refined.value, refined.rejected, refined.labels, now
            )
            if refined.value >= config.threshold:
                promoted += 1

    return ScanResult(
        seen=seen,
        new=new,
        rejected=rejected,
        promoted=promoted,
        detail_fetches=detail_fetches,
        errors=tuple(errors),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_scan.py -v`
Expected: 9 passed.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all tests pass, no errors.

- [ ] **Step 6: Commit**

```bash
git add karyab/scan.py tests/test_scan.py
git commit -m "Add scan orchestration

The only module holding I/O and the clock, which is what keeps the
scorers pure. Stage two runs only for projects within reach of the
threshold, since a detail fetch costs a request and cannot rescue a
score 25 points short. A failed page or detail is recorded and stepped
over rather than aborting the pass."
```

---

### Task 9: The CLI and the dry-run report

**Files:**
- Create: `karyab/cli.py`
- Create: `tests/test_cli.py`
- Modify: `README.md` (create)

**Interfaces:**
- Consumes: everything above.
- Produces: `karyab.cli.main(argv: list[str] | None = None) -> int` with subcommands `init`, `vocab`, `scan`, `report`; and `karyab.cli.render_report(rows: list[dict], *, threshold: float, show_rejected: bool) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
import json
from pathlib import Path

from karyab.cli import main, render_report


def _rows():
    return [
        {
            "project_id": 1,
            "stage": 2,
            "value": 78.0,
            "rejected": False,
            "reasons": ["base", "skill match: bot", "posted in the last 10 minutes"],
            "title": "ساخت ربات تلگرام فروشگاهی",
            "slug": "sakht-robot-abc",
            "min_budget": 1_000_000,
            "max_budget": 3_000_000,
            "token": 3,
            "category_id": 6,
            "first_seen_at": "2026-09-01T12:00:00+00:00",
            "scored_at": "2026-09-01T12:00:00+00:00",
        },
        {
            "project_id": 2,
            "stage": 1,
            "value": 0.0,
            "rejected": True,
            "reasons": ["category 2 is not in the allowlist [6]"],
            "title": "طراحی لوگو",
            "slug": "logo-xyz",
            "min_budget": 500_000,
            "max_budget": 2_000_000,
            "token": 2,
            "category_id": 2,
            "first_seen_at": "2026-09-01T12:00:00+00:00",
            "scored_at": "2026-09-01T12:00:00+00:00",
        },
    ]


def test_the_report_shows_candidates_with_their_reasons():
    text = render_report(_rows(), threshold=55.0, show_rejected=False)

    assert "ربات تلگرام" in text
    assert "78" in text
    assert "skill match: bot" in text
    assert "3 tokens" in text or "tokens: 3" in text


def test_rejected_projects_are_hidden_by_default_and_shown_on_request():
    hidden = render_report(_rows(), threshold=55.0, show_rejected=False)
    shown = render_report(_rows(), threshold=55.0, show_rejected=True)

    assert "طراحی لوگو" not in hidden
    assert "طراحی لوگو" in shown
    assert "not in the allowlist" in shown


def test_the_report_links_each_project():
    text = render_report(_rows(), threshold=55.0, show_rejected=False)
    assert "karlancer.com" in text
    assert "sakht-robot-abc" in text


def test_an_empty_report_says_so_rather_than_printing_nothing():
    text = render_report([], threshold=55.0, show_rejected=False)
    assert text.strip()


def test_init_writes_a_config_seeded_from_the_profile(tmp_path, capsys):
    cfg_path = tmp_path / "config.toml"
    profile = Path("docs/research/profile-65389.json")

    code = main(["init", "--config", str(cfg_path), "--profile", str(profile)])

    assert code == 0
    assert cfg_path.exists()
    body = cfg_path.read_text(encoding="utf-8")
    assert "[skills]" in body
    assert "categories_allow" in body

    from karyab.config import Config

    cfg = Config.load(cfg_path)
    assert cfg.skills, "the generated config must carry a skill vocabulary"
    assert cfg.categories_allow == (6,)


def test_init_refuses_to_clobber_an_existing_config(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("min_budget = 1\n", encoding="utf-8")
    profile = Path("docs/research/profile-65389.json")

    code = main(["init", "--config", str(cfg_path), "--profile", str(profile)])

    assert code != 0
    assert cfg_path.read_text(encoding="utf-8") == "min_budget = 1\n"


def test_vocab_prints_a_skills_table(tmp_path, capsys):
    code = main(["vocab", "--profile", "docs/research/profile-65389.json"])
    out = capsys.readouterr().out

    assert code == 0
    assert "[skills]" in out
    assert "bot" in out


def test_report_reads_the_database(tmp_path, capsys):
    from datetime import datetime, timezone

    from karyab.models import Project
    from karyab.store import Store

    db = tmp_path / "k.db"
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    project = Project.from_listing(
        {"id": 5, "url": "s", "title": "ربات", "category_id": 6, "max_budget": 2_000_000}
    )
    with Store(db) as store:
        store.first_seen(project, now)
        store.record_score(5, 1, 80.0, False, ["skill match: bot"], now)

    code = main(["report", "--db", str(db)])
    out = capsys.readouterr().out

    assert code == 0
    assert "ربات" in out


def test_unknown_command_exits_nonzero(capsys):
    try:
        main(["nonsense"])
    except SystemExit as exc:
        assert exc.code != 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karyab.cli'`

- [ ] **Step 3: Write the implementation**

`karyab/cli.py`:

```python
"""Phase 1 command line: init, vocab, scan, report.

Nothing here submits anything. The whole point of this phase is to watch
what the matcher *would* do, for free, before an LLM or a browser is
wired in.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .api import KarlancerClient
from .config import Config, default_config_path
from .scan import run_scan
from .store import Store
from .vocab import build_vocabulary, to_toml

PROJECT_URL = "https://www.karlancer.com/project/{slug}"


def default_db_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "karyab" / "karyab.db"


def _toman(value: int) -> str:
    return f"{value:,}" if value else "?"


def render_report(rows: list[dict], *, threshold: float, show_rejected: bool) -> str:
    visible = [r for r in rows if show_rejected or not r["rejected"]]
    if not visible:
        return "Nothing to show yet. Run `karyab scan` first.\n"

    lines: list[str] = []
    for row in visible:
        mark = "REJECTED" if row["rejected"] else (
            "CANDIDATE" if row["value"] >= threshold else "below threshold"
        )
        lines.append(f"[{row['value']:5.1f}] {mark}  {row['title']}")
        lines.append(
            f"         {_toman(row['min_budget'])}-{_toman(row['max_budget'])} toman"
            f"  ·  {row['token']} tokens  ·  stage {row['stage']}"
        )
        lines.append(f"         {PROJECT_URL.format(slug=row['slug'])}")
        for reason in row["reasons"]:
            lines.append(f"           - {reason}")
        lines.append("")

    shown = len(visible)
    candidates = sum(
        1 for r in visible if not r["rejected"] and r["value"] >= threshold
    )
    lines.append(f"{shown} shown, {candidates} at or above the threshold of {threshold}.")
    return "\n".join(lines) + "\n"


def _load_config(path: Path) -> Config:
    if path.exists():
        return Config.load(path)
    print(f"No config at {path}; using defaults. Run `karyab init` to create one.",
          file=sys.stderr)
    return Config.default()


def cmd_init(args) -> int:
    cfg_path = Path(args.config)
    if cfg_path.exists():
        print(f"{cfg_path} already exists; refusing to overwrite it.", file=sys.stderr)
        return 1

    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    terms = build_vocabulary(profile)
    defaults = Config.default()

    body = f"""# karyab configuration
# Edit freely. Every value here is a default measured from your own
# completed projects, not a guess -- see docs/superpowers/specs/.

# Category 6 is برنامه نویسی. All 29 of your completed projects are category 6.
categories_allow = {list(defaults.categories_allow)}
categories_block = []

# A project whose ceiling is below this is not worth spending a token on.
min_budget = {defaults.min_budget}

# Where your five-star outcomes cluster. A scoring bonus, never a cap:
# larger projects stay biddable, they just start lower.
sweet_spot = {list(defaults.sweet_spot)}
sweet_spot_bonus = {defaults.sweet_spot_bonus}
sweet_spot_enabled = {str(defaults.sweet_spot_enabled).lower()}

max_token_cost = {defaults.max_token_cost}
threshold = {defaults.threshold}
daily_cap = {defaults.daily_cap}
poll_seconds = {defaults.poll_seconds}

# Generated from the projects you actually won. Weights are relative to
# your strongest term. Adjust anything that looks wrong -- this is the
# single biggest lever on which projects surface.
{to_toml(terms)}"""

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(body, encoding="utf-8")
    print(f"Wrote {cfg_path} with {len(terms)} skill terms.")
    print("Read the [skills] table and correct anything that looks wrong.")
    return 0


def cmd_vocab(args) -> int:
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    terms = build_vocabulary(profile)
    print(to_toml(terms), end="")
    return 0


def cmd_scan(args) -> int:
    config = _load_config(Path(args.config))
    now = datetime.now(timezone.utc)

    with Store(args.db) as store, KarlancerClient() as client:
        result = run_scan(client, store, config, now=now, pages=args.pages)
        rows = store.latest_scores(limit=args.limit)

    print(
        f"Saw {result.seen} projects ({result.new} new), "
        f"rejected {result.rejected}, "
        f"fetched {result.detail_fetches} details, "
        f"{result.promoted} cleared the threshold."
    )
    for error in result.errors:
        print(f"  ! {error}", file=sys.stderr)
    print()
    print(render_report(rows, threshold=config.threshold, show_rejected=args.rejected))
    return 0


def cmd_report(args) -> int:
    config = _load_config(Path(args.config))
    with Store(args.db) as store:
        rows = store.latest_scores(limit=args.limit)
    print(render_report(rows, threshold=config.threshold, show_rejected=args.rejected),
          end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="karyab",
        description="Watch karlancer.com and report what is worth bidding on.",
    )
    parser.add_argument("--config", default=str(default_config_path()))
    parser.add_argument("--db", default=str(default_db_path()))
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="write a config seeded from your profile")
    p_init.add_argument("--profile", default="docs/research/profile-65389.json")
    p_init.set_defaults(func=cmd_init)

    p_vocab = sub.add_parser("vocab", help="print the skill table for your config")
    p_vocab.add_argument("--profile", default="docs/research/profile-65389.json")
    p_vocab.set_defaults(func=cmd_vocab)

    p_scan = sub.add_parser("scan", help="poll the feed, score it, and report")
    p_scan.add_argument("--pages", type=int, default=1)
    p_scan.add_argument("--limit", type=int, default=30)
    p_scan.add_argument("--rejected", action="store_true", help="include rejects")
    p_scan.set_defaults(func=cmd_scan)

    p_report = sub.add_parser("report", help="show what the last scans decided")
    p_report.add_argument("--limit", type=int, default=30)
    p_report.add_argument("--rejected", action="store_true")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: 9 passed.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Run it against the live feed**

```bash
.venv/bin/python -m karyab.cli init --config ./config.toml --profile docs/research/profile-65389.json
.venv/bin/python -m karyab.cli --config ./config.toml --db ./karyab.db scan --pages 2
```

Expected: a summary line, then a ranked list of real projects with reasons. Read the top ten and check the picks make sense. If off-target projects rank highly, fix the weights in `./config.toml` and re-run `report` — no re-scan needed, the scores are stored.

- [ ] **Step 7: Write the README**

`README.md`:

```markdown
# کاریاب / karyab

Watches karlancer.com's public project feed, scores each project against the
skills you have actually been paid for, and reports what is worth bidding on
and why.

Phase 1 is read-only. It makes no LLM calls, drives no browser, and submits
nothing.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m karyab.cli init
```

`init` writes a config seeded from your own completed projects. Read the
`[skills]` table it generates and correct anything that looks wrong — those
weights decide which projects surface.

## Use

```bash
karyab scan --pages 2        # poll, score, store, report
karyab report --rejected     # what was skipped, and why
karyab vocab                 # regenerate the skill table
```

## Tuning

Scores are stored, so re-reading them is free. Edit `config.toml`, run
`karyab report`, and look at what moved. `--rejected` shows near-misses, which
is where a missing skill term usually announces itself.

## Design

`docs/superpowers/specs/2026-08-31-karyab-design.md` — the whole system.
`docs/superpowers/plans/2026-09-01-karyab-phase-1.md` — this phase, task by task.
```

- [ ] **Step 8: Commit**

```bash
git add karyab/cli.py tests/test_cli.py README.md
git commit -m "Add the Phase 1 CLI and dry-run report

init seeds a config from the user's own won projects and refuses to
overwrite an existing one. The report prints every reason behind a score,
including rejections, because tuning the matcher means reading what it
threw away. Nothing here submits anything."
```

---

## Definition of done

Phase 1 is finished when all of the following hold:

- [ ] `.venv/bin/python -m pytest -q` passes with no failures and no errors.
- [ ] `karyab init` produces a config whose `[skills]` table is generated from the 29 completed projects, with `bot` among the highest-weighted terms.
- [ ] `karyab scan --pages 2` runs against the live API, stores ~48 projects, and prints a ranked report with reasons.
- [ ] Rejected projects appear under `karyab report --rejected` with a readable reason each.
- [ ] No module under `karyab/scoring/` imports `httpx`, `time`, `datetime.now`, or `pathlib`. (`karyab.terms` is fine — it is pure.)
- [ ] Nothing in the codebase parses `past_time`, reads `users_bid`, or reads `successful_projects_percentage`.
- [ ] The user has read the top ten of a real report and confirmed the picks are sensible.

Verify the two mechanical invariants with:

```bash
grep -rn "past_time\|users_bid\|successful_projects_percentage" karyab/ && echo "FAIL: dead signal referenced" || echo "ok: no dead signals"
grep -rn "import httpx\|^import time\|datetime.now\|from pathlib" karyab/scoring/ && echo "FAIL: impurity in scoring" || echo "ok: scoring is pure"
```

## What Phase 1 deliberately does not do

No proposal text is generated, no Claude API key is needed, no browser is
installed, and nothing is ever submitted. Those arrive in Phases 2-4, once the
matcher has been proven against real listings at zero cost.
