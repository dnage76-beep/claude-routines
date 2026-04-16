#!/usr/bin/env python3
"""
Alexa briefing entry point (cloud-native).

Run:
    python3 -m briefing.main              # fetches + pushes 5 gists
    python3 -m briefing.main --dry-run    # prints each gist body, pushes nothing
    python3 -m briefing.main --mock       # uses mock data, pushes nothing

Environment variables (all required unless --mock/--dry-run):
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    GOOGLE_REFRESH_TOKEN
    GIST_TOKEN                     # GitHub PAT with `gist` scope
    ALEXA_GIST_MORNING_BRIEF       # gist id for morning-brief.json
    ALEXA_GIST_MESSAGE_SUMMARY     # gist id for message-summary.json
    ALEXA_GIST_EMAIL_SUMMARY       # gist id for email-summary.json
    ALEXA_GIST_UPCOMING_EVENTS     # gist id for upcoming-events.json
    ALEXA_GIST_NEWS_AND_WEATHER    # gist id for news-and-weather.json
    VAULT_SNAPSHOT_GIST_ID         # optional — adds vault priorities/deadlines
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

# Allow running both as a module (python -m briefing.main) and as a script.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
    from briefing import voice  # type: ignore
    from briefing.sources import (  # type: ignore
        athletics, calendar, deadlines, email as email_src, vault, weather,
    )
else:
    from . import voice
    from .sources import (
        athletics, calendar, deadlines, email as email_src, vault, weather,
    )


# ── Gist IDs resolved from env at runtime ──────────────────────────────────────

GIST_ENV_MAP = {
    "morning_brief":    ("ALEXA_GIST_MORNING_BRIEF",    "morning-brief.json"),
    "message_summary":  ("ALEXA_GIST_MESSAGE_SUMMARY",  "message-summary.json"),
    "email_summary":    ("ALEXA_GIST_EMAIL_SUMMARY",    "email-summary.json"),
    "upcoming_events":  ("ALEXA_GIST_UPCOMING_EVENTS",  "upcoming-events.json"),
    "news_and_weather": ("ALEXA_GIST_NEWS_AND_WEATHER", "news-and-weather.json"),
}

EASTERN = timezone(timedelta(hours=-4))  # America/New_York w/o pytz.


def make_feed(uid: str, title: str, text: str, now: datetime) -> list[dict]:
    """Alexa Flash Briefing JSON feed format."""
    return [{
        "uid": uid,
        "updateDate": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0Z"),
        "titleText": title,
        "mainText": text,
        "redirectionUrl": "https://www.amazon.com",
    }]


def push_gist(gist_id: str, filename: str, content: list[dict], token: str) -> tuple[bool, str]:
    try:
        resp = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"files": {filename: {"content": json.dumps(content)}}},
            timeout=15,
        )
        if resp.status_code == 200:
            return True, "ok"
        return False, f"HTTP {resp.status_code}: {resp.text[:120]}"
    except Exception as exc:
        return False, str(exc)


# ── Briefing text builders (one per gist) ─────────────────────────────────────

def build_morning_brief(ctx: dict) -> str:
    now = ctx["now"]
    return voice.join_sentences(
        voice.greeting(now),
        voice.section_weather(ctx["weather"]),
        voice.section_calendar(ctx["cal"]["today"], ctx["cal"]["tomorrow"]),
        voice.section_deadlines(ctx["deadlines"]),
        voice.section_email(ctx["email_priorities"]),
        voice.section_athletics(ctx["athletics_next"]),
        voice.section_vault(ctx["vault_priorities"]),
        voice.closer(now),
    )


def build_upcoming_events(ctx: dict) -> str:
    now = ctx["now"]
    return voice.join_sentences(
        f"Here's what's on your calendar, Derek.",
        voice.section_calendar(ctx["cal"]["today"], ctx["cal"]["tomorrow"]),
        voice.section_athletics(ctx["athletics_next"]),
    )


def build_email_summary(ctx: dict) -> str:
    return voice.join_sentences(
        "Here's the email rundown, Derek.",
        voice.section_email(ctx["email_priorities"]),
    )


def build_message_summary(ctx: dict) -> str:
    """
    iMessages are Mac-only. In the cloud build, this gist carries deadlines
    instead of messages — it reuses the existing Alexa feed slot without
    breaking Derek's skill layout. Local fallback can still overwrite this
    gist with real iMessages when the Mac is on.
    """
    return voice.join_sentences(
        "Deadline check, Derek.",
        voice.section_deadlines(ctx["deadlines"]),
        voice.section_vault(ctx["vault_priorities"]),
    )


def build_news_and_weather(ctx: dict) -> str:
    return voice.join_sentences(
        "Weather and conditions, Derek.",
        voice.section_weather(ctx["weather"]),
        "News coverage is handled by the main morning brief.",
    )


GENERATORS = {
    "morning_brief":    build_morning_brief,
    "upcoming_events":  build_upcoming_events,
    "email_summary":    build_email_summary,
    "message_summary":  build_message_summary,
    "news_and_weather": build_news_and_weather,
}


TITLES = {
    "morning_brief":    lambda n: f"Morning Brief for {voice.format_date(n)}",
    "upcoming_events":  lambda n: f"Calendar for {voice.format_date(n)}",
    "email_summary":    lambda n: f"Email Summary for {voice.format_date(n)}",
    "message_summary":  lambda n: f"Deadlines for {voice.format_date(n)}",
    "news_and_weather": lambda n: f"Weather for {voice.format_date(n)}",
}


# ── Context assembly ──────────────────────────────────────────────────────────

def assemble_context(now: datetime, mock: bool = False) -> dict[str, Any]:
    if mock:
        return _mock_context(now)

    cal_data = calendar.fetch_calendar(now=now)
    vault_data = vault.fetch_vault()
    email_data = email_src.fetch_priorities(lookback_hours=24)
    weather_data = weather.fetch_weather()
    dl = deadlines.collect(
        now=now,
        vault_deadlines=vault_data.get("deadlines", []),
        calendar_events=cal_data.get("today", []) + cal_data.get("tomorrow", []),
    )
    return {
        "now": now,
        "cal": cal_data,
        "vault_priorities": vault_data.get("priorities", []),
        "email_priorities": email_data.get("priorities", []),
        "weather": weather_data,
        "deadlines": dl.get("deadlines", []),
        "athletics_next": athletics.next_athletics(cal_data),
        "errors": {
            "calendar": cal_data.get("error"),
            "vault": vault_data.get("error"),
            "email": email_data.get("error"),
        },
    }


def _mock_context(now: datetime) -> dict:
    """Static fake data for --mock / --dry-run local preview."""
    return {
        "now": now,
        "cal": {
            "today": [
                {"summary": "Dynamics (ME 221)", "time": "9 AM", "raw_summary": "ME 221 Lecture", "raw_start": ""},
                {"summary": "rehab with Kyle", "time": "1 PM", "raw_summary": "Kyle treatment", "raw_start": ""},
                {"summary": "Tesla business with Jordan (call)", "time": "6 PM", "raw_summary": "Jordan call", "raw_start": ""},
            ],
            "tomorrow": [
                {"summary": "Heat Transfer (ME 341)", "time": "10 AM", "raw_summary": "ME 341 Lecture", "raw_start": ""},
                {"summary": "Athletes in Action", "time": "7 PM", "raw_summary": "AIA", "raw_start": ""},
            ],
            "day_after": [],
            "athletics_next": None,
        },
        "vault_priorities": [
            "Tesla auto repair business launches late May",
            "HIST-378 exhibit proposal is the next academic deadline",
            "Lock down fall schedule before summer",
        ],
        "email_priorities": [
            {"sender": "Sophia Sarver", "subject": "Advising appointment options for fall",
             "snippet": "Here are three windows that work on my end", "score": 92},
            {"sender": "Donald Osborn", "subject": "Northrop Grumman -- intern referral follow-up",
             "snippet": "Checking in on your application status", "score": 88},
            {"sender": "Tobego Housing", "subject": "Moveout walkthrough scheduling",
             "snippet": "Please confirm a date before May 20", "score": 80},
        ],
        "weather": {
            "temp_f": 64, "desc": "Partly cloudy", "feels_f": 62,
            "high_f": 72, "low_f": 51, "precip_pct": 10,
        },
        "deadlines": [
            {"what": "HIST-378 exhibit proposal", "when": "due in 12 days", "days_out": 12, "date": "2026-04-28"},
            {"what": "Tesla business launch with Jordan", "when": "due in about 5 weeks", "days_out": 39, "date": "2026-05-25"},
            {"what": "moveout from Tobego house", "when": "due about 6 weeks", "days_out": 46, "date": "2026-06-01"},
        ],
        "athletics_next": {
            "summary": "GMU MVB practice",
            "when": "tomorrow at 4 PM",
        },
        "errors": {},
    }


# ── Runner ────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, mock: bool = False) -> int:
    now = datetime.now(tz=EASTERN)
    ctx = assemble_context(now, mock=mock)

    # Build every brief text up-front.
    briefs: dict[str, str] = {k: gen(ctx) for k, gen in GENERATORS.items()}

    if dry_run or mock:
        for key, text in briefs.items():
            header = TITLES[key](now)
            print(f"\n── {key.upper()}  [{header}] ──")
            print(text)
        errors = ctx.get("errors", {})
        if any(errors.values()):
            print("\n(warnings)")
            for k, v in errors.items():
                if v:
                    print(f"  {k}: {v}")
        return 0

    # Real push.
    token = os.environ.get("GIST_TOKEN")
    if not token:
        print("ERR: GIST_TOKEN not set", file=sys.stderr)
        return 2

    overall_ok = True
    for key, text in briefs.items():
        env_name, filename = GIST_ENV_MAP[key]
        gist_id = os.environ.get(env_name)
        if not gist_id:
            print(f"SKIP: {key} (env {env_name} unset)")
            continue
        feed = make_feed(f"{key}-{int(now.timestamp())}", TITLES[key](now), text, now)
        ok, info = push_gist(gist_id, filename, feed, token)
        status = "OK " if ok else "ERR"
        print(f"  {status} {key:<18} {filename:<24} {info}")
        if not ok:
            overall_ok = False

    return 0 if overall_ok else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch live data but print the output instead of pushing.")
    parser.add_argument("--mock", action="store_true",
                        help="Use static mock data. Fast preview, no credentials needed.")
    args = parser.parse_args()
    sys.exit(run(dry_run=args.dry_run, mock=args.mock))


if __name__ == "__main__":
    main()
