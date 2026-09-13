"""Turn the user's own bid history into a voice corpus.

The point of this module is a single measured fact: **a bid's text is
editable, and the user edits it during negotiation.** So the text stored
against a *won* bid is frequently the last thing they said before getting
paid, not the thing that won the work. The two highest-value wins in the real
data read "here is the offer, you can hire me" and "I revised the offer, you
can pay now".

Measured 2026-09-02: 27% of won bids carry a negotiation marker, against 1% of
bids that were never engaged with at all. Feeding won bids to a proposal writer
without filtering would teach it to open a cold pitch mid-conversation.

No `updated_at` is exposed by the API, so edits cannot be detected directly.
The marker list below is the available proxy. It lives here, in the code, and
not buried in an analysis script, because it decides what the writer learns
and it is the first thing to correct when a draft reads wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .models import parse_timestamp

# Phrases that mark a bid as a mid-negotiation reply rather than a cold pitch.
# Every entry was found by auditing the user's real corpus, not guessed. The
# second group was added after a first pass let six negotiated replies through
# — including a 13-word "here you go, I added those two days" that a writer
# would otherwise have learned to open a cold pitch with.
NEGOTIATION_MARKERS: tuple[str, ...] = (
    # --- offer was revised ---
    "اصلاح کردم",
    "ویرایش کردم",
    "به روز کردم",
    "بروز کردم",
    "تغییر دادم",
    "تغییر پیشنهاد",
    "قیمت رو کم کردم",
    "تخفیف",
    # --- offer is being handed over; the client already agreed ---
    "این از پیشنهاد",
    "اینم خدمت شما",
    "پیشنهاد رو ثبت کردم",
    "درخواست رو ارسال کردم",
    "استخدام رو بزنید",
    "میتونید استخدام",
    "میتونید پرداخت",
    "پرداخت رو انجام",
    # --- refers back to a conversation that already happened ---
    "طبق صحبت",
    "همونطور که گفت",
    "توضیح دادم",
    "بهتون گفتم",
)

_MARKER_RE = re.compile("|".join(re.escape(m) for m in NEGOTIATION_MARKERS))

# Below this, a bid carries no teachable content. The real data contains
# 9-character bids.
MIN_PITCH_WORDS = 5


class Outcome(str, Enum):
    """What became of a bid.

    PENDING is deliberately not a loss: 214 of the user's 312 bids are
    pending, and folding them into the declined set would drown the signal
    from the 67 genuine declines.

    FAILED is deliberately not a loss either — the project was awarded and
    then went wrong, so the *pitch* succeeded. Counting it against the pitch
    would punish the wrong thing.
    """

    WON = "won"
    DECLINED = "declined"
    PENDING = "pending"
    FAILED = "failed"
    UNKNOWN = "unknown"


_STATUS_MAP = {
    "completed": Outcome.WON,
    "declined": Outcome.DECLINED,
    "pending": Outcome.PENDING,
    "failed": Outcome.FAILED,
}


def classify(bid: dict) -> Outcome:
    return _STATUS_MAP.get(str(bid.get("status") or "").lower(), Outcome.UNKNOWN)


def is_opening_pitch(description: str | None) -> bool:
    """True if this text plausibly is what the user first said to a client."""
    text = (description or "").strip()
    if len(text.split()) < MIN_PITCH_WORDS:
        return False
    return not _MARKER_RE.search(text)


@dataclass(frozen=True)
class VoiceSample:
    """One proposal the user wrote, with what became of it."""

    bid_id: int
    project_id: int
    text: str
    outcome: Outcome
    is_opening_pitch: bool
    word_count: int
    budget: int
    duration: int
    token: int
    created_at: datetime | None
    project_title: str
    category_id: int
    project_skills: tuple[str, ...]

    @property
    def is_teachable(self) -> bool:
        """Usable as a voice example: a real cold pitch that actually won."""
        return self.outcome is Outcome.WON and self.is_opening_pitch


def _int(raw: dict, key: str) -> int:
    value = raw.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_bid(bid: dict) -> VoiceSample:
    project = bid.get("project") or {}
    if not isinstance(project, dict):
        project = {}
    skills = tuple(
        str(s["name"])
        for s in (project.get("skills") or [])
        if isinstance(s, dict) and s.get("name")
    )
    text = str(bid.get("description") or "")
    return VoiceSample(
        bid_id=_int(bid, "id"),
        project_id=_int(bid, "project_id"),
        text=text,
        outcome=classify(bid),
        is_opening_pitch=is_opening_pitch(text),
        word_count=len(text.split()),
        budget=_int(bid, "budget"),
        duration=_int(bid, "duration"),
        token=_int(bid, "token"),
        created_at=parse_timestamp(bid.get("created_at")),
        project_title=str(project.get("title") or ""),
        category_id=_int(project, "category_id"),
        project_skills=skills,
    )


# --- fetching ---------------------------------------------------------------

BIDS_URL = "https://www.karlancer.com/api/bids/"

# karlancer.com resets connections under parallel load (observed: 14 concurrent
# fetches drew an SSL error), so pages are walked serially with a pause.
PAGE_PAUSE_SECONDS = 0.6


@dataclass(frozen=True)
class HarvestResult:
    fetched: int = 0
    stored: int = 0
    pages: int = 0
    errors: tuple[str, ...] = ()


def fetch_bids(request, headers: dict[str, str], *, max_pages: int | None = None,
               sleep=None) -> tuple[list[dict], int, list[str]]:
    """Walk every page of the user's bid history.

    `request` is anything with `.get(url, headers=...)` returning a Playwright
    APIResponse — passed in so this is testable without a browser.
    """
    import time

    pause = sleep if sleep is not None else (lambda s: time.sleep(s))
    rows: list[dict] = []
    errors: list[str] = []

    first = request.get(f"{BIDS_URL}?page=1", headers=headers)
    if first.status != 200:
        return [], 0, [f"page 1 returned HTTP {first.status}"]
    try:
        payload = first.json()["data"]
    except Exception as exc:
        return [], 0, [f"page 1 was not the expected JSON: {exc}"]

    rows.extend(payload.get("data") or [])
    last_page = int(payload.get("last_page") or 1)
    if max_pages is not None:
        last_page = min(last_page, max_pages)

    for page in range(2, last_page + 1):
        pause(PAGE_PAUSE_SECONDS)
        try:
            response = request.get(f"{BIDS_URL}?page={page}", headers=headers)
            if response.status != 200:
                errors.append(f"page {page} returned HTTP {response.status}")
                continue
            rows.extend(response.json()["data"]["data"])
        except Exception as exc:  # one bad page must not lose the rest
            errors.append(f"page {page}: {exc}")

    return rows, last_page, errors


def harvest(request, headers: dict[str, str], store, now: datetime, *,
            max_pages: int | None = None, sleep=None) -> HarvestResult:
    """Fetch the bid history, classify it, and store the voice corpus."""
    rows, pages, errors = fetch_bids(
        request, headers, max_pages=max_pages, sleep=sleep
    )

    samples = []
    for raw in rows:
        try:
            samples.append(parse_bid(raw))
        except Exception as exc:  # a malformed bid must not stop the harvest
            errors.append(f"unparsable bid {raw.get('id')}: {exc}")

    stored = store.save_voice_samples(samples, now) if samples else 0
    return HarvestResult(
        fetched=len(rows), stored=stored, pages=pages, errors=tuple(errors)
    )
