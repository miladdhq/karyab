# کاریاب / karyab — how to use it

## Open it

Double-click **کاریاب — Karyab** in your applications menu.

Or from a terminal:

    ~/dev/karyab/karyab-start

Either way it opens **http://127.0.0.1:8765** in your browser. Running it
twice is safe — it just opens the tab again.

To stop it: `~/dev/karyab/karyab-stop`

## What you do in the page

Everything. You do not need the terminal.

**جستجوی پروژه‌های تازه** — polls karlancer.com, scores every new project
against the skills you have actually been paid for, and fills the queue.
Takes about a minute. It only reads; nothing is ever sent.

**Each card** shows the score, the budget, what it costs in tokens, and the
reasons behind the score. Click a card to open it: the client's brief on one
side, your draft on the other.

**گرفتن بریف برای Claude** — copies a complete writing brief to your
clipboard: the client's own words, the rules measured from your history, and
the three winning proposals of yours closest to that job. Paste it into
Claude and ask for the proposal. Paste the answer back into the draft box.

**The draft box** saves as you type and checks itself against your own
history. A red list means it must be fixed. A score means it is sendable —
higher is closer to what has actually won for you.

**باز کردن آگهی و ارسال** — opens the project on karlancer.com. Paste your
draft there and send it yourself. karyab never submits for you.

**به‌روزرسانی سوابق** — re-reads your bid history so the voice examples stay
current. Worth doing once a month, or after you win something.

## The meter

`۶ / ۸ پیشنهاد · ۲۹ ژتون` means six candidates against a daily cap of eight,
and sending all six would cost 29 tokens. The cap is yours to change.

## Tuning what gets surfaced

Edit `~/.config/karyab/config.toml`:

    threshold = 55        # lower it if the queue is too thin
    daily_cap = 8         # proposals per day
    min_budget = 500000   # ignore anything cheaper

Then tick **نمایش ردشده‌ها** in the page to see what was skipped and why.
That is the fastest way to spot a skill term that is missing from the
`[skills]` table in the same file.

Scores are stored, so changing the threshold takes effect on reload — no
re-scan needed.

## If something breaks

**The page will not open** — check the log:

    tail ~/dev/karyab/.karyab-server.log

**"Not logged in" or "session no longer authenticates"** — your Karlancer
session expired:

    cd ~/dev/karyab && ./karyab-start   # stop it first if running
    .venv/bin/karyab login

A browser opens; log in as normal. karyab never sees your password.

**Nothing found in a scan** — either the threshold is too high, or the feed
genuinely has nothing in your categories right now. Tick نمایش ردشده‌ها to
confirm which.

## Command line, if you prefer it

    cd ~/dev/karyab
    .venv/bin/karyab scan --pages 2
    .venv/bin/karyab report --rejected
    .venv/bin/karyab brief --out ~/drafts.json
    .venv/bin/karyab drafts ~/drafts.json
    .venv/bin/karyab harvest
