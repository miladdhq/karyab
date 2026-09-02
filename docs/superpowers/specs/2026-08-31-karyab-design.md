# کاریاب / karyab — design

**Date:** 2026-08-31
**Status:** approved design, pending implementation plan
**Owner:** milad

## Problem

Winning work on karlancer.com rewards two things: being early to a fresh
project, and sending a proposal that reads as though a person read the brief.
Doing both by hand means watching a feed all day. Doing both badly — spraying
templated bids — costs money (Karlancer charges tokens per proposal) and
reputation.

karyab watches the feed, decides which projects are worth a bid, drafts a
proposal in the user's own voice, and queues it for one-click review and
submission.

## Goals

- Surface a matching project within minutes of it being posted.
- Bid selectively. Fewer, better proposals — the token cost makes volume a
  losing strategy anyway.
- Draft proposals indistinguishable from ones the user wrote by hand.
- Keep a human in the loop on every submission.
- Learn from the user's real history rather than from guesses about what works.

## Non-goals

- Auto-submitting without review. Explicitly rejected by the user.
- Multiple accounts. Karlancer's terms permit one freelancer account per
  person; karyab operates that single account.
- Bidding on everything. Coverage is not the metric; reply rate is.

## Constraints discovered

Findings from probing the live site on 2026-08-31.

**The public API needs no authentication.**

    GET https://www.karlancer.com/api/publics/search/projects?page=N

Returns a Laravel paginator: 24 projects per page, 417 pages at time of
writing, newest first. Observed a project 2 minutes after posting. Each record
carries `id`, `title`, `description`, `min_budget`, `max_budget`,
`job_duration`, `skills[]` (`{id, name}`), `category_id`, `country`,
`past_time`, `is_urgent`, `is_highlight`, `is_expired`, `users_bid`,
`successful_projects_percentage`, `low_hire`, `token`, `url` (slug),
`shortened_url`.

Individual project detail: `GET /api/publics/projects/{slug}`. The detail
response adds fields the listing omits: `created_at` (a real ISO timestamp),
`hire_deadline`, `files[]` (client attachments, with URLs), and `breadcrumbs`
(the named category path). It does **not** add a bid count.

Three fields in the listing are not usable as signals, verified across a
24-project sample:

- `users_bid` is `null` on every record in both the listing and the detail
  response. **The number of competing bids is not exposed publicly.**
- `successful_projects_percentage` is `0` on every record. It is not a
  meaningful client-quality signal from this endpoint.
- `low_hire` *is* populated in the listing (4 of 24 true) but is `null` in the
  detail response. Read it from the listing; treat `null` as unknown.

`past_time` is a localised Persian relative string with Persian-Indic digits
("۲ دقیقه  پیش", note the double space). It is display text, not data, and is
never parsed — see freshness below.

**Bidding is authenticated.** `GET /api/projects` returns
`401 {"message":"Unauthenticated."}`.

**The login endpoint resists reverse-engineering.** `POST /api/login` returns
422 `"فیلد نام کاربری الزامی است."` for every field name and encoding tried
(`username`, `user_name`, `mobile`, `email`, JSON and form-encoded, nested and
flat). It requires something the Angular client supplies — a header or client
key — that was not worth extracting.

**No captcha.** No recaptcha/hcaptcha/arcaptcha reference anywhere in the
application bundle.

**Proposals cost tokens.** Each project record carries a `token` field, 1–7 in
the observed sample, scaling roughly with budget. This is the cost of bidding
and it is the reason selectivity is the core design principle rather than a
nicety.

**Terms.** No clause prohibiting automation or scraping. One freelancer account
per person is enforced. The residual risk is not the terms but the pattern: bids
that read as machine-generated are what gets an account flagged.

## The user's profile, measured

Profile 65389 (`Zeinab.H`, formerly `Vayrex`), read from
`GET /api/publics/profile/{id}` — also unauthenticated, and paginated with
`?page=N` for its `completed_projects`, `reviews_pg`, and `worksamples`
sub-resources. Captured to `docs/research/profile-65389.json`.

Headline numbers: 4.3 rating over 28 reviews, 97% on-time, ~4h20m average
response, 29 completed projects.

Four findings change the design.

**Every single completed project is category 6 (برنامه نویسی).** 29 of 29. The
category whitelist does not need to be guessed; it is measured. Anything
outside category 6 starts from a position of no evidence.

