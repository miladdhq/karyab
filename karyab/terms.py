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
