"""
Athletics source. Reads the already-fetched calendar payload looking for
volleyball-shaped events. Keeps this separate from calendar.py because Derek
may later want to layer in a team schedule feed (GMU Athletics RSS) without
touching the calendar code.
"""

from __future__ import annotations


def next_athletics(calendar_data: dict) -> dict | None:
    """Returns the athletics_next dict from calendar.py, or None."""
    return calendar_data.get("athletics_next")
