"""
Google Calendar source. Pulls today + next 2 days of events using the
Calendar API directly (no client library). Returns normalized dicts the
voice layer can consume.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from . import google_oauth


_BASE = "https://www.googleapis.com/calendar/v3"

# Keyword map that turns opaque event titles into Sheldon-voice labels.
# Inherited from push_gists.py but trimmed to items that add value (not noise).
CAL_CONTEXT_MAP = {
    "kyle": "rehab with Kyle",
    "treatment": "rehab session",
    "rehab": "rehab",
    "volleyball": "volleyball",
    "practice": "volleyball practice",
    "mvb": "volleyball",
    "hist-378": "History of Aviation",
    "hist 378": "History of Aviation",
    "me 341": "Heat Transfer",
    "me 221": "Dynamics",
    "ece 330": "Electronics",
    "aia": "Athletes in Action",
    "jillian": "Jillian",
    "jordan": "Tesla business with Jordan",
    "sarver": "advising meeting",
    "schrag": "Professor Schrag meeting",
    "exhibit": "HIST-378 exhibit proposal",
    "career fair": "career fair",
    "interview": "interview",
}


def _fmt_time(iso: str, tz_offset_hours: int = -4) -> str:
    """Render a Calendar start time as Alexa-friendly '9 AM' / '2:30 PM'."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        # Google returns UTC for timed events. Convert to America/New_York.
        dt_local = dt.astimezone(timezone(timedelta(hours=tz_offset_hours)))
        hour = dt_local.hour
        minute = dt_local.minute
        suffix = "AM" if hour < 12 else "PM"
        h12 = hour % 12 or 12
        if minute == 0:
            return f"{h12} {suffix}"
        return f"{h12}:{minute:02d} {suffix}"
    except Exception:
        return ""


def _enrich(summary: str) -> str:
    """Apply the CAL_CONTEXT_MAP to a title. Returns the original if no match."""
    if not summary:
        return "an event"
    low = summary.lower()
    for trigger, replacement in CAL_CONTEXT_MAP.items():
        if trigger in low:
            # Don't double-up if original was already clear.
            if replacement.lower() in low:
                return summary
            return f"{summary} ({replacement})"
    return summary


def _fetch_range(time_min: datetime, time_max: datetime) -> list[dict]:
    headers = google_oauth.auth_headers()
    params = {
        "timeMin": time_min.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "timeMax": time_max.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "25",
    }
    resp = requests.get(
        f"{_BASE}/calendars/primary/events",
        headers=headers,
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def _normalize(ev: dict) -> dict:
    start = ev.get("start", {}) or {}
    raw_start = start.get("dateTime") or start.get("date") or ""
    time_str = _fmt_time(raw_start) if "T" in raw_start else "all day"
    summary = ev.get("summary") or "Untitled event"
    return {
        "summary": _enrich(summary),
        "raw_summary": summary,
        "time": time_str,
        "raw_start": raw_start,
        "location": (ev.get("location") or "").strip(),
    }


def fetch_calendar(now: datetime | None = None) -> dict[str, Any]:
    """
    Return a dict:
        {
          "today": [ {summary, time, location, raw_start, raw_summary}, ... ],
          "tomorrow": [ ... ],
          "day_after": [ ... ],
          "athletics_next": {summary, when, raw_start} or None,
          "error": None or str
        }
    """
    if now is None:
        now = datetime.now(tz=timezone(timedelta(hours=-4)))

    result: dict[str, Any] = {
        "today": [],
        "tomorrow": [],
        "day_after": [],
        "athletics_next": None,
        "error": None,
    }

    try:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_after_end = today_start + timedelta(days=3)
        items = _fetch_range(today_start, day_after_end)
    except Exception as exc:
        result["error"] = f"calendar fetch failed: {exc}"
        return result

    tomorrow_start = today_start + timedelta(days=1)
    day_after_start = today_start + timedelta(days=2)

    for ev in items:
        n = _normalize(ev)
        raw = n["raw_start"]
        try:
            if "T" in raw:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(now.tzinfo)
            else:
                dt = datetime.fromisoformat(raw).replace(tzinfo=now.tzinfo)
        except Exception:
            continue

        # Skip past events within today.
        if dt < now - timedelta(hours=1):
            continue

        if dt < tomorrow_start:
            result["today"].append(n)
        elif dt < day_after_start:
            result["tomorrow"].append(n)
        else:
            result["day_after"].append(n)

        # Athletics detection — pick the first future volleyball/practice hit.
        raw_low = n["raw_summary"].lower()
        if result["athletics_next"] is None and any(
            kw in raw_low for kw in ("volleyball", "mvb", "practice", "match", "tournament")
        ):
            delta_days = (dt.date() - now.date()).days
            if delta_days == 0:
                when = f"today at {n['time']}"
            elif delta_days == 1:
                when = f"tomorrow at {n['time']}"
            else:
                when = f"in {delta_days} days"
            result["athletics_next"] = {
                "summary": n["raw_summary"],
                "when": when,
                "raw_start": raw,
            }

    return result
