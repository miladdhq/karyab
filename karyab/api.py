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
