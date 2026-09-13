# کاریاب / karyab — how to use it

## It runs itself

karyab is installed as a user service. It starts when you log in, comes back
within seconds if it ever stops, and survives a reboot. You should not have to
start it.

Just open **http://127.0.0.1:8765**, or double-click **کاریاب — Karyab** in
your applications menu.

If the page shows a red bar saying it is not responding, wait a few seconds —
the service restarts itself. If it persists:

    cd ~/karyab
    ./karyab-service status     # is it running, and what did it last say
    ./karyab-service logs       # follow the log
    ./karyab-service restart

To uninstall the service: `./karyab-service remove`

`karyab-start` and `karyab-stop` still work for running it by hand, but with
the service installed you do not need them.

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

**باز کردن آگهی** — opens the project on karlancer.com. Paste your draft
there and send it yourself. karyab never submits for you.

**ارسال شد** — press this *after* you have actually sent the bid. The project
leaves the queue, moves to **ارسال‌شده‌ها**, and its token cost counts against
your daily meter. Opening the ad does not mark anything: looking is not
bidding, and auto-marking would quietly hide projects you decided against.

Marked something by mistake? Open **ارسال‌شده‌ها** and press
**برگرداندن به صف**.

**به‌روزرسانی سوابق** — re-reads your bid history so the voice examples stay
current. Worth doing once a month, or after you win something. **This takes
up to two minutes** — it walks thirty-odd pages through a real browser. The
button says so while it runs; the page is not stuck.

## The tabs

**صف بررسی** — projects worth a look that you have not bid on yet.

**ارسال‌شده‌ها** — everything you have sent, newest first, with what it cost
and the exact text you sent. Useful a week later when a client replies and
you need to remember what you promised.

## The meter

`۱ / ۸ امروز · ۷ ژتون` means one bid sent in the last 24 hours against a cap
of eight, costing 7 tokens. It is a rolling 24 hours, not a calendar day — a
cap that resets at midnight just invites a 23:59 spree. The cap is yours to
change in the config.

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

**The page will not open** — the service should fix itself within seconds.
If not:

    ./karyab-service status
    tail -40 ~/karyab/.karyab-server.log

**"Not logged in" or "session no longer authenticates"** — your Karlancer
session expired:

    cd ~/karyab
    .venv/bin/karyab login

A browser opens; log in as normal. karyab never sees your password.

**Nothing found in a scan** — either the threshold is too high, or the feed
genuinely has nothing in your categories right now. Tick نمایش ردشده‌ها to
confirm which.

## Command line, if you prefer it

    cd ~/karyab
    .venv/bin/karyab scan --pages 2
    .venv/bin/karyab report --rejected
    .venv/bin/karyab brief --out ~/drafts.json
    .venv/bin/karyab drafts ~/drafts.json
    .venv/bin/karyab harvest
