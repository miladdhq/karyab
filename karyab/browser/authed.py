"""Authenticated access to Karlancer's private API.

Two things about this API are easy to get wrong, and both fail quietly:

  * **Cookies are not enough.** The session cookies get you the Angular shell,
    served as HTTP 200 with `text/html`. Nothing raises; a parser just finds
    HTML where it expected JSON.
  * **`Accept: application/json` alone is not enough either** — that returns
    401. The API wants a Laravel Sanctum bearer token, which the app keeps as
    the `access_token` field of a JSON blob in `localStorage["auth-token"]`.

So both headers are always sent together, from one place.
"""

from __future__ import annotations

import json
import re
from typing import Any

AUTH_TOKEN_KEY = "auth-token"

# Laravel Sanctum tokens look like "3755630|<hash>". This checks only for that
# shape — enough to tell a real bare token from a garbled value, without
# guessing at a hash length the server is free to change.
_SANCTUM_RE = re.compile(r"^\d+\|\S+$")


class AuthTokenMissing(RuntimeError):
    """The saved session carries no usable API token."""


def extract_token(storage_state: dict[str, Any]) -> tuple[str, str]:
    """Pull (token_type, access_token) out of a Playwright storage state."""
    raw = None
    for origin in storage_state.get("origins") or []:
        for item in origin.get("localStorage") or []:
            if item.get("name") == AUTH_TOKEN_KEY:
                raw = item.get("value")
                break

    if not raw:
        raise AuthTokenMissing(
            f"No {AUTH_TOKEN_KEY!r} in the saved session. Run `karyab login` again."
        )

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        # The app wraps the token in JSON today; tolerate a bare string in case
        # that ever changes rather than failing on a token we can plainly see.
        token = str(raw).strip().strip('"')
        # Tolerate a bare token in case the app stops wrapping it in JSON, but
        # only when it actually looks like one. Accepting arbitrary text here
        # would turn a corrupt session into a confusing 401 later instead of a
        # clear error now.
        if not _SANCTUM_RE.match(token):
            raise AuthTokenMissing(
                "The stored auth token is neither valid JSON nor a recognisable "
                "token. Run `karyab login` again."
            ) from None
        return "Bearer", token

    if not isinstance(parsed, dict):
        raise AuthTokenMissing("The stored auth token has an unexpected shape.")

    token = str(parsed.get("access_token") or "").strip()
    if not token:
        raise AuthTokenMissing(
            "The stored auth token has no access_token. Run `karyab login` again."
        )
    return str(parsed.get("token_type") or "Bearer"), token


def bearer_header(token: tuple[str, str]) -> dict[str, str]:
    """The two headers every authenticated request needs."""
    token_type, value = token
    value = value.strip()
    prefix = f"{token_type} "
    authorization = value if value.startswith(prefix) else f"{token_type} {value}"
    return {"Accept": "application/json", "Authorization": authorization}
