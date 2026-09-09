# Using karyab

Everything runs from `~/dev/karyab`. Prefix commands with `.venv/bin/python -m karyab.cli`,
or add this to your shell once:

    alias karyab='/home/milad/dev/karyab/.venv/bin/python -m karyab.cli'

## Daily use

    karyab scan --pages 2      # find and score new projects (~1 min)
    karyab review              # open http://127.0.0.1:8765 and read the queue

That is the whole loop. `scan` is safe to run as often as you like — it only
reads the public feed, and it never sends anything.

## Getting drafts written

    karyab brief --out ~/karyab-drafts.json

This writes a briefing file: for each candidate, the client's own words plus
the three winning proposals of yours closest to that job. Paste the file to
Claude and ask for the `text` fields to be filled in, then:

    karyab drafts ~/karyab-drafts.json

Drafts are checked against your own history and stored. Open `karyab review`
to edit and copy them.

## Sending a bid

karyab does not submit. Open the project link from the dashboard, paste the
draft, and send it yourself. That keeps the account action yours.

## Tuning

Config lives at `~/.config/karyab/config.toml`.

    threshold = 55        # lower it if the queue feels thin
    daily_cap = 8         # proposals per day the meter budgets against
    sweet_spot = [500000, 3500000]

Scores are stored, so after editing the config just run `karyab report` — no
re-scan needed. `karyab report --rejected` shows what was skipped and why,
which is the fastest way to spot a missing skill term.

## Once a month

    karyab harvest        # re-read your bid history; keeps the voice corpus current

If it says the session expired, run `karyab login` again.