**The declared skill list badly under-describes the actual work.** The profile
declares seven skills — طراحی سایت, php, react js, node js, برنامه نویس فول
استک, express.js, react native. But of the 29 wins, 11 are bots (6 of them
Telegram bots), 2 are WireGuard panels, 2 are Python, 1 is Next.js. None of
those words appear in the declared list.

This is decisive for matching: **the skill vocabulary must be derived from won
projects, not from the profile's declared skills.** A scorer keyed on the
declared list would miss the single largest cluster of work this user actually
wins. It also means the profile itself is leaving money on the table, which is
a separate conversation.

**Ratings are bimodal, not average.** The 4.3 is 23 five-star reviews and 5
one-star reviews. There is no middle. So "4.3" understates both how well the
good projects go and how badly the bad ones do.

**Outcomes vary with project size.** Of rated projects at or below 3.5M toman,
17 of 19 are five-star (89%). Above 3.5M, 4 of 6 (67%) — and the two worst
outcomes are the two largest rated projects (12M and 11.1M). The sample above
3.5M is small, so this is a signal rather than a proof.

Karlancer publishes a generated summary on the profile page, visible to every
client considering a bid, which reaches the same conclusion: strong on small
and simple projects, high risk of incompletion on larger or time-bound ones.
Whatever else is true, prospective clients are reading that before they read
the proposal.

**Design consequences, not judgements:**

- The scorer gets a configurable **sweet-spot band**, defaulting to roughly
  500k–3.5M toman, as a scoring bonus rather than a hard cap. The user can move
  it or disable it. Bidding outside it stays possible and is simply scored
  lower, because the evidence for it is weaker.
- One of the five one-star reviews specifically objects to a bid at several
  times the client's stated budget. That converts the price-clamping rule from
  a nicety into a **hard invariant**: a proposal whose price exceeds
  `max_budget` is never queued.
- The evidence pack for the writer is built from the 29 completed projects and
  their titles, not from the seven declared skills.

## Architecture

Six components. Each is independently testable and communicates through SQLite.

### 1. `harvest` — voice and win data

Runs once at setup, then monthly. Drives a logged-in browser over the user's
conversation list and extracts, for every proposal they have sent:

- the proposal text verbatim
- the project it was for (category, budget, skills)
- the outcome: no reply / client replied / project awarded

This produces two artefacts:

**Voice corpus** — the user's own winning proposals, used as few-shot examples
for the writer. This is the highest-leverage input in the system. Learning from
the user's actual replied-to messages beats any amount of prompt engineering
about "sounding natural", because it is ground truth for what works for this
person on this platform.

**Win data** — which categories, budget bands, and client profiles actually
convert. Feeds the scorer's weights, replacing guessed constants with measured
ones.

### 2. `watch` — the feed daemon

Polls `/api/publics/search/projects?page=1` every 2–3 minutes with jitter,
pages deeper only on cold start. Diffs against the `projects` table by `id`.
New rows enter the pipeline. Exponential backoff on error, hard stop on
repeated 4xx. Unauthenticated, so this half of the system carries no account
risk at all.

### 3. `score` — the matcher

Two stages, because the listing is cheap and the detail endpoint is a request
per project.

**Stage one** scores the listing record alone: skill overlap, budget floor,
category, `low_hire`, token cost. Most projects are rejected here having cost
one twenty-fourth of a request.

**Stage two** fetches `/api/publics/projects/{slug}` for survivors only, and
refines the score with `created_at`, `hire_deadline`, and whether the client
attached files — an attached brief is a strong signal of a client who has
thought about the work.

Both stages are pure functions over a record and the user's config. No LLM, no
network inside the scoring logic itself; the fetch is the caller's job. Fully
unit-testable against fixtures.

Signals:

| Signal | Source | Stage | Effect |
|---|---|---|---|
| Skill overlap | `skills[]` vs. configured skills, weighted per skill | 1 | primary |
| Budget floor | `max_budget` below configured minimum | 1 | hard reject |
| Category | `category_id` against whitelist/blacklist | 1 | hard reject |
| Token cost | `token` vs. expected value of the bid | 1 | penalty |
| Sweet spot | `min_budget`/`max_budget` inside the configured band | 1 | bonus |
| Weak client | `low_hire` true | 1 | penalty |
| Urgency | `is_urgent`, `is_highlight` | 1 | bonus |
| Freshness | `first_seen_at`, corroborated by `created_at` | 2 | bonus, steep |
| Deadline room | `hire_deadline` | 2 | penalty if imminent |
| Brief quality | `files[]` non-empty, description length | 2 | bonus |

