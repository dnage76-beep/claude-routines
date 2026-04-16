"""
Weather source. Public wttr.in JSON, no auth required. Best-effort — a miss
just drops the weather line from the brief.
"""

from __future__ import annotations

import requests


def fetch_weather(location: str = "Fairfax,VA") -> dict:
    try:
        resp = requests.get(
            f"https://wttr.in/{location}?format=j1",
            timeout=8,
            headers={"User-Agent": "claude-routines alexa briefing"},
        )
        resp.raise_for_status()
        data = resp.json()
        current = data["current_condition"][0]
        today = data["weather"][0]
        return {
            "temp_f": int(current["temp_F"]),
            "desc": current["weatherDesc"][0]["value"],
            "feels_f": int(current["FeelsLikeF"]),
            "high_f": int(today["maxtempF"]),
            "low_f": int(today["mintempF"]),
            "precip_pct": int(today.get("hourly", [{}])[6].get("chanceofrain", "0") or 0),
        }
    except Exception:
        return {}
