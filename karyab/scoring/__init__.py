"""Pure scoring functions.

Nothing in this package may touch the network, the clock or the disk. The
caller passes in everything, which is what makes the matcher testable and
what lets a score be replayed months later against the same inputs.
"""

from .types import Reason, Score

__all__ = ["Reason", "Score"]
