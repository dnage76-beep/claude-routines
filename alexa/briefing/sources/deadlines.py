"""
Deadlines source. Merges three signals:
  1. Hard-coded known deadlines Derek mentioned in CLAUDE.md (HIST-378 exhibit
     proposal Apr 28, Fall registration windows, etc.)
  2. Vault frontmatter — any note under Projects/ or Classes/ with a `due` or
     `deadline` field (pulled from the vault-snapshot gist, see vault.py).
  3. Calendar events tagged "due", "deadline", "submit", "proposal", etc.

Returns a unified sorted list of (what, when_text, raw_date).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any


# Hardcoded fallback list. These are facts pulled straight from ~/.claude/CLAUDE.md
# and keep the briefing useful even if the vault snapshot is stale.
KNOWN_DEADLINES: list[dict] = [
    {"what": "HIST-378 exhibit proposal", "date": "2026-04-28"},
    {"what": "HIST-378 final exhibit", "date": "2026-05-12"},
    {"what": "moveout from Tobego house", "date": "2026-06-01"},
    {"what": "Tesla business launch with Jordan", "date": "2026-05-25"},
]


_DEADLINE_KEYWORDS = re.compile(
    r"\b(due|deadline|submit|proposal|final|exam|midterm|interview|registration)\b",
    flags=re.IGNORECASE,
)


def _parse_date(s: str) -> date | None:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _relative(d: date, now: date) -> str:
    delta = (d - now).days
    if delta < 0:
        return "past due"
    if delta == 0:
        return "due today"
    if delta == 1:
        return "due tomorrow"
    if delta <= 7:
        return f"due in {delta} days"
    if delta <= 14:
        return f"due in about {delta // 7} weeks"
    # For further-out, speak the month and day.
    return f"due {d.strftime('%B')} {d.day}"


def collect(
    now: datetime | None = None,
    vault_deadlines: list[dict] | None = None,
    calendar_events: list[dict] | None = None,
) -> dict[str, Any]:
    """
    vault_deadlines: list of {what, date (YYYY-MM-DD)} pulled by vault.py
    calendar_events: normalized list from calendar.fetch_calendar (today+2)
    """
    now = now or datetime.now()
    today = now.date()
    horizon = today + timedelta(days=45)

    merged: dict[str, dict] = {}

    def add(what: str, d: date | None):
        if not d or d < today - timedelta(days=1) or d > horizon:
            return
        key = f"{what.lower()}|{d.isoformat()}"
        if key in merged:
            return
        merged[key] = {
            "what": what,
            "date": d.isoformat(),
            "when": _relative(d, today),
            "days_out": (d - today).days,
        }

    # Known deadlines.
    for item in KNOWN_DEADLINES:
        add(item["what"], _parse_date(item["date"]))

    # Vault frontmatter-extracted deadlines (see vault.py).
    for item in vault_deadlines or []:
        add(item.get("what", "").strip(), _parse_date(item.get("date", "")))

    # Calendar events that look like deadlines.
    for ev in calendar_events or []:
        summary = ev.get("raw_summary", "")
        if not _DEADLINE_KEYWORDS.search(summary):
            continue
        raw = ev.get("raw_start", "")
        parsed = None
        try:
            if "T" in raw:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
            else:
                parsed = _parse_date(raw)
        except Exception:
            parsed = None
        if parsed:
            add(summary, parsed)

    ordered = sorted(merged.values(), key=lambda x: x["days_out"])
    return {"deadlines": ordered, "error": None}
