from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Reason:
    """One contribution to a score, in words the user can act on."""

    label: str
    delta: float
    fatal: bool = False


@dataclass(frozen=True)
class Score:
    value: float
    reasons: tuple[Reason, ...] = ()

    @property
    def rejected(self) -> bool:
        return any(r.fatal for r in self.reasons)

    @property
    def labels(self) -> list[str]:
        return [r.label for r in self.reasons]

    def with_extra(self, reasons: Iterable[Reason]) -> "Score":
        extra = tuple(reasons)
        total = self.value + sum(r.delta for r in extra)
        return Score(value=clamp(total), reasons=self.reasons + extra)


def clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)
