# کاریاب / karyab

Watches karlancer.com's public project feed, scores each project against the
skills you have actually been paid for, and reports what is worth bidding on
and why.

Phase 1 is read-only. It makes no LLM calls, drives no browser, and submits
nothing.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m karyab.cli init
```

`init` writes a config seeded from your own completed projects. Read the
`[skills]` table it generates and correct anything that looks wrong — those
weights decide which projects surface.

karyab talks to karlancer.com directly and deliberately ignores
`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` — karlancer.com is an Iranian
domestic site, so routing it through a foreign-bound proxy (a SOCKS tunnel
such as V2Ray, say) is both unnecessary and, with a bare `socks://` scheme,
an outright crash. If you genuinely need a proxy for this host, pass your
own `transport=` to `KarlancerClient`.

## Use

```bash
karyab scan --pages 2        # poll, score, store, report
karyab report --rejected     # what was skipped, and why
karyab vocab                 # regenerate the skill table
```

## Tuning

Scores are stored, so re-reading them is free. Edit `config.toml`, run
`karyab report`, and look at what moved. `--rejected` shows near-misses, which
is where a missing skill term usually announces itself.

## Design

`docs/superpowers/specs/2026-08-31-karyab-design.md` — the whole system.
`docs/superpowers/plans/2026-09-01-karyab-phase-1.md` — this phase, task by task.
