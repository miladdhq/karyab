"""Auto mode: karyab does the work, the user approves every bid.

The safety model, stated once because everything here depends on it:

  * **No bid is ever sent without an explicit, per-project approval.** An
    approval is a project id plus the exact text the user signed off on. It
    covers that project and nothing else.
  * **The daily cap is a hard stop**, and it outranks approvals given earlier.
    Approve five bids, hit the cap at three, and the remaining two wait.
  * **The text sent is the approved text**, not the drafted text. The user
    edits in the approval dialog, and the edit is the thing that counts.
  * **karyab never completes the purchase.** Bidding on Karlancer is a paid
    tier choice — bronze, silver or gold — not a form submit. Auto mode fills
    the proposal and opens the tier screen; the money is spent by a human
    hand, deliberately.

Pure functions over state, so all of that is testable without a browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from .config import Config


class Decision(str, Enum):
    READY = "ready"
    NOTHING_TO_DO = "nothing_to_do"
    CAP_REACHED = "cap_reached"


@dataclass(frozen=True)
class Plan:
    decision: Decision
    candidates: list[dict[str, Any]] = field(default_factory=list)
    remaining: int = 0
    reason: str = ""


@dataclass(frozen=True)
class AutoState:
    enabled: bool = False
    # project_id -> the exact text the user approved for it
    approved: dict[int, str] = field(default_factory=dict)
    last_scan: datetime | None = None


@dataclass(frozen=True)
class Action:
    kind: str  # scan | await_approval | submit | idle
    project_id: int | None = None
    text: str = ""
    reason: str = ""


def plan_cycle(items: list[dict[str, Any]], config: Config, *,
               spent_today: int, now: datetime) -> Plan:
    """Which projects auto mode would offer, in order, within the cap."""
    remaining = max(0, config.daily_cap - spent_today)
    if remaining == 0:
        return Plan(Decision.CAP_REACHED, [], 0,
                    f"{spent_today} bids sent in the last 24 hours; "
                    f"the cap is {config.daily_cap}.")

    eligible = sorted(
        (i for i in items
         if not i.get("rejected") and i.get("value", 0) >= config.threshold),
        key=lambda i: -i.get("value", 0),
    )
    if not eligible:
        return Plan(Decision.NOTHING_TO_DO, [], remaining,
                    f"Nothing at or above a score of {config.threshold}.")

    return Plan(Decision.READY, eligible[:remaining], remaining, "")


def next_action(state: AutoState, items: list[dict[str, Any]], config: Config, *,
                spent_today: int, now: datetime) -> Action:
    """The single next thing auto mode should do."""
    if not state.enabled:
        return Action("idle", reason="Auto mode is off.")

    plan = plan_cycle(items, config, spent_today=spent_today, now=now)
    if plan.decision is Decision.CAP_REACHED:
        # Deliberately checked before approvals: an approval given an hour ago
        # does not license a bid that would now break the cap.
        return Action("idle", reason=plan.reason)

    for candidate in plan.candidates:
        pid = candidate["project_id"]
        if pid in state.approved:
            return Action("submit", project_id=pid, text=state.approved[pid])
        return Action("await_approval", project_id=pid,
                      reason="Waiting for you to approve this proposal.")

    due = (state.last_scan is None
           or now - state.last_scan >= timedelta(seconds=config.poll_seconds))
    if due:
        return Action("scan", reason="Looking for new projects.")
    return Action("idle", reason=plan.reason or "Nothing to do right now.")