**Freshness is measured, not parsed.** karyab records `first_seen_at` when a
project first appears in its own polling, and corroborates against `created_at`
from the detail endpoint. The Persian relative-time string is display text and
is never parsed.

**Competition is unknowable.** No public field exposes how many freelancers have
already bid, so the scorer cannot account for it. Speed is the proxy: bid early
and the question is moot. This is the strongest argument for a tight polling
interval.

Emits a 0–100 score **and a list of human-readable reasons, including for
rejections**. Rejected projects are stored, not discarded, so the user can see
what was skipped and why, and tune thresholds against real misses rather than
guesses.

### 4. `write` — the proposal writer

One Claude API call per project that clears the threshold. Inputs:

- the project title, description, budget range, skills, and the names of any
  files the client attached
- the user's evidence pack: profile skills, portfolio, and real projects from
  `~/dev` with names and links
- 2–3 winning proposals from the voice corpus, selected for similarity to the
  current project
- the assigned shape and length band (see below)

Outputs: proposal text in Persian, a suggested price, a suggested duration, and
the clarifying question embedded in the text.

### 5. `review` — the dashboard

Local web page, RTL. One card per queued draft: project on one side, editable
draft on the other, score and its reasons, prefilled price and duration.
Actions: Send, Skip, Blacklist client. Reachable over LAN so it can be reviewed
from a phone.

### 6. `submit` — the browser

Playwright with a persisted logged-in session. Opens the project page, fills
the bid form, submits, records the result. Every submission originates from a
real browser with real cookies, because this is the half attached to the user's
account.

A `--dry-run` mode fills the form and stops without clicking submit.

## Auth design

The two halves are split deliberately:

- **Discovery uses the public API.** Fast, unauthenticated, no account exposure.
- **Submission and harvest use a real browser.** The login endpoint's hidden
  requirement never has to be solved, an added OTP or header change does not
  break anything, and a bid is indistinguishable from the user clicking the
  button.

Session state persists to disk after one manual login. When it expires, karyab
pauses submission and asks for a fresh login rather than retrying blindly.

## The human-likeness specification

The product is the proposal. These rules are requirements, not style advice.

**Measured on 2026-09-02 against the user's own 312 sent proposals.** The
rules below are no longer a guess about what reads as human; they are what
actually converted for this user on this platform. The original three-part
rule is superseded — see "What the bid history actually says" below.

**Every proposal contains:**

1. **A specific technical claim about how the work would be done.** Naming a
   concrete technology is the one content signal that lifts: 42% of winning
   opening pitches name one, against 33% of declined. The strongest winner in
   the set does exactly this — it proposes React Native so one codebase ships
   web, Android and iOS, and says why that is cheaper for the client.
2. **An invitation to open the conversation**, phrased as an invitation, not a
   question. Both top winners end this way ("خوشحال میشم گفتگو رو باز کنید").
   Question marks correlate with *losing*: 9% of wins contain one against 21%
   of declines.
3. **Brevity.** Winning opening pitches run a median of 28 words (p75 = 38).
   Declined ones run 39 (p75 = 69). Length is the clearest single separator in
   the data.

**Banned outright:** anything over ~60 words; an explicit price or timeline in
the opening pitch (4% of wins mention one, 16% of declines); an elaborate
greeting; skill-list dumps; self-superlatives; "بهترین کیفیت و کمترین قیمت";
any promise the user has not made.

**Retained from the original rules**, because they remain sound and the data
neither confirms nor refutes them at this sample size: no em-dashes, no
translated-English syntax, no markdown in the proposal body, and enforced
shape variance across a batch so fifty proposals do not share one skeleton.

**Validation before queueing.** A draft that fails a structural check — missing
question, missing evidence, out of length band, contains a banned phrase — is
regenerated rather than queued.

## What the bid history actually says

Harvested 2026-09-02 from `/api/bids/`: 312 proposals — 214 pending, 67
declined, 29 completed, 2 failed. The 29 completions match the profile's
completed-project count exactly.

