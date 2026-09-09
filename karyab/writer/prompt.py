"""What a proposal writer is told, and how a written draft is read back.

Kept separate from any backend so the same instructions and the same voice
corpus drive both paths: the Anthropic API, and a person (or a Claude session)
writing the drafts by hand. Pure functions, no I/O, no SDK import.

Two things here exist because of measurements, not taste:

  * The budget is never shown to the writer. Quoting a price appears in 6% of
    the user's winning pitches and 15% of the declined ones, so handing over a
    number invites the exact behaviour that loses work.
  * Stable content comes first. Prompt caching is a prefix match, so the rules
    and the voice corpus sit ahead of the per-project text; otherwise every
    draft pays full input price for the same corpus.
"""

from __future__ import annotations

from typing import Any

SYSTEM_RULES = """You write freelance proposals in Persian, as this specific freelancer, on karlancer.com.

You are not writing marketing copy. You are writing the short first message a working developer sends a client who just posted a job. It must read as though they typed it themselves in thirty seconds.

What the evidence says, measured across this freelancer's own 15 winning proposals and 65 declined ones:

- Inviting the client to open a conversation is the strongest signal: 46% of wins do it, against 18% of declines. Say something like "لطفا گفت و گو رو باز کنید تا صحبت کنیم". Make it an invitation, never a question — question marks correlate with losing.
- Naming a concrete technology is the second strongest: 60% of wins, against 33% of declines. Say how you would actually build it.
- Stating a price or a timeline correlates with LOSING: 6% of wins, 15% of declines. Never quote either. Terms belong in the conversation that follows.
- Winning proposals run about 32 words. Not a rule, a habit — some winners run to 130. Write what the job needs and stop.

Hard constraints. A draft breaking any of these is discarded:
- No markdown. No asterisks, no bullet lists, no headings. This goes into a plain textarea.
- No em-dashes. This freelancer has never typed one in 80 real proposals.
- Between 12 and 140 words.

Write only the proposal text. No preamble, no explanation, no quotes around it."""


def _voice_block(samples: list[dict[str, Any]]) -> str:
    if not samples:
        return ("No prior proposals are available, so write plainly and briefly "
                "in the freelancer's likely register.")
    lines = ["Proposals this freelancer sent that WON the work. Match this "
             "register, rhythm and level of formality — not the wording:"]
    for i, s in enumerate(samples, 1):
        text = " ".join((s.get("text") or "").split())
        lines.append(f"\n{i}. ({s.get('word_count', 0)} words) {text}")
    return "\n".join(lines)


def _project_block(project: dict[str, Any]) -> str:
    title = project.get("title") or ""
    body = " ".join((project.get("description") or "").split())
    reasons = ", ".join(project.get("reasons") or [])
    return (
        "The job to write for.\n\n"
        f"Title: {title}\n"
        f"The client wrote: {body or '(no description)'}\n"
        f"Why it matched: {reasons or '(no reasons recorded)'}\n\n"
        "Write the proposal now. Persian only, plain text."
    )


def build_brief(project: dict[str, Any], voice: list[dict[str, Any]]) -> str:
    """The whole instruction as one readable block, for the hand-written path."""
    return "\n\n".join([SYSTEM_RULES, _voice_block(voice), _project_block(project)])


def build_messages(project: dict[str, Any],
                   voice: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages for the API, ordered so the reusable part can be cached."""
    return [{
        "role": "user",
        "content": [
            # Stable across every draft in a run — marked cacheable.
            {"type": "text", "text": _voice_block(voice),
             "cache_control": {"type": "ephemeral"}},
            # Volatile: changes per project, so it must come after the breakpoint.
            {"type": "text", "text": _project_block(project)},
        ],
    }]


def parse_drafts(bundle: dict[str, Any]) -> dict[int, str]:
    """Read a written bundle back. Raises rather than silently dropping data."""
    drafts = bundle.get("drafts")
    if not isinstance(drafts, list):
        raise ValueError("bundle has no 'drafts' list")

    out: dict[int, str] = {}
    for entry in drafts:
        if not isinstance(entry, dict) or "project_id" not in entry:
            raise ValueError(f"draft entry has no project_id: {entry!r}")
        text = (entry.get("text") or "").strip()
        if text:
            out[int(entry["project_id"])] = text
    return out
