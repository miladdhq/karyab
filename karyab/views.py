"""Ways of looking at the queue.

Each view answers a different question the user actually has, rather than
being a generic filter menu:

  همه          what is there at all
  کاندیداها     what is worth bidding on right now
  تازه‌ترین      what just appeared — the only edge available, since no public
               field says how many freelancers have already bid
  ربات‌ها       the user's strongest cluster: 11 of their 29 wins are bots
  بودجه بالا    the big money, which their history says is also the risky end
  کم‌هزینه      cheapest to bid on, for stretching a token balance
  پیش‌نویس‌دار   already drafted, waiting to be sent
  ردشده‌ها      what was skipped, and why — the tuning surface

Pure functions over a list of queue rows: no I/O, no clock of their own.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# The bot cluster, in both scripts. Worth its own view because it is where
# this user actually wins: 11 of 29 completed projects, six of them Telegram.
_BOT = re.compile(r"\bbot\b|telegram bot|ربات|بات\b|تلگرام", re.IGNORECASE)

VIEWS: dict[str, dict[str, str]] = {
    "all": {"label": "همه", "hint": "هر پروژه‌ای که دیده و امتیاز داده شده"},
    "candidates": {"label": "کاندیداها", "hint": "بالاتر از آستانه — ارزش پیشنهاد دادن دارد"},
    "newest": {"label": "تازه‌ترین", "hint": "تازه‌رسیده‌ها؛ زود رسیدن تنها برتری موجود است"},
    "bots": {"label": "ربات‌ها", "hint": "پروژه‌های ربات و تلگرام، جدا از بقیه"},
    "big": {"label": "بودجه بالا", "hint": "بزرگ‌ترین بودجه‌ها؛ سابقه می‌گوید پرریسک‌ترین هم هستند"},
    "cheap": {"label": "کم‌هزینه", "hint": "کم‌ژتون‌ترین‌ها برای کش آمدن سهمیه"},
    "drafted": {"label": "پیش‌نویس‌دار", "hint": "متنش نوشته شده و منتظر ارسال است"},
    "rejected": {"label": "ردشده‌ها", "hint": "چه چیزهایی رد شد و چرا"},
}

DEFAULT_VIEW = "all"


def _seen_at(row: dict[str, Any]) -> str:
    """Sort key for recency. A missing timestamp sorts last, never crashes."""
    return row.get("first_seen_at") or ""


def _matches_bot(row: dict[str, Any]) -> bool:
    haystack = " ".join([
        str(row.get("title") or ""),
        " ".join(str(r) for r in (row.get("reasons") or [])),
    ])
    return bool(_BOT.search(haystack))


def apply_view(items: list[dict[str, Any]], view: str, *,
               threshold: float, now: datetime) -> list[dict[str, Any]]:
    """The rows this view shows, in the order it shows them.

    Never mutates the input: the caller holds one list and switches views
    against it repeatedly.
    """
    live = [i for i in items if not i.get("rejected")]

    if view == "rejected":
        return sorted((i for i in items if i.get("rejected")),
                      key=_seen_at, reverse=True)

    if view == "candidates":
        return sorted((i for i in live if i.get("value", 0) >= threshold),
                      key=lambda i: -i.get("value", 0))

    if view == "newest":
        return sorted(live, key=_seen_at, reverse=True)

    if view == "bots":
        return sorted((i for i in live if _matches_bot(i)),
                      key=lambda i: -i.get("value", 0))

    if view == "big":
        return sorted(live, key=lambda i: -(i.get("max_budget") or 0))

    if view == "cheap":
        # Ties broken by score, so the cheapest good one leads.
        return sorted(live, key=lambda i: (i.get("token") or 0, -i.get("value", 0)))

    if view == "drafted":
        return sorted((i for i in live if (i.get("draft") or "").strip()),
                      key=lambda i: -i.get("value", 0))

    # "all", and anything unrecognised: showing everything is a safer failure
    # than showing nothing.
    return sorted(live, key=lambda i: -i.get("value", 0))


def view_counts(items: list[dict[str, Any]], *,
                threshold: float, now: datetime) -> dict[str, int]:
    """How many rows each view holds, for the tab badges."""
    return {
        name: len(apply_view(items, name, threshold=threshold, now=now))
        for name in VIEWS
    }
