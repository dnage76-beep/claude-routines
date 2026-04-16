"""
Sheldon voice layer. Every string that Alexa reads aloud passes through here.

Rules (from ~/.claude/CLAUDE.md):
- No em dashes — use "--".
- No emojis.
- No filler ("Certainly!", "Great question!", "Here's what I found:").
- Terse, direct, conversational.
- Address Derek as "Derek", not "Mr. Nagel".
- Morning tone vs evening tone vs midday tone.
- Text must sound fine when TTS reads it. That means:
  - No markdown (* # _ [] backticks).
  - No URLs — strip them.
  - No multi-digit years in ambiguous formats ("2026-04-28" -> "April 28th").
  - Short sentences, one thought per sentence.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable


# ── tone openers ──────────────────────────────────────────────────────────────

def greeting(now: datetime) -> str:
    """Mode-appropriate opener in Sheldon's voice."""
    hour = now.hour
    weekday = now.strftime("%A")
    if hour < 5:
        return f"It's early, Derek. Here's the overnight."
    if hour < 11:
        return f"Morning, Derek. {weekday}, {format_date(now)}."
    if hour < 15:
        return f"Midday check-in, Derek."
    if hour < 19:
        return f"Afternoon, Derek."
    return f"Wrap-up for today, Derek."


def closer(now: datetime) -> str:
    hour = now.hour
    if hour < 11:
        return "That's the setup. Go get it."
    if hour < 15:
        return "That's where you stand."
    if hour < 19:
        return "Keep moving."
    return "That's the day. Rest up."


# ── formatters ────────────────────────────────────────────────────────────────

_MONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]


def format_date(d: datetime) -> str:
    """'April 16th' — how Alexa reads dates cleanly."""
    day = d.day
    suffix = "th"
    if day % 10 == 1 and day != 11:
        suffix = "st"
    elif day % 10 == 2 and day != 12:
        suffix = "nd"
    elif day % 10 == 3 and day != 13:
        suffix = "rd"
    return f"{_MONTHS[d.month - 1]} {day}{suffix}"


def format_time(d: datetime) -> str:
    """'9 AM' or '2:30 PM'. Alexa handles both fine, shorter is better."""
    hour = d.hour
    minute = d.minute
    suffix = "AM" if hour < 12 else "PM"
    h12 = hour % 12 or 12
    if minute == 0:
        return f"{h12} {suffix}"
    return f"{h12}:{minute:02d} {suffix}"


def days_until(target: datetime, now: datetime) -> str:
    """Human-readable relative date ("today", "tomorrow", "in 3 days")."""
    a = target.date()
    b = now.date()
    delta = (a - b).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    if 2 <= delta <= 6:
        return f"in {delta} days"
    if delta < 0:
        return f"{abs(delta)} days ago"
    return f"on {format_date(target)}"


# ── TTS-safe scrubber ─────────────────────────────────────────────────────────

_URL_RE = re.compile(r"https?://\S+")
_MARKDOWN_RE = re.compile(r"[\*_`#>]")
_EM_DASH_RE = re.compile(r"[—–]")
_MULTI_WS_RE = re.compile(r"\s+")
_BRACKETS_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")  # markdown links
# Matches wiki-style [[link]]
_WIKI_RE = re.compile(r"\[\[([^\]]+)\]\]")
_EMOJI_RE = re.compile(
    "["                    # rough emoji range
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "]",
    flags=re.UNICODE,
)


def clean(text: str) -> str:
    """Strip markdown, urls, emojis, em dashes, collapse whitespace."""
    if not text:
        return ""
    text = _BRACKETS_RE.sub(r"\1", text)    # [label](url) -> label
    text = _WIKI_RE.sub(r"\1", text)        # [[Note]] -> Note
    text = _URL_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = _MARKDOWN_RE.sub("", text)
    text = _EM_DASH_RE.sub("--", text)
    text = _MULTI_WS_RE.sub(" ", text)
    return text.strip()


def join_sentences(*parts: str) -> str:
    """Join non-empty strings into a single TTS block with single spaces.
    Ensures each part ends with terminal punctuation before joining, but does
    not rewrite punctuation inside a part.
    """
    cleaned = []
    for p in parts:
        c = clean(p)
        if not c:
            continue
        if c[-1] not in ".!?":
            c += "."
        cleaned.append(c)
    return " ".join(cleaned)


def narrate_list(items: Iterable[str], *, conjunction: str = "and") -> str:
    """Turn ['a', 'b', 'c'] into 'a, b, and c'. TTS-safe."""
    cleaned = [clean(x) for x in items if x and clean(x)]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} {conjunction} {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", {conjunction} {cleaned[-1]}"


# ── section builders (used by main.py) ────────────────────────────────────────

def section_calendar(today_events: list[dict], tomorrow_events: list[dict]) -> str:
    if not today_events and not tomorrow_events:
        return "Your calendar is clear today and tomorrow."
    parts = []
    if today_events:
        if len(today_events) == 1:
            e = today_events[0]
            parts.append(f"Today you have {e['summary']} at {e['time']}.")
        else:
            first = today_events[0]
            rest = [f"{e['summary']} at {e['time']}" for e in today_events[1:]]
            parts.append(
                f"You have {len(today_events)} things today. "
                f"First up, {first['summary']} at {first['time']}. "
                f"After that: {narrate_list(rest)}."
            )
    if tomorrow_events:
        previews = [f"{e['summary']} at {e['time']}" for e in tomorrow_events[:3]]
        parts.append(f"Tomorrow: {narrate_list(previews)}.")
    return " ".join(parts)


def section_deadlines(deadlines: list[dict]) -> str:
    if not deadlines:
        return "No deadlines coming up."
    top = deadlines[:3]
    lines = []
    for d in top:
        when = d.get("when", "soon")
        what = d.get("what", "something")
        lines.append(f"{what} {when}")
    return "Top deadlines: " + narrate_list(lines) + "."


def section_email(priorities: list[dict]) -> str:
    if not priorities:
        return "Nothing urgent in email."
    lines = []
    for e in priorities[:3]:
        sender = e.get("sender", "someone")
        subject = e.get("subject", "no subject")
        lines.append(f"{sender} sent '{subject}'")
    verb = "is" if len(priorities) == 1 else "are"
    count_word = "one" if len(priorities) == 1 else f"{len(priorities)}"
    tail = "email that needs a look" if len(priorities) == 1 else "emails that need a look"
    return f"In the inbox, there {verb} {count_word} {tail}. " + narrate_list(lines) + "."


def section_athletics(next_event: dict | None) -> str:
    if not next_event:
        return ""
    what = next_event.get("summary", "a volleyball commitment")
    when = next_event.get("when", "soon")
    return f"Volleyball: {what} {when}."


def section_vault(priorities: list[str]) -> str:
    if not priorities:
        return ""
    top = priorities[:3]
    return "Priorities on deck: " + narrate_list(top) + "."


def section_weather(w: dict | None) -> str:
    if not w:
        return ""
    temp = w.get("temp_f")
    desc = (w.get("desc") or "").lower()
    high = w.get("high_f")
    low = w.get("low_f")
    if not (temp and high and low):
        return ""
    return f"Weather in Fairfax: {temp} degrees, {desc}. High of {high}, low of {low}."
