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
