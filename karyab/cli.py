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
def matched_terms(reasons) -> tuple[str, ...]:
    """Pull the skill terms back out of a scorer reason line.

    The scorer records why it matched as "skill match: bot, telegram bot".
    Voice examples are chosen by overlap with those terms, so they have to be
    recovered rather than passing the whole sentence as a search key.
    """
    terms: list[str] = []
    for reason in reasons:
        text = str(reason)
        if text.startswith("skill match:"):
            terms += [t.strip() for t in text.split(":", 1)[1].split(",") if t.strip()]
    return tuple(terms)


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

    source = _profile_or_explain(args.profile)
    if source is None:
        return 1
    profile = json.loads(source.read_text(encoding="utf-8"))
    terms = build_vocabulary(profile)
    defaults = Config.default()

    body = f"""# karyab configuration
# Edit freely. Every value here is a default measured from your own
# completed projects, not a guess -- see docs/superpowers/specs/.

# Category 6 is برنامه نویسی. Adjust if your completed projects fall elsewhere.
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
    source = _profile_or_explain(args.profile)
    if source is None:
        return 1
    profile = json.loads(source.read_text(encoding="utf-8"))
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


def cmd_login(args) -> int:
    """Open a browser so the user can log in; save the resulting session."""
    from .browser.session import SESSION_PATH, SessionExpired, save_session

    try:
        path = save_session()
    except SessionExpired as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ImportError:
        print("Playwright is not installed. Run: .venv/bin/pip install playwright",
              file=sys.stderr)
        return 1

    print(f"Session saved to {path} (readable only by you).")
    print("It is account access in a file — it is gitignored, never log or share it.")
    return 0


def cmd_discover(args) -> int:
    """Record which API calls the logged-in panel actually makes."""
    from .browser.discover import discover
    from .browser.session import SessionExpired

    out = Path(args.out)
    try:
        report = discover(out, headless=not args.show)
    except SessionExpired as exc:
        print(str(exc), file=sys.stderr)
        return 1

    api = {k: v for k, v in report.items() if k.startswith("/api/")}
    print(f"Recorded {len(api)} API endpoint(s) -> {out}")
    for path, info in api.items():
        print(f"  {','.join(info.get('methods', [])):6} {info.get('status')}  {path}")
    return 0


def cmd_harvest(args) -> int:
    """Fetch the user's own bid history and build the voice corpus."""
    import json as _json

    from playwright.sync_api import sync_playwright

    from .browser.authed import AuthTokenMissing, bearer_header, extract_token
    from .browser.session import SESSION_PATH, SessionExpired, load_context
    from .harvest import harvest

    now = datetime.now(timezone.utc)
    try:
        state = _json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        headers = bearer_header(extract_token(state))
    except FileNotFoundError:
        print(f"No saved session at {SESSION_PATH}. Run `karyab login` first.",
              file=sys.stderr)
        return 1
    except AuthTokenMissing as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        with sync_playwright() as p:
            browser, context = load_context(p, headless=True)
            with Store(args.db) as store:
                result = harvest(context.request, headers, store, now,
                                 max_pages=args.max_pages)
                stats = store.voice_stats()
            browser.close()
    except SessionExpired as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Harvested {result.fetched} proposals across {result.pages} page(s).")
    for error in result.errors:
        print(f"  ! {error}", file=sys.stderr)
    print()
    print(f"  won            {stats['won']:4}")
    print(f"  teachable      {stats['teachable']:4}  "
          f"(wins that are genuine opening pitches, not negotiated replies)")
    print(f"  declined       {stats['declined_pitches']:4}")
    print()
    print(f"  winning pitches run a median of {stats['median_won_words']} words; "
          f"declined ones {stats['median_declined_words']}.")
    return 0


def cmd_voice(args) -> int:
    """Show the winning proposals the writer will learn from."""
    skills = tuple(s.strip() for s in (args.skills or "").split(",") if s.strip())
    with Store(args.db) as store:
        rows = store.teachable_samples(match_skills=skills, limit=args.limit)
        stats = store.voice_stats()

    if not rows:
        print("No voice corpus yet. Run `karyab harvest` first.")
        return 0

    where = f" matching {list(skills)}" if skills else ""
    print(f"{stats['teachable']} teachable winning pitches; "
          f"showing {len(rows)}{where}.\n")
    for row in rows:
        print(f"[{row['budget']:,} toman · {row['word_count']} words] "
              f"{row['project_title'][:44]}")
        print(f"  {row['text'].strip()[:400]}")
        print()
    return 0


