"""User-editable configuration.

Every knob the matcher reads lives here. Defaults are measured from the
user's own 29 completed projects, not guessed — see the spec section
"The user's profile, measured".
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path


def default_config_path() -> Path:
    """Where the config lives, honouring XDG_CONFIG_HOME."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "karyab" / "config.toml"


@dataclass(frozen=True)
class Config:
    # term -> weight. Generated from won projects by `karyab vocab`.
    skills: dict[str, float] = field(default_factory=dict)

    # Category 6 is برنامه نویسی. All 29 completed projects are category 6.
    categories_allow: tuple[int, ...] = (6,)
    categories_block: tuple[int, ...] = ()

    # Hard floor: a project whose ceiling is below this is not worth a token.
    min_budget: int = 500_000

    # Where the five-star outcomes cluster. A bonus, never a cap.
    sweet_spot: tuple[int, int] = (500_000, 3_500_000)
    sweet_spot_bonus: float = 12.0
    sweet_spot_enabled: bool = True

    # Proposals cost 1-7 tokens. Refuse to spend more than this on one bid.
    max_token_cost: int = 7

    # Score below which a project is not worth drafting for.
    threshold: float = 55.0

    daily_cap: int = 8
    poll_seconds: int = 150

    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def load(cls, path: Path) -> "Config":
        """Read a TOML file over the defaults.

        Unknown keys are an error rather than a silent no-op: a typo in a
        config file is otherwise invisible and would quietly change which
        projects get bid on.
        """
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(
                f"unknown config key(s) in {path}: {', '.join(unknown)}"
            )

        overrides: dict[str, object] = {}
        for key, value in raw.items():
            if key in {"categories_allow", "categories_block"}:
                overrides[key] = tuple(int(v) for v in value)
            elif key == "sweet_spot":
                lo, hi = (int(v) for v in value)
                overrides[key] = (lo, hi)
            elif key == "skills":
                overrides[key] = {str(k): float(v) for k, v in value.items()}
            else:
                overrides[key] = value

        cfg = replace(cls.default(), **overrides)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        lo, hi = self.sweet_spot
        if lo > hi:
            raise ValueError(
                f"sweet_spot must be [low, high], got [{lo}, {hi}]"
            )
        if self.min_budget < 0:
            raise ValueError("min_budget must not be negative")
        if not 0 <= self.threshold <= 100:
            raise ValueError("threshold must be between 0 and 100")
        if self.max_token_cost < 1:
            raise ValueError("max_token_cost must be at least 1")
