"""Drafting proposals in the user's own voice.

Nothing here is a guess about what reads as human. Every rule the validator
enforces was measured against the user's own 312 sent proposals — see the
spec's "What the bid history actually says".
"""

from .rules import Assessment, Violation, assess, validate

__all__ = ["Assessment", "Violation", "assess", "validate"]
