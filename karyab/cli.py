"""Phase 1 command line: init, vocab, scan, report.

Nothing here submits anything. The whole point of this phase is to watch
what the matcher *would* do, for free, before an LLM or a browser is
wired in.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .api import KarlancerClient
from .config import Config, default_config_path
from .scan import run_scan
from .store import Store
from .vocab import build_vocabulary, to_toml

# The brief's original path, https://www.karlancer.com/project/{slug}, 404s.
# Verified live: /projects/{slug} (plural) returns 200.
PROJECT_URL = "https://www.karlancer.com/projects/{slug}"


def default_db_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "karyab" / "karyab.db"


def _toman(value: int) -> str:
    return f"{value:,}" if value else "?"


def render_report(rows: list[dict], *, threshold: float, show_rejected: bool) -> str:
    visible = [r for r in rows if show_rejected or not r["rejected"]]
    if not visible:
        return "Nothing to show yet. Run `karyab scan` first.\n"

    lines: list[str] = []
    for row in visible:
        mark = "REJECTED" if row["rejected"] else (
            "CANDIDATE" if row["value"] >= threshold else "below threshold"
        )
        lines.append(f"[{row['value']:5.1f}] {mark}  {row['title']}")
        lines.append(
            f"         {_toman(row['min_budget'])}-{_toman(row['max_budget'])} toman"
            f"  ·  {row['token']} tokens  ·  stage {row['stage']}"
        )
        lines.append(f"         {PROJECT_URL.format(slug=row['slug'])}")
        for reason in row["reasons"]:
            lines.append(f"           - {reason}")
        lines.append("")

    shown = len(visible)
    candidates = sum(
        1 for r in visible if not r["rejected"] and r["value"] >= threshold
    )
    lines.append(f"{shown} shown, {candidates} at or above the threshold of {threshold}.")
    return "\n".join(lines) + "\n"


def _load_config(path: Path) -> Config:
    if path.exists():
        return Config.load(path)
    print(f"No config at {path}; using defaults. Run `karyab init` to create one.",
          file=sys.stderr)
    return Config.default()


def cmd_init(args) -> int:
    cfg_path = Path(args.config)
    if cfg_path.exists():
        print(f"{cfg_path} already exists; refusing to overwrite it.", file=sys.stderr)
        return 1

    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    terms = build_vocabulary(profile)
    defaults = Config.default()

    body = f"""# karyab configuration
# Edit freely. Every value here is a default measured from your own
# completed projects, not a guess -- see docs/superpowers/specs/.

# Category 6 is برنامه نویسی. All 29 of your completed projects are category 6.
categories_allow = {list(defaults.categories_allow)}
categories_block = []

# A project whose ceiling is below this is not worth spending a token on.
min_budget = {defaults.min_budget}

# Where your five-star outcomes cluster. A scoring bonus, never a cap:
# larger projects stay biddable, they just start lower.
sweet_spot = {list(defaults.sweet_spot)}
sweet_spot_bonus = {defaults.sweet_spot_bonus}
sweet_spot_enabled = {str(defaults.sweet_spot_enabled).lower()}

max_token_cost = {defaults.max_token_cost}
threshold = {defaults.threshold}
daily_cap = {defaults.daily_cap}
poll_seconds = {defaults.poll_seconds}

# Generated from the projects you actually won. Weights are relative to
# your strongest term. Adjust anything that looks wrong -- this is the
# single biggest lever on which projects surface.
{to_toml(terms)}"""

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(body, encoding="utf-8")
    print(f"Wrote {cfg_path} with {len(terms)} skill terms.")
    print("Read the [skills] table and correct anything that looks wrong.")
    return 0


def cmd_vocab(args) -> int:
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    terms = build_vocabulary(profile)
    print(to_toml(terms), end="")
    return 0


def cmd_scan(args) -> int:
    config = _load_config(Path(args.config))
    now = datetime.now(timezone.utc)

    with Store(args.db) as store, KarlancerClient() as client:
        result = run_scan(client, store, config, now=now, pages=args.pages)
        rows = store.top_scores(limit=args.limit)

    print(
        f"Saw {result.seen} projects ({result.new} new), "
        f"rejected {result.rejected}, "
        f"fetched {result.detail_fetches} details, "
        f"{result.promoted} cleared the threshold."
    )
    for error in result.errors:
        print(f"  ! {error}", file=sys.stderr)
    print()
    print(render_report(rows, threshold=config.threshold, show_rejected=args.rejected))
    return 0


def cmd_report(args) -> int:
    config = _load_config(Path(args.config))
    with Store(args.db) as store:
        rows = store.top_scores(limit=args.limit)
    print(render_report(rows, threshold=config.threshold, show_rejected=args.rejected),
          end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    # `--config` and `--db` must work both before AND after the subcommand
    # (`karyab --config X scan` and `karyab scan --config X`), because users
    # will type them either way. So every subparser also declares them.
    #
    # That alone is not enough: argparse's subparsers action parses the
    # remainder into a *fresh* namespace and then copies every one of its
    # keys onto the real namespace -- including its own default for
    # `--config`/`--db` when the flag was not repeated after the
    # subcommand. That copy silently clobbers whatever the top-level parser
    # already recorded from `--config X` given *before* the subcommand
    # (verified against this exact argparse version; it is not a hypothetical).
    #
    # The fix: give the top-level parser real defaults, but give every
    # subparser's copy of these two flags `default=argparse.SUPPRESS`. Then
    # an unspecified `--config` after the subcommand is simply absent from
    # the fresh subnamespace, so the copy step has nothing to overwrite the
    # top-level value with, while an explicit `--config` after the
    # subcommand still lands normally and wins.
    top_only = argparse.ArgumentParser(add_help=False)
    top_only.add_argument("--config", default=str(default_config_path()))
    top_only.add_argument("--db", default=str(default_db_path()))

    sub_shared = argparse.ArgumentParser(add_help=False)
    sub_shared.add_argument("--config", default=argparse.SUPPRESS)
    sub_shared.add_argument("--db", default=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(
        prog="karyab",
        description="Watch karlancer.com and report what is worth bidding on.",
        parents=[top_only],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="write a config seeded from your profile", parents=[sub_shared])
    p_init.add_argument("--profile", default="docs/research/profile-65389.json")
    p_init.set_defaults(func=cmd_init)

    p_vocab = sub.add_parser("vocab", help="print the skill table for your config", parents=[sub_shared])
    p_vocab.add_argument("--profile", default="docs/research/profile-65389.json")
    p_vocab.set_defaults(func=cmd_vocab)

    p_scan = sub.add_parser("scan", help="poll the feed, score it, and report", parents=[sub_shared])
    p_scan.add_argument("--pages", type=int, default=1)
    p_scan.add_argument("--limit", type=int, default=30)
    p_scan.add_argument("--rejected", action="store_true", help="include rejects")
    p_scan.set_defaults(func=cmd_scan)

    p_report = sub.add_parser("report", help="show what the last scans decided", parents=[sub_shared])
    p_report.add_argument("--limit", type=int, default=30)
    p_report.add_argument("--rejected", action="store_true")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
