# کاریاب / karyab

A local assistant for freelancers on [karlancer.com](https://www.karlancer.com).
It watches the public project feed, scores every new project against the work
you have *actually been paid for*, learns how you write from your own winning
proposals, and gives you a review page to draft and send from.

It never bids for you. Every proposal is sent by your hand, from your account.

## What it does

- **Finds work worth bidding on.** Polls the feed every few minutes and scores
  each project by skill overlap with your completed projects, budget, freshness
  and client signals. Rejects are kept with their reasons so you can tune it.
- **Learns your voice.** Reads your own bid history and keeps the proposals
  that actually won as writing examples — filtering out the ones that were
  edited during negotiation, which would otherwise teach it to open a cold
  pitch with "here is the revised offer".
- **Checks drafts against your history.** Hard rules that no winning pitch of
  yours ever broke (no markdown, no em-dashes, sane length) block a draft;
  soft signals score it.
- **Gives you a review page** in Persian, right to left, with categories,
  a token-spend meter, and an auto mode that proposes bids one at a time for
  your approval.

## Install

Needs Python 3.12+ and Linux. Google Chrome is used if present; otherwise a
Chromium is downloaded.

```bash
git clone <this repo> ~/karyab
cd ~/karyab
./install.sh
```

Then, once:

```bash
.venv/bin/karyab profile https://www.karlancer.com/profile/<your id>
.venv/bin/karyab init
.venv/bin/karyab login          # a browser opens; log in as normal
```

Open **http://127.0.0.1:8765**. It runs as a background service and restarts
itself. `RUNBOOK.md` explains the page.

## Your data stays yours

Everything personal lives in `~/.local/share/karyab/` and `~/.config/karyab/`,
never in this repository:

| file | what | protection |
|---|---|---|
| `session.json` | your Karlancer login | created 0600, never logged |
| `secrets.json` | your Anthropic API key, if you add one | created 0600, masked in the UI |
| `karyab.db` | your proposals, scores, drafts | local SQLite |
| `profile.json` | your public profile snapshot | — |

The review page binds to `127.0.0.1` only and refuses to listen on a network
address without an explicit flag, because it holds your credentials and has no
login of its own.

## Writing proposals

karyab does not need an AI key to be useful. `karyab brief` exports a briefing
file — the client's own words, the rules measured from your history, and your
three closest winning proposals — which you can hand to any assistant, or
write from yourself. `karyab drafts` reads the answers back and checks them.

If you add an Anthropic key in the settings page, drafts can be generated
directly.

## Honest limits

- It only reads Karlancer's public JSON endpoints, which are undocumented and
  could change. When they do, `scan` will fail loudly rather than silently
  return nothing.
- Nobody can see how many others have bid on a project — the field exists but
  is always empty. Speed is the only edge, which is why the **تازه‌ترین** tab
  ignores the score.
- The writing rules come from one freelancer's 15 winning pitches. They are
  a starting point, not a law; the config is yours to change.

## Development

```bash
.venv/bin/python -m pytest -q      # ~270 tests, under 3 seconds, no network
```

Design and decisions are in `docs/superpowers/specs/`. The scoring modules
under `karyab/scoring/` are pure functions with no I/O, on purpose.