def cmd_review(args) -> int:
    """Open the local review dashboard."""
    from .web.app import serve

    serve(args.db, host=args.host, port=args.port, allow_remote=args.i_know)
    return 0


def cmd_brief(args) -> int:
    """Export the queue's candidates as writing briefs.

    This is the no-API path: karyab writes out everything a writer needs, a
    person or a Claude session writes the drafts into the same file, and
    `karyab drafts` reads them back. Costs nothing and needs no key.
    """
    import json as _json

    from .writer.prompt import build_brief

    config = _load_config(Path(args.config))
    with Store(args.db) as store:
        rows = store.top_scores(limit=args.limit)
        candidates = [r for r in rows
                      if not r["rejected"] and r["value"] >= config.threshold]
        if args.all:
            candidates = [r for r in rows if not r["rejected"]][:args.limit]

        corpus = store.voice_stats()
        bundle = []
        for row in candidates[:args.max]:
            voice = store.teachable_samples(
                match_skills=matched_terms(row.get("reasons") or ()), limit=3)
            bundle.append({
                "project_id": row["project_id"],
                "title": row["title"],
                "score": row["value"],
                "token_cost": row["token"],
                "url": PROJECT_URL.format(slug=row["slug"]),
                "brief": build_brief(row, voice),
                "text": "",
            })

    if not bundle:
        print(f"Nothing at or above the threshold of {config.threshold}. "
              f"Use --all to brief every non-rejected project.")
        return 0

    if not corpus["teachable"]:
        print("WARNING: no voice corpus in this database, so the briefs carry no",
              file=sys.stderr)
        print("         examples of how you actually write. Run `karyab harvest`",
              file=sys.stderr)
        print("         against the SAME --db first; drafts will read generic without it.",
              file=sys.stderr)

    out = Path(args.out)
    out.write_text(_json.dumps({"drafts": bundle}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    total = sum(b["token_cost"] for b in bundle)
    print(f"Wrote {len(bundle)} brief(s) to {out} — {total} tokens if all are sent.")
    print("Fill in each \"text\" field, then run: karyab drafts " + str(out))
    return 0


def cmd_drafts(args) -> int:
    """Read written drafts back in, checking each against the gate."""
    import json as _json

    from .writer.prompt import parse_drafts
    from .writer.rules import assess, validate

    try:
        bundle = _json.loads(Path(args.file).read_text(encoding="utf-8"))
        texts = parse_drafts(bundle)
    except FileNotFoundError:
        print(f"No such file: {args.file}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"That file is not a draft bundle: {exc}", file=sys.stderr)
        return 1

    if not texts:
        print("No drafts filled in yet — every \"text\" field is empty.")
        return 0

    now = datetime.now(timezone.utc)
    stored = blocked = 0
    with Store(args.db) as store:
        for project_id, text in texts.items():
            problems = validate(text)
            a = assess(text)
            store.save_draft(project_id, text, now, source=args.source,
                             score=a.score, blocking=[v.code for v in problems])
            stored += 1
            if problems:
                blocked += 1
                print(f"  ! {project_id}: " +
                      "; ".join(v.message for v in problems))

    print(f"Stored {stored} draft(s); {blocked} need fixing before they can be sent.")
    print("Review them in the dashboard: karyab review")
    return 0


def cmd_profile(args) -> int:
    """Fetch your public Karlancer profile so init can build your config."""
    import json as _json

    from .profile import consolidate, default_profile_path, parse_profile_ref

    try:
        user_id = parse_profile_ref(args.ref)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Reading profile {user_id} from karlancer.com…")
    try:
        data = consolidate(None, user_id)
    except Exception as exc:
        print(f"Could not read profile {user_id}: {exc}", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else default_profile_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    prof = data["profile"]
    print(f"  {prof.get('username')}: {len(data['completed_projects'])} completed "
          f"projects, {len(data['reviews'])} reviews, "
          f"{len(prof.get('skills') or [])} declared skills")
    for w in data["warnings"]:
        print(f"  ! {w}", file=sys.stderr)
    print(f"Saved to {out}")
    print("Next: karyab init")
    return 0


def _profile_or_explain(path: str | None) -> Path | None:
    """The profile file to build from, or None with a message printed."""
    from .profile import default_profile_path

    target = Path(path) if path else default_profile_path()
    if target.exists():
        return target
    print(f"No profile at {target}.", file=sys.stderr)
    print("Fetch yours first:  karyab profile <your profile id or URL>",
          file=sys.stderr)
    return None


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
    p_init.add_argument("--profile", default=None,
                        help="profile file (default: the one `karyab profile` saved)")
    p_init.set_defaults(func=cmd_init)

    p_vocab = sub.add_parser("vocab", help="print the skill table for your config", parents=[sub_shared])
    p_vocab.add_argument("--profile", default=None)
    p_vocab.set_defaults(func=cmd_vocab)

    p_prof = sub.add_parser("profile", parents=[sub_shared],
                            help="fetch your public profile (first-time setup)")
    p_prof.add_argument("ref", help="your profile id or URL")
    p_prof.add_argument("--out", default=None)
    p_prof.set_defaults(func=cmd_profile)

    p_scan = sub.add_parser("scan", help="poll the feed, score it, and report", parents=[sub_shared])
    p_scan.add_argument("--pages", type=int, default=1)
    p_scan.add_argument("--limit", type=int, default=30)
    p_scan.add_argument("--rejected", action="store_true", help="include rejects")
    p_scan.set_defaults(func=cmd_scan)

    p_report = sub.add_parser("report", help="show what the last scans decided", parents=[sub_shared])
    p_report.add_argument("--limit", type=int, default=30)
    p_report.add_argument("--rejected", action="store_true")
    p_report.set_defaults(func=cmd_report)

    p_login = sub.add_parser(
        "login", parents=[sub_shared],
        help="log in to Karlancer in a browser and save the session")
    p_login.set_defaults(func=cmd_login)

    p_disc = sub.add_parser(
        "discover", parents=[sub_shared],
        help="record which API calls the logged-in panel makes")
    p_disc.add_argument("--out", default="docs/research/authenticated-endpoints.json")
    p_disc.add_argument("--show", action="store_true",
                        help="run the browser visibly instead of headless")
    p_disc.set_defaults(func=cmd_discover)

    p_harvest = sub.add_parser(
        "harvest", parents=[sub_shared],
        help="fetch your own proposal history and build the voice corpus")
    p_harvest.add_argument("--max-pages", type=int, default=None,
                           help="stop after N pages (default: all)")
    p_harvest.set_defaults(func=cmd_harvest)

    p_voice = sub.add_parser(
        "voice", parents=[sub_shared],
        help="show the winning pitches the writer will learn from")
    p_voice.add_argument("--skills", default="",
                         help="comma-separated terms to rank examples against")
    p_voice.add_argument("--limit", type=int, default=3)
    p_voice.set_defaults(func=cmd_voice)

    p_review = sub.add_parser(
        "review", parents=[sub_shared],
        help="open the local review dashboard in a browser")
    p_review.add_argument("--host", default="127.0.0.1")
    p_review.add_argument("--port", type=int, default=8765)
    p_review.add_argument("--i-know", action="store_true",
                          help="allow binding to a non-loopback address "
                               "(no auth; anyone on the network can spend your API credit)")
    p_review.set_defaults(func=cmd_review)

    p_brief = sub.add_parser(
        "brief", parents=[sub_shared],
        help="export writing briefs for the queue (no API key needed)")
    p_brief.add_argument("--out", default="drafts.json")
    p_brief.add_argument("--max", type=int, default=8,
                         help="most briefs to write (default: the daily cap)")
    p_brief.add_argument("--limit", type=int, default=40)
    p_brief.add_argument("--all", action="store_true",
                         help="include projects below the threshold")
    p_brief.set_defaults(func=cmd_brief)

    p_drafts = sub.add_parser(
        "drafts", parents=[sub_shared],
        help="read written drafts back in and check them")
    p_drafts.add_argument("file", nargs="?", default="drafts.json")
    p_drafts.add_argument("--source", default="session")
    p_drafts.set_defaults(func=cmd_drafts)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
