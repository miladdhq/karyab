"""Persisted login session for karlancer.com.

Karlancer's `/api/login` refuses every field shape tried against it, so the
login is not reverse-engineered: the user signs in themselves in a real
browser and the resulting cookies are saved. That also survives the OTP and
Google paths the login page offers, and means a bid later placed through
this session is indistinguishable from one the user placed by hand.
"""

from __future__ import annotations

import os
from pathlib import Path

# Chrome is already installed on this machine, so Playwright drives it
# directly rather than downloading its own ~150MB Chromium.
BROWSER_CHANNEL = "chrome"

# Chromium reads the desktop's proxy configuration, not just the environment,
# so unsetting ALL_PROXY in the parent process is not enough: page navigation
# still goes through the machine's SOCKS proxy and times out on domestic
# Iranian sites. Forcing a direct connection makes the browser behave like the
# rest of karyab, which sets trust_env=False for the same reason.
# `proxy={"server": "direct://"}` is NOT the way to do this: Playwright's
# request context tries to resolve "direct" as a hostname and fails with
# EAI_AGAIN. Chromium's own flag is the reliable mechanism.
LAUNCH_ARGS = {"args": ["--no-proxy-server"]}


def _launch_kwargs(headless: bool) -> dict:
    """Launch options. install.sh sets BROWSER_CHANNEL to None on machines
    without Chrome, in which case Playwright's own Chromium is used."""
    kwargs = {"headless": headless, **LAUNCH_ARGS}
    if BROWSER_CHANNEL:
        kwargs["channel"] = BROWSER_CHANNEL
    return kwargs

LOGIN_URL = "https://www.karlancer.com/login"
PANEL_URL = "https://www.karlancer.com/panel/projects"

# Probe endpoint: returns 200 with a session, 401 without one.
# /api/projects returns 403 even for a valid session; /api/dashboard is the
# endpoint the logged-in panel itself calls first.
AUTH_PROBE = "https://www.karlancer.com/api/dashboard"


def default_session_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "karyab" / "session.json"


SESSION_PATH = default_session_path()


class SessionExpired(RuntimeError):
    """The saved session no longer authenticates."""


def _write_private(path: Path, text: str) -> None:
    """Write a secret to disk without ever exposing it at mode 644."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with 0600 from the outset rather than chmod-ing afterwards,
    # which would leave a window where the cookies are world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def save_session(path: Path | None = None, *, timeout_seconds: int = 300) -> Path:
    """Open a visible browser, wait for the user to log in, save the session.

    Blocks until the browser reports an authenticated session or the timeout
    expires. Nothing is typed on the user's behalf.
    """
    from playwright.sync_api import sync_playwright

    target = Path(path) if path else SESSION_PATH

    with sync_playwright() as p:
        browser = p.chromium.launch(**_launch_kwargs(headless=False))
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print("A browser window is open. Log in to Karlancer there.")
        print("karyab never sees your password — you type it into the real site.")
        print(f"Waiting up to {timeout_seconds // 60} minutes...")

        deadline = timeout_seconds * 1000
        try:
            # The panel route is only reachable once authenticated.
            page.wait_for_url("**/panel/**", timeout=deadline)
        except Exception:
            # Fall back to probing the API: the user may have landed elsewhere.
            if not _context_is_authenticated(context):
                browser.close()
                raise SessionExpired(
                    "Timed out before a logged-in session appeared. "
                    "Nothing was saved."
                )

        state = context.storage_state()
        browser.close()

    import json

    _write_private(target, json.dumps(state, ensure_ascii=False))
    return target


def _context_is_authenticated(context) -> bool:
    """True if this context can actually read authenticated data.

    Checking for HTTP 200 alone is not a test: without `Accept:
    application/json` the API serves the Angular shell as 200 text/html, so a
    logged-out session passes. The real test is a JSON body carrying the
    bearer token from localStorage.
    """
    try:
        state = context.storage_state()
    except Exception:
        return False

    try:
        from .authed import bearer_header, extract_token
        headers = bearer_header(extract_token(state))
    except Exception:
        return False

    try:
        response = context.request.get(AUTH_PROBE, headers=headers)
    except Exception:
        return False

    if response.status != 200:
        return False
    ctype = (response.headers.get("content-type") or "").lower()
    return "json" in ctype


def load_context(playwright, path: Path | None = None, *, headless: bool = True):
    """Launch a browser carrying the saved session.

    Raises SessionExpired if no session is stored or it no longer works, so
    callers stop rather than silently scraping logged-out pages.
    """
    target = Path(path) if path else SESSION_PATH
    if not target.exists():
        raise SessionExpired(
            f"No saved session at {target}. Run `karyab login` first."
        )

    browser = playwright.chromium.launch(**_launch_kwargs(headless=headless))
    context = browser.new_context(storage_state=str(target))
    if not _context_is_authenticated(context):
        browser.close()
        raise SessionExpired(
            f"The session at {target} no longer authenticates. "
            "Run `karyab login` again."
        )
    return browser, context
