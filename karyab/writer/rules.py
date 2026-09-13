"""What a draft must not do, and what a good draft tends to do.

The distinction matters more than any individual rule. The user's 15 winning
pitches were measured against every candidate rule, and the split is empirical:

    a HARD rule is one that NO winning pitch violates
    a SOFT signal is one that real winning pitches violate

An earlier version of this module enforced the soft signals as requirements
and rejected 12 of the user's own 15 winning proposals. Correlations are not
requirements: "invites a conversation" holds in 46% of wins, which also means
54% of wins do not do it. Blocking on that throws away work that demonstrably
got paid.

So hard rules block a draft; soft signals score it, and the score is shown at
review so the user can judge a weak draft rather than never seeing it.

Measured violation rates (wins / declines):

    markdown          0/15  vs  1/65     hard
    em-dash           0/15  vs  0/65     hard
    over 140 words    0/15  vs  7/65     hard
    under 12 words    0/15  vs  2/65     hard
    no invitation     8/15  vs 48/65     soft, strongest signal
    no technology     3/15  vs 29/65     soft
    quotes price      2/15  vs 10/65     soft, weak
    sales cliche      1/15  vs  1/65     soft, no measured signal at all
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Hard bounds only. No winning pitch falls outside them; 9 declined ones do.
LENGTH_BAND = (12, 140)

# The measured median of a winning pitch. Used for guidance, never enforced.
TARGET_WORDS = 32

_INVITATION = re.compile(
    r"گفت\s*و\s*گو|گفتگو|چت\s*رو\s*باز|باز\s*کنید|پیام\s*بد(ید|هید)|"
    r"در\s*خدمتم|درخدمتم|صحبت\s*کنیم|تماس\s*بگیرید|در\s*تماس"
)

_TECHNOLOGY = re.compile(
    r"react|node|python|php|django|flask|express|next|laravel|wordpress|"
    r"javascript|typescript|api|wireguard|bootstrap|jquery|mysql|postgres|"
    r"پایتون|جنگو|فلسک|وردپرس|لاراول|ربات|بات|تلگرام|جاوااسکریپت|وایرگارد|"
    r"ری\s*اکت|نود|فرانت|بک\s*اند|سرور|اندروید|اپلیکیشن",
    re.IGNORECASE,
)

_PRICE_OR_TIME = re.compile(
    r"[\d۰-۹]+\s*(تومان|تومن|میلیون|هزار|روز|روزه|ساعت|هفته|ماه)"
)

_BANNED_PHRASES = (
    "بهترین کیفیت", "کمترین قیمت", "ارزان ترین", "ارزان‌ترین",
    "بهترین قیمت", "تضمین صد در صد",
)

_MARKDOWN = re.compile(r"\*\*|__|^\s*[-*+]\s+|^\s*#{1,6}\s|\[.+\]\(.+\)", re.MULTILINE)
_EM_DASH = re.compile(r"—|–")


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


@dataclass(frozen=True)
class Assessment:
    """How closely a draft matches what has actually won for this user."""

    score: int
    strengths: tuple[str, ...] = ()
    weaknesses: tuple[str, ...] = ()
    word_count: int = 0

    @property
    def is_strong(self) -> bool:
        return self.score >= 70


def validate(draft: str) -> list[Violation]:
    """Hard rules only. A non-empty result means the draft must not be sent.

    Every rule here is one that none of the user's winning pitches breaks, so
    enforcing it cannot reject work that has demonstrably succeeded.
    """
    text = (draft or "").strip()
    words = len(text.split())
    found: list[Violation] = []

    low, high = LENGTH_BAND
    if words < low:
        found.append(Violation(
            "too_short",
            f"{words} words. No winning pitch is under {low}; two declined "
            f"ones are."))
    elif words > high:
        found.append(Violation(
            "too_long",
            f"{words} words. No winning pitch exceeds {high}; seven declined "
            f"ones do."))

    if _MARKDOWN.search(text):
        found.append(Violation(
            "markdown",
            "Contains markdown. Proposals are typed into a plain textarea, and "
            "no winning pitch has any."))

    if _EM_DASH.search(text):
        found.append(Violation(
            "em_dash",
            "Contains an em-dash, which appears in none of the user's 80 real "
            "proposals — a reliable machine tell."))

    return found


def assess(draft: str) -> Assessment:
    """Score a draft against the signals that separate wins from declines.

    Never blocks. A low score means "look at this one carefully", not
    "this cannot be sent" — several of the user's own wins score poorly.
    """
    text = (draft or "").strip()
    words = len(text.split())
    score = 40
    strengths: list[str] = []
    weaknesses: list[str] = []

    if _INVITATION.search(text):
        score += 30
        strengths.append("invites the client to open a conversation (46% of wins, 18% of declines)")
    else:
        weaknesses.append("does not invite a conversation — the strongest signal in the history")

    if _TECHNOLOGY.search(text):
        score += 20
        strengths.append("names a concrete technology (60% of wins, 33% of declines)")
    else:
        weaknesses.append("names no specific technology")

    if _PRICE_OR_TIME.search(text):
        score -= 10
        weaknesses.append("quotes a price or timeline up front (6% of wins, 15% of declines)")

    for phrase in _BANNED_PHRASES:
        if phrase in text:
            weaknesses.append(f"contains the sales cliche {phrase!r}")
            score -= 5
            break

    # Near the measured median reads naturally; far from it is worth a look.
    if abs(words - TARGET_WORDS) <= 20:
        score += 10
        strengths.append(f"{words} words, close to the {TARGET_WORDS}-word median of winning pitches")
    elif words > 90:
        score -= 10
        weaknesses.append(f"{words} words is long; winning pitches median {TARGET_WORDS}")

    return Assessment(
        score=max(0, min(100, score)),
        strengths=tuple(strengths),
        weaknesses=tuple(weaknesses),
        word_count=words,
    )
