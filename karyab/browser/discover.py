"""One-time reconnaissance of the authenticated surface.

Karlancer's chat and bid endpoints are not in the public bundle in any form
static analysis could pin down, so they are discovered the honest way: drive
the logged-in app, record every XHR it makes, and report the API calls it
used. The output shapes the harvest implementation.

Read-only. Navigates and records; it never clicks anything that submits.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from .session import load_context

# Panel routes worth walking. Chat lives behind one of these.
ROUTES = (
    "https://www.karlancer.com/panel/projects",
    "https://www.karlancer.com/panel/messages",
    "https://www.karlancer.com/panel/chat",
    "https://www.karlancer.com/panel/bids",
    "https://www.karlancer.com/panel/dashboard",
)


def discover(out_path: Path, *, routes=ROUTES, headless: bool = True) -> dict:
    """Visit each route, record the API calls it makes, save a report."""
    from playwright.sync_api import sync_playwright

    seen: dict[str, dict] = {}

    with sync_playwright() as p:
        browser, context = load_context(p, headless=headless)
        page = context.new_page()

        def on_response(response) -> None:
            url = response.url
            if "/api/" not in url:
                return
            path = urlsplit(url).path
            entry = seen.setdefault(
                path,
                {"path": path, "status": response.status, "methods": set(),
                 "samples": [], "shape": None},
            )
            entry["methods"].add(response.request.method)
            if len(entry["samples"]) < 1 and response.status == 200:
                try:
                    body = response.json()
                except Exception:
                    return
                entry["shape"] = _shape(body)
                entry["samples"].append(_truncate(body))

        page.on("response", on_response)

        for route in routes:
            try:
                page.goto(route, wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(1500)
            except Exception as exc:  # a dead route must not stop discovery
                seen.setdefault(f"!route {route}", {"error": str(exc)[:120]})

        browser.close()

    report = {
        path: {**info, "methods": sorted(info.get("methods", []))}
        for path, info in sorted(seen.items())
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    return report


def _shape(value, depth: int = 0):
    """A compact description of a JSON body's structure, not its contents."""
    if depth > 3:
        return "..."
    if isinstance(value, dict):
        return {k: _shape(v, depth + 1) for k, v in list(value.items())[:20]}
    if isinstance(value, list):
        return [_shape(value[0], depth + 1), f"...x{len(value)}"] if value else []
    return type(value).__name__


def _truncate(value, limit: int = 400):
    text = json.dumps(value, ensure_ascii=False)
    return text[:limit] + ("..." if len(text) > limit else "")
