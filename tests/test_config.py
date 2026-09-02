import textwrap
from pathlib import Path

from karyab.config import Config


def test_default_config_targets_category_six_only():
    cfg = Config.default()
    assert cfg.categories_allow == (6,)
    assert cfg.categories_block == ()


def test_default_sweet_spot_matches_the_measured_band():
    cfg = Config.default()
    assert cfg.sweet_spot == (500_000, 3_500_000)
    assert cfg.sweet_spot_enabled is True


def test_load_overrides_defaults_and_keeps_the_rest(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        textwrap.dedent(
            """
            min_budget = 900000
            threshold = 70.0

            [skills]
            "telegram bot" = 1.0
            react = 0.8
            """
        ).strip(),
        encoding="utf-8",
    )

    cfg = Config.load(path)

    assert cfg.min_budget == 900_000
    assert cfg.threshold == 70.0
    assert cfg.skills == {"telegram bot": 1.0, "react": 0.8}
    # untouched keys keep their defaults
    assert cfg.categories_allow == (6,)
    assert cfg.daily_cap == 8


def test_load_rejects_an_unknown_key(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("mn_budget = 900000\n", encoding="utf-8")

    try:
        Config.load(path)
    except ValueError as exc:
        assert "mn_budget" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown key")


def test_load_rejects_a_backwards_sweet_spot(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("sweet_spot = [3500000, 500000]\n", encoding="utf-8")

    try:
        Config.load(path)
    except ValueError as exc:
        assert "sweet_spot" in str(exc)
    else:
        raise AssertionError("expected ValueError for inverted sweet_spot")
