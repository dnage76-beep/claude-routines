"""
Gmail source. Reads Derek's primary inbox via the Gmail API using a refresh
token (shared with calendar). Scores by the same life-context engine from
push_gists.py so the briefing surfaces things that actually matter.
"""

from __future__ import annotations

import base64
from email.utils import parseaddr
from typing import Any

import requests

from . import google_oauth


_BASE = "https://gmail.googleapis.com/gmail/v1"


# ── life-context signal — carried forward from push_gists.py ──────────────────
IMPORTANT_SENDERS = [
    "gmu.edu", "mason.edu", "northrop", "nasa", "ngc.com", "lstech",
    "ty lin", "tesla", "astronics", "nagel", "gibbons",
    # Named people Derek deals with:
    "donald.osborn", "ssarver", "tbooker", "foltz", "schrag",
]

PROMO_KEYWORDS = [
    "unsubscribe", "no-reply", "noreply", "newsletter", "marketing",
    "welcome@", "hello@", "info@", "support@", "supabase", "donotreply",
    "notification@", "updates@", "digest", "coupon", "offer", "deal",
    "promo", "sale", "discount", "free trial",
]

EMAIL_BOOST_KEYWORDS = [
    "internship", "interview", "offer", "application", "resume", "career",
    "tesla", "repair", "jordan", "llc", "business",
    "gmu", "mason", "george mason", "canvas", "blackboard", "assignment", "exam",
    "grade", "professor", "class", "course", "scholarship",
    "volleyball", "athletes in action", "aia",
    "tobego", "lease", "rent", "housing", "moveout",
    "jillian", "mom", "dad", "sarah", "diana", "oma",
    "northrop", "ngc", "nasa", "ty lin", "ls tech",
    "openclaw", "sheldon", "railway", "google cloud", "billing",
    "flight", "aviation",
]


def _score(email: dict) -> int:
    from_addr = (email.get("from") or "").lower()
    subject = (email.get("subject") or "").lower()
    snippet = (email.get("snippet") or "").lower()
    combined = f"{from_addr} {subject} {snippet}"
    score = 50
    for s in IMPORTANT_SENDERS:
        if s in from_addr:
            score += 30
            break
    for kw in EMAIL_BOOST_KEYWORDS:
        if kw in combined:
            score += 10
    for g in ("no-reply", "noreply", "donotreply", "notification@", "updates@", "alert@"):
        if g in from_addr:
            score -= 15
            break
    return min(score, 100)


def _is_promo(email: dict) -> bool:
    from_addr = (email.get("from") or "").lower()
    subject = (email.get("subject") or "").lower()
    labels = [l.lower() for l in email.get("labelIds", [])]

    # Known-important sender always wins.
    if any(s in from_addr for s in IMPORTANT_SENDERS):
        return False
    if "category_promotions" in labels or "category_social" in labels:
        return True
    if any(k in from_addr for k in PROMO_KEYWORDS):
        return True
    if any(k in subject for k in ("unsubscribe", "newsletter", "offer", "deal", "sale", "welcome")):
        return True
    return False


def _headers_to_dict(headers: list[dict]) -> dict:
    return {h["name"].lower(): h["value"] for h in headers}


def _pretty_sender(raw_from: str) -> str:
    name, addr = parseaddr(raw_from or "")
    return name or addr or "an unknown sender"


def _fetch_one(msg_id: str) -> dict | None:
    """Fetch a single message's headers + snippet + labels."""
    try:
        resp = requests.get(
            f"{_BASE}/users/me/messages/{msg_id}",
            headers=google_oauth.auth_headers(),
            params={"format": "metadata",
                    "metadataHeaders": ["From", "Subject", "Date"]},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        headers = _headers_to_dict(data.get("payload", {}).get("headers", []))
        return {
            "id": msg_id,
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": data.get("snippet", ""),
            "labelIds": data.get("labelIds", []),
        }
    except Exception:
        return None


def fetch_priorities(lookback_hours: int = 24, max_ids: int = 40) -> dict[str, Any]:
    """
    Return:
        {
          "priorities": [ {sender, subject, snippet, score}, ... ],
          "total": int,
          "error": None or str,
        }
    """
    result: dict[str, Any] = {"priorities": [], "total": 0, "error": None}

    query = f"newer_than:{max(1, int(lookback_hours / 24))}d -category:promotions -category:social -is:newsletter"
    try:
        listing = requests.get(
            f"{_BASE}/users/me/messages",
            headers=google_oauth.auth_headers(),
            params={"q": query, "maxResults": str(max_ids)},
            timeout=15,
        )
        listing.raise_for_status()
        ids = [m["id"] for m in listing.json().get("messages", [])]
    except Exception as exc:
        result["error"] = f"gmail list failed: {exc}"
        return result

    fetched = []
    for mid in ids[:max_ids]:
        one = _fetch_one(mid)
        if one:
            fetched.append(one)

    non_promo = [e for e in fetched if not _is_promo(e)]
    for e in non_promo:
        e["score"] = _score(e)
    non_promo.sort(key=lambda x: x["score"], reverse=True)

    top = []
    for e in non_promo[:3]:
        if e["score"] < 30:
            continue
        top.append({
            "sender": _pretty_sender(e["from"]),
            "subject": (e["subject"] or "no subject")[:80],
            "snippet": (e["snippet"] or "")[:140],
            "score": e["score"],
        })

    result["priorities"] = top
    result["total"] = len(non_promo)
    return result
