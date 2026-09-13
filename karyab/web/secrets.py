"""On-disk storage for the Anthropic API key.

The key is entered through the dashboard rather than an environment variable,
which means karyab is responsible for holding it safely:

  * written 0600, created that way rather than chmod-ed afterwards, so there
    is never a moment where it sits world-readable
  * stored under XDG data, never in the repository
  * masked everywhere it is displayed, and never logged
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# Anthropic keys look like sk-ant-<something long>. Checked only to catch an
# obvious paste error early — the real test is a live call.
_KEY_SHAPE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$")


class ApiKeyInvalid(ValueError):
    """The supplied string is not shaped like an Anthropic API key."""


def default_secrets_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "karyab" / "secrets.json"


def _write_private(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def save_api_key(key: str, *, path: Path | None = None) -> Path:
    target = Path(path) if path else default_secrets_path()
    cleaned = (key or "").strip()
    if not _KEY_SHAPE.match(cleaned):
        raise ApiKeyInvalid(
            "That does not look like an Anthropic API key. They start with "
            "'sk-ant-' and are long. Copy it from console.anthropic.com."
        )
    _write_private(target, {"anthropic_api_key": cleaned})
    return target


def load_api_key(*, path: Path | None = None) -> str | None:
    target = Path(path) if path else default_secrets_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    key = data.get("anthropic_api_key")
    return key.strip() if isinstance(key, str) and key.strip() else None


def clear_api_key(*, path: Path | None = None) -> None:
    target = Path(path) if path else default_secrets_path()
    target.unlink(missing_ok=True)


def mask_api_key(key: str | None) -> str:
    """Enough to recognise which key it is; never enough to use it."""
    if not key:
        return "not set"
    return f"sk-ant-…{key[-4:]}"