**A confound that had to be removed first.** A bid's `description` is editable,
and the user edits it during negotiation. So the text stored against a *won*
bid is often the final negotiated message, not the opening pitch — the two
highest-value "winning proposals" read "here is the offer, you can hire me"
and "I revised the offer, you can pay now". Measured: 27% of won bids contain
a mid-negotiation reply marker, against 1% of never-engaged pending bids, a
27x difference. Analysing won bids naively therefore teaches the writer to
open with a follow-up message, which would be worse than useless.

The harvest filters these out. After filtering: 21 clean opening pitches that
won, against 66 that were declined. Every figure in the human-likeness section
above is computed on that filtered set.

**No `updated_at` field is exposed**, so edits cannot be detected directly; the
reply-marker heuristic is the available proxy and its pattern list is part of
the harvest code, not hidden in an analysis script.

**Sample-size caveat, stated plainly:** 21 winning pitches is a small sample.
Length (28 vs 39 words median, 38 vs 69 at p75) is a wide and stable gap.
The content lifts — naming a technology, avoiding question marks, omitting
price — are single-digit-count differences and should be treated as leads that
Phase 4's outcome tracking either confirms or overturns, not as settled law.

## Pricing

Rules the user configures, not model judgement. A rate and a rough effort
estimate per category produce a price, clamped into the project's stated
`min_budget`–`max_budget` range. The review queue prefills it and the user
overrides at will.

**Invariant: a draft whose price exceeds the project's `max_budget` is never
queued.** This is enforced in code, not left to the model or to review
discipline. It exists because the user has already taken a one-star review for
exactly this — a bid at several times a client's stated budget — and one such
review costs more than any single project is worth.

## Data

SQLite at `~/.local/share/karyab/karyab.db`.

- `projects` — every project seen, with `first_seen_at`, score and reasons,
  including rejects
- `drafts` — generated proposals, shape, price, duration, status
- `submissions` — what was sent, when, token cost, outcome
- `voice_samples` — harvested proposals with outcomes
- `config` — mutable runtime settings

Configuration the user edits lives in one file: skills and weights, rate per
category, budget floor, sweet-spot band, category whitelist/blacklist, daily
cap, token budget, score threshold.

The initial skill vocabulary is **generated from the 29 completed projects**
rather than typed by hand or copied from the profile's declared skills, then
handed to the user to correct. Phase 1 ships this generator.

## Safety and rate limiting

- Polite polling interval with jitter; exponential backoff; no parallel fanout.
- Daily submission cap, default 8. Token budget cap.
- No submission without an explicit human click.
- Blacklist for clients not worth bidding on again.

## Testing

- `score` is pure logic — unit tested against fixture project records.
- The API client is tested against recorded JSON responses, not the live site.
- `write` is tested structurally: every generated draft must satisfy the
  three-part rule, the length band, the shape assignment, and the banned-phrase
  list. Voice quality is judged by the user in review, not asserted in a test.
- `submit` is tested against a local mock of the bid form, plus `--dry-run`
  against the real page.

Stack: Python 3.12, httpx, Playwright, FastAPI, SQLite, anthropic SDK.

## Phases

**Phase 1 — feed and matcher. No LLM, no browser.**
API client, project store, scorer, config, and a CLI that reports what it would
have bid on and why. Runnable the day it is built; proves the matching is right
before a single token is spent.

**Phase 2 — harvest.** Browser login, chat mining, voice corpus, win data. Feeds
measured weights back into the scorer.

**Phase 3 — writer and dashboard.** Claude API writer with the human-likeness
rules, RTL review queue.

**Phase 4 — submit and learn.** Playwright submission, outcome tracking, and the
feedback loop from replies back into scoring and shape selection.

Phase 1 is the subject of the first implementation plan.

## Open questions

- ~~Whether the three-part proposal rule survives contact with the harvested
  data.~~ **Answered 2026-09-02: it did not.** The user's winning pitches are
  far shorter than the rule assumed (28 words median, not 60-160), invite a
  conversation instead of asking a question, and omit the price. The rule has
  been rewritten from the measured data.
- Whether to keep the sweet-spot band on by default. The evidence supports it,
  but it is the user's business decision how much weight to give a six-project
  sample, and the band is one config line either way.
- Proposals are sent under the profile name `Zeinab.H`. The writer's voice and
  self-reference must match that persona consistently; the harvested proposals
  in Phase 2 settle the register.
