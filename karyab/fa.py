"""Persian rendering of the scorer's reasons.

The scorer writes its reasons in English because they are also read in the
terminal, in logs, and in tests. The dashboard is entirely Persian, so showing
"posted in the last 12 hours" beside Persian project titles reads as a leak
from the machinery underneath.

Translating at display time rather than changing the scorer keeps one set of
reason strings under test, and keeps the CLI readable for whoever is debugging.
"""

from __future__ import annotations

import re

# Whole-reason phrases, matched first because they are unambiguous.
_EXACT = {
    "base": "پایه",
    "no skill term matched": "هیچ مهارتی مطابقت نداشت",
    "budget not stated": "بودجه اعلام نشده",
    "marked urgent": "فوری",
    "highlighted listing": "آگهی ویژه",
    "detailed brief": "شرح کامل",
    "very thin brief": "شرح خیلی کوتاه",
    "client flagged low_hire": "کارفرما کم‌استخدام است",
    "hiring deadline is imminent": "مهلت استخدام نزدیک است",
    "posted in the last 10 minutes": "همین چند دقیقه پیش",
    "posted in the last half hour": "نیم ساعت گذشته",
    "posted in the last 2 hours": "۲ ساعت گذشته",
    "posted in the last 12 hours": "۱۲ ساعت گذشته",
    "posted in the last 2 days": "۲ روز گذشته",
    "more than 2 days old": "بیش از ۲ روز پیش",
    "skipped in auto mode": "در حالت خودکار رد شد",
    "project has expired": "آگهی منقضی شده",
}

# Skill terms are English by design — they are what the user types in the
# config — so the label is translated and the terms are left alone.
_SKILL_MATCH = re.compile(r"^skill match:\s*(.+)$")
_SWEET_SPOT = re.compile(r"^inside the sweet spot band ([\d,]+)-([\d,]+)$")
_FILES = re.compile(r"^client attached (\d+) file\(s\) to the brief$")
_CATEGORY_BLOCKED = re.compile(r"^category (\d+) is blocked$")
_CATEGORY_ALLOW = re.compile(r"^category (\d+) is not in the allowlist.*$")
_BUDGET_FLOOR = re.compile(r"^budget ceiling ([\d,]+) is below the floor ([\d,]+)$")
_TOKEN_LIMIT = re.compile(r"^costs (\d+) tokens, over the limit of (\d+)$")

_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa_digits(text: str) -> str:
    return text.translate(_DIGITS)


def translate_reason(reason: str) -> str:
    """One scorer reason, in Persian. Unknown reasons pass through unchanged."""
    text = (reason or "").strip()
    if not text:
        return text

    exact = _EXACT.get(text.lower())
    if exact:
        return exact

    m = _SKILL_MATCH.match(text)
    if m:
        return f"مهارت‌های مشترک: {m.group(1)}"

    m = _SWEET_SPOT.match(text)
    if m:
        return f"در محدوده‌ی مطلوب {_fa_digits(m.group(1))}–{_fa_digits(m.group(2))}"

    m = _FILES.match(text)
    if m:
        return f"کارفرما {_fa_digits(m.group(1))} فایل پیوست کرده"

    m = _CATEGORY_BLOCKED.match(text)
    if m:
        return f"دسته‌ی {_fa_digits(m.group(1))} مسدود است"

    m = _CATEGORY_ALLOW.match(text)
    if m:
        return f"دسته‌ی {_fa_digits(m.group(1))} در فهرست مجاز نیست"

    m = _BUDGET_FLOOR.match(text)
    if m:
        return (f"سقف بودجه {_fa_digits(m.group(1))} کمتر از حداقل "
                f"{_fa_digits(m.group(2))} است")

    m = _TOKEN_LIMIT.match(text)
    if m:
        return (f"{_fa_digits(m.group(1))} ژتون هزینه دارد، بیش از سقف "
                f"{_fa_digits(m.group(2))}")

    # Better to show the English than to hide a reason the user needs.
    return text


def translate_reasons(reasons) -> list[str]:
    return [translate_reason(r) for r in (reasons or [])]
