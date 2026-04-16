"""Phase 2B: Actionable-item extractor → Apple Reminders "Sheldon Inbox".

Runs after (or alongside) the daily triage. Scans the last 24h across Derek's
three inboxes, applies a strict actionable filter, and creates Apple Reminders
for the small number of items that truly require an action with a deadline.

Design notes:
- Reuses the gmail-multi OAuth tokens at mcp-servers/gmail-multi/tokens/.
- Reuses the same Apple Mail.app envelope-index read pattern as mail-exchange.
- Reads the Reminders SQLite DB for dedup; writes via osascript.
- HARD CAP of 5 reminders per run. Most days should create 0-2.
- STRICT actionable bar: clear reply-needed OR explicit deadline. Nothing else.

Run:
    mcp-servers/gmail-multi/.venv/bin/python scheduled/reminders/extractor.py
    mcp-servers/gmail-multi/.venv/bin/python scheduled/reminders/extractor.py --dry-run
    mcp-servers/gmail-multi/.venv/bin/python scheduled/reminders/extractor.py --since-hours 48

Output:
    stdout:  JSON summary (one object per created reminder)
    stderr:  human-readable log lines ("created N reminders: ...")

Exit codes:
    0 on success (including "0 reminders created").
    1 on unrecoverable error.
"""
from __future__ import annotations

import argparse
import email
import email.policy
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable

# ----------------------------------------------------------------------------
# Paths / config
# ----------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
GMAIL_SERVER_DIR = REPO_ROOT / "mcp-servers" / "gmail-multi"
GMAIL_CONFIG = GMAIL_SERVER_DIR / "config.json"
GMAIL_TOKENS_DIR = GMAIL_SERVER_DIR / "tokens"

MAIL_ROOT = Path.home() / "Library" / "Mail" / "V10"
ENVELOPE_DB = MAIL_ROOT / "MailData" / "Envelope Index"
EXCHANGE_ACCOUNT_UUID = "00EC10D3-DDC8-4213-93CE-8906B6CB949B"

REMINDERS_STORES_DIR = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "group.com.apple.reminders"
    / "Container_v1"
    / "Stores"
)
SHELDON_LIST_NAME = "Sheldon Inbox"
MAX_REMINDERS_PER_RUN = 5
DEFAULT_SINCE_HOURS = 24

# ----------------------------------------------------------------------------
# Lazy Google API imports (only needed when Gmail sources are enabled)
# ----------------------------------------------------------------------------
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _build_gmail_service(token_path: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# ----------------------------------------------------------------------------
# Strict actionable classifier
# ----------------------------------------------------------------------------
#
# We bucket qualifying mail into priority tiers (lower = higher priority):
#   1 - Tesla auto-repair business (#1 priority per CLAUDE.md)
#   2 - Interviews / interview scheduling / phone screens
#   3 - Job hunt: offers, replies from recruiters, Donald Osborn / Northrop
#   4 - Hard academic deadlines (HIST-378 exhibit proposal, exam schedules,
#       grade disputes, formal advisor asks)
#   5 - Athletes in Action coordination needing Derek's action as president
#   6 - Generic "please reply" from a known inner-circle contact
#
# Anything that doesn't fit one of those tiers is filtered out, aggressively.

PROMO_SENDER_HINTS = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|newsletter|"
    r"notifications?@|updates?@|news@|promo|marketing|billing@|receipts?@|"
    r"alerts?@|security-?noreply|team@.*(usps|ups|fedex|dhl)|"
    r"@email\.|@e\.|@mail\.|@m\.|@news\.|@marketing\.|@promo\.)",
    re.IGNORECASE,
)

# If the FROM address domain matches any of these, reject outright — these are
# bulk/transactional senders and Derek has no need to reply to them, even when
# the word "action" appears in the subject line.
PROMO_DOMAIN_HINTS = re.compile(
    r"@(livenation|ticketmaster|stubhub|namecheap|godaddy|"
    r"criteriacorp|wellfound|indeed|linkedin|ziprecruiter|glassdoor|"
    r"usps|ups|fedex|dhl|amazon|ebay|etsy|paypal|venmo|"
    r"spotify|netflix|hulu|apple\.com|google\.com|"
    r"youtube|instagram|facebook|tiktok|twitter|reddit|"
    r"github\.com|notion|slack)",
    re.IGNORECASE,
)

PROMO_SUBJECT_HINTS = re.compile(
    r"(unsubscribe|newsletter|% off|discount|sale ends|flash sale|"
    r"your order|order #|tracking|shipped|delivered|"
    r"verification code|your code is|\b2fa\b|two-factor|"
    r"password reset|welcome to|statement available|"
    r"payment received|thank you for your purchase|receipt from|"
    r"upcoming concert|just announced|tour dates|"
    r"your weekly|your monthly|digest)",
    re.IGNORECASE,
)

TESLA_HINTS = re.compile(
    r"(tesla|auto.?repair|\bmodel\s?[3ysx]\b|"
    r"fsd\b|repair shop|diagnostic|body shop)",
    re.IGNORECASE,
)

# Interview hints -- only checked against subject+sender-name, NOT body, to
# avoid false positives from random marketing copy.
INTERVIEW_HINTS = re.compile(
    r"(\binterview\b|phone\s?screen|technical\s?screen|\bon-?site\s+interview|"
    r"schedule (a|our|the) (call|chat|meeting|interview)|"
    r"next\s?steps|\bround\s?\d)",
    re.IGNORECASE,
)

JOB_HUNT_HINTS = re.compile(
    r"(\bapplication\b|\brecruiter\b|recruiting|hiring\s?manager|offer letter|"
    r"job opportunity|role at|position at|\breq\s?\d|requisition|"
    r"northrop|grumman|osborn|ls.?tech|\binternship\b|\bco-?op\b)",
    re.IGNORECASE,
)

# Academic hints -- require at least one strong academic token. Generic words
# like "deadline" alone are not enough.
ACADEMIC_STRONG_HINTS = re.compile(
    r"(hist.?378|me.?341|me.?221|ece.?330|syst\s?\d|"
    r"exhibit proposal|lab report|midterm|final exam|"
    r"canvas assignment|homework\s?\d|hw\s?\d|"
    r"gmu|george mason|mason\.edu|@gmu\.edu)",
    re.IGNORECASE,
)
ACADEMIC_CONTEXT_HINTS = re.compile(
    r"(professor|prof\.|advisor|office hours|transcript|"
    r"registrar|registration|grade\b|exam schedule)",
    re.IGNORECASE,
)

AIA_HINTS = re.compile(
    r"(athletes in action|\baia\b|bible study|small\s?group|campus ministry|"
    r"prayer team)",
    re.IGNORECASE,
)

INNER_CIRCLE_EMAILS = {
    # Family
    "tricianagel73@gmail.com",
    "ptnagel@gmail.com",
    "sgnagel18@gmail.com",
    # School / advisors
    "ssarver@gmu.edu",
    "tbooker@gmu.edu",
    "nrogers1@gmu.edu",
    # Career leads
    "donald.osborn2@ngc.com",
    "kim.christman@lstechllc.com",
    # Housing
    "vickihuttar@gmail.com",
    "dhuttar@gmail.com",
    "danielrnyk@yahoo.com",
    # Academic
    # professors change per semester — add via config if needed
}

ACTION_VERB_HINTS = re.compile(
    r"(please (reply|respond|confirm|fill|sign|submit|review)|"
    r"can you (send|confirm|reply|review|forward)|"
    r"let me know|waiting on|when can|are you available|"
    r"need(s|ed)? (your|a) (response|reply|signature|answer|decision)|"
    r"action required|response required|requires your attention|"
    r"by (monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"tomorrow|end of (day|week)|eod|eow|\d{1,2}(st|nd|rd|th)?))",
    re.IGNORECASE,
)

DATE_WORDS = re.compile(
    r"\b(?:by |due (?:by |on )?|before |no later than )?"
    r"(?P<date>"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{2,4})?"
    r"|\d{1,2}/\d{1,2}(?:/\d{2,4})?"
    r"|(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?(?:\s+(?:morning|afternoon|evening))?"
    r"|tomorrow|tonight|today|end of (?:day|week)|eod|eow"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class Candidate:
    source: str               # "gmail:personal" | "gmail:secondary" | "exchange"
    message_id: str           # opaque id for dedup / URL
    gmail_url: str | None     # if gmail, a direct message URL
    sender_name: str
    sender_email: str
    subject: str
    snippet: str
    received: datetime
    body_preview: str = ""    # up to 2000 chars, only when needed
    priority: int = 99        # 1 = highest, 99 = skip
    category: str = ""        # "tesla" | "interview" | "job" | "academic" | "aia" | "reply"
    action_verb: str = "Reply"
    inferred_due: datetime | None = None
    rationale: str = ""       # why we flagged it (for logs/dry-run)


def _classify(cand: Candidate) -> None:
    """Mutate cand in place: set priority/category/action_verb/rationale.

    Strict filter: if we can't clearly identify BOTH a category AND an action
    signal, we leave priority=99 (skipped).
    """
    sender = f"{cand.sender_name} <{cand.sender_email}>".lower()
    subj = cand.subject.lower()
    snip = cand.snippet.lower()
    body = cand.body_preview.lower()
    full = f"{subj} {snip} {body}"

    # Immediate rejects (promo / automated)
    if PROMO_SENDER_HINTS.search(sender):
        cand.rationale = "rejected: automated/no-reply sender"
        return
    if PROMO_SUBJECT_HINTS.search(subj):
        cand.rationale = "rejected: promo/transactional subject"
        return

    sender_email_lc = cand.sender_email.lower().strip()
    from_inner_circle = sender_email_lc in INNER_CIRCLE_EMAILS

    has_action_signal = bool(ACTION_VERB_HINTS.search(full)) or bool(
        INTERVIEW_HINTS.search(full)
    )

    # Priority 1: Tesla business
    if TESLA_HINTS.search(full):
        # Only if there's actually an action request (replies, scheduling, quotes)
        if has_action_signal or "jordan" in sender:
            cand.priority = 1
            cand.category = "tesla"
            cand.action_verb = "Handle"
            cand.rationale = "Tesla auto-repair business action"
            return

    # Priority 2: Interviews
    if INTERVIEW_HINTS.search(full):
        cand.priority = 2
        cand.category = "interview"
        cand.action_verb = "Reply re interview"
        cand.rationale = "interview scheduling / phone screen"
        return

    # Priority 3: Job hunt
    if JOB_HUNT_HINTS.search(full) and (has_action_signal or from_inner_circle):
        cand.priority = 3
        cand.category = "job"
        cand.action_verb = "Reply"
        cand.rationale = "job hunt with action signal"
        return

    # Priority 4: Academic deadlines
    if ACADEMIC_HINTS.search(full):
        # Needs an action signal OR an explicit date word
        if has_action_signal or DATE_WORDS.search(full):
            cand.priority = 4
            cand.category = "academic"
            cand.action_verb = "Handle"
            cand.rationale = "academic deadline / professor ask"
            return

    # Priority 5: Athletes in Action coordination
    if AIA_HINTS.search(full) and has_action_signal:
        cand.priority = 5
        cand.category = "aia"
        cand.action_verb = "Reply"
        cand.rationale = "AIA coordination needs Derek"
        return

    # Priority 6: Inner-circle direct ask
    if from_inner_circle and has_action_signal:
        cand.priority = 6
        cand.category = "reply"
        cand.action_verb = "Reply"
        cand.rationale = "inner-circle contact asking for response"
        return

    cand.rationale = "no category matched (skipped by strict filter)"


def _infer_due(cand: Candidate, run_time: datetime) -> datetime:
    """Pick a due date based on category + body hints."""
    # Try explicit date words in body/subject first.
    text = f"{cand.subject} {cand.snippet} {cand.body_preview}"
    m = DATE_WORDS.search(text)
    if m:
        parsed = _parse_date_phrase(m.group("date"), run_time)
        if parsed and parsed > run_time:
            return parsed

    # Defaults by category
    if cand.category == "interview":
        return (run_time + timedelta(hours=12)).replace(minute=0, second=0, microsecond=0)
    if cand.category == "tesla":
        return (run_time + timedelta(hours=12)).replace(minute=0, second=0, microsecond=0)
    if cand.category == "job":
        return (run_time + timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
    if cand.category == "academic":
        # Soft default a week out if no explicit date was found.
        return (run_time + timedelta(days=5)).replace(hour=9, minute=0, second=0, microsecond=0)
    if cand.category == "aia":
        return (run_time + timedelta(hours=36)).replace(minute=0, second=0, microsecond=0)
    # Default: within 24h
    return (run_time + timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_WEEKDAYS = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


def _parse_date_phrase(phrase: str, now: datetime) -> datetime | None:
    """Best-effort parse of a human date phrase extracted from the body."""
    p = phrase.strip().lower().rstrip(".,")
    if p in {"today", "tonight"}:
        return now.replace(hour=20, minute=0, second=0, microsecond=0)
    if p == "tomorrow":
        return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    if p in {"eod", "end of day"}:
        return now.replace(hour=17, minute=0, second=0, microsecond=0)
    if p in {"eow", "end of week"}:
        days_until_fri = (4 - now.weekday()) % 7 or 7
        return (now + timedelta(days=days_until_fri)).replace(hour=17, minute=0, second=0, microsecond=0)

    # Weekday only: "Friday", "next Tuesday"
    for k, dow in _WEEKDAYS.items():
        if p.startswith(k):
            delta = (dow - now.weekday()) % 7 or 7
            return (now + timedelta(days=delta)).replace(hour=9, minute=0, second=0, microsecond=0)

    # Month + day: "Apr 28", "April 28, 2026"
    for k, month in _MONTHS.items():
        m = re.match(rf"{k}[a-z]*\.?\s+(\d{{1,2}})(?:(?:st|nd|rd|th))?(?:,?\s+(\d{{2,4}}))?$", p)
        if m:
            day = int(m.group(1))
            year = int(m.group(2)) if m.group(2) else now.year
            if year < 100:
                year += 2000
            try:
                dt = datetime(year, month, day, 9, 0, tzinfo=now.tzinfo)
                if dt < now - timedelta(days=60):
                    # Almost certainly next year
                    dt = dt.replace(year=year + 1)
                return dt
            except ValueError:
                return None

    # Numeric M/D or M/D/Y
    m = re.match(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", p)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100:
            year += 2000
        try:
            dt = datetime(year, month, day, 9, 0, tzinfo=now.tzinfo)
            if dt < now - timedelta(days=60):
                dt = dt.replace(year=year + 1)
            return dt
        except ValueError:
            return None
    return None


# ----------------------------------------------------------------------------
# Gmail source
# ----------------------------------------------------------------------------
def _gmail_query(since: datetime) -> str:
    # Exclude the firehose, include anchored-to-Derek threads
    date_str = since.strftime("%Y/%m/%d")
    return (
        f"after:{date_str} "
        f"-category:promotions -category:social -category:forums "
        f"-is:chat -from:noreply -from:no-reply"
    )


def _extract_gmail_body(payload: dict) -> str:
    import base64

    def walk(part: dict) -> str:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for sub in part.get("parts", []) or []:
            t = walk(sub)
            if t:
                return t
        if data and mime == "text/html":
            raw = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            stripped = re.sub(r"<[^>]+>", " ", raw)
            return html.unescape(re.sub(r"\s+", " ", stripped))
        return ""

    return walk(payload)[:2000]


def _load_gmail_candidates(since_hours: int, verbose: bool = False) -> list[Candidate]:
    if not GMAIL_CONFIG.exists():
        if verbose:
            print("gmail config not found — skipping Gmail sources", file=sys.stderr)
        return []
    try:
        config = json.loads(GMAIL_CONFIG.read_text())
    except Exception as exc:
        print(f"gmail config read failed: {exc}", file=sys.stderr)
        return []

    since = datetime.now(tz=timezone.utc) - timedelta(hours=since_hours)
    query = _gmail_query(since)
    cands: list[Candidate] = []

    for nick, info in config.get("accounts", {}).items():
        token_path = GMAIL_TOKENS_DIR / f"{nick}.json"
        if not token_path.exists():
            if verbose:
                print(f"skip gmail:{nick} — no token", file=sys.stderr)
            continue
        try:
            svc = _build_gmail_service(token_path)
        except Exception as exc:
            print(f"gmail:{nick} auth failed: {exc}", file=sys.stderr)
            continue
        try:
            resp = (
                svc.users()
                .messages()
                .list(userId="me", q=query, maxResults=50)
                .execute()
            )
        except Exception as exc:
            print(f"gmail:{nick} list failed: {exc}", file=sys.stderr)
            continue

        ids = [m["id"] for m in resp.get("messages", [])]
        for mid in ids:
            try:
                msg = (
                    svc.users()
                    .messages()
                    .get(userId="me", id=mid, format="full")
                    .execute()
                )
            except Exception:
                continue
            headers = {
                h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])
            }
            from_raw = headers.get("from", "")
            name, addr = parseaddr(from_raw)
            subj = headers.get("subject", "(no subject)")
            snippet = msg.get("snippet", "")
            body = _extract_gmail_body(msg.get("payload", {}))
            try:
                received = parsedate_to_datetime(headers.get("date", ""))
                if received.tzinfo is None:
                    received = received.replace(tzinfo=timezone.utc)
            except Exception:
                received = datetime.now(tz=timezone.utc)

            cand = Candidate(
                source=f"gmail:{nick}",
                message_id=mid,
                gmail_url=f"https://mail.google.com/mail/u/{info.get('email', '')}/#inbox/{mid}",
                sender_name=name or addr,
                sender_email=addr.lower(),
                subject=subj,
                snippet=snippet,
                received=received,
                body_preview=body,
            )
            cands.append(cand)
    return cands


# ----------------------------------------------------------------------------
# Exchange (GMU) source — mirrors mcp-servers/mail-exchange/server.py
# ----------------------------------------------------------------------------
def _copy_envelope_db() -> str:
    tmp = Path(tempfile.gettempdir()) / "envelope_copy_phase2b.sqlite"
    shutil.copy(ENVELOPE_DB, tmp)
    for suffix in ("-shm", "-wal"):
        src = Path(f"{ENVELOPE_DB}{suffix}")
        if src.exists():
            shutil.copy(src, f"{tmp}{suffix}")
    return str(tmp)


def _find_emlx(message_rowid: int, remote_id: str | None) -> Path | None:
    if not remote_id:
        return None
    stem = remote_id.split(":")[-1][:40]
    inbox_dir = MAIL_ROOT / EXCHANGE_ACCOUNT_UUID / "Inbox.mbox"
    if not inbox_dir.exists():
        return None
    for match in inbox_dir.rglob("*.emlx"):
        if match.stem.startswith(stem) or match.stem == str(message_rowid):
            return match
    return None


def _parse_emlx_body(path: Path) -> str:
    raw = path.read_bytes()
    first_newline = raw.index(b"\n")
    length = int(raw[:first_newline])
    body_bytes = raw[first_newline + 1 : first_newline + 1 + length]
    msg = email.message_from_bytes(body_bytes, policy=email.policy.default)
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                text = part.get_content()
                break
        if not text:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    h = part.get_content()
                    text = re.sub(r"<[^>]+>", "", h)
                    text = re.sub(r"\s+\n", "\n", text)
                    break
    else:
        text = msg.get_content()
    return text.strip()[:2000]


def _load_exchange_candidates(since_hours: int, verbose: bool = False) -> list[Candidate]:
    if not ENVELOPE_DB.exists():
        if verbose:
            print("mail envelope db not found — skipping Exchange", file=sys.stderr)
        return []
    try:
        db_path = _copy_envelope_db()
    except Exception as exc:
        print(f"exchange copy failed: {exc}", file=sys.stderr)
        return []

    cands: list[Candidate] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        url = f"ews://{EXCHANGE_ACCOUNT_UUID}/Inbox"
        row = conn.execute("SELECT ROWID FROM mailboxes WHERE url = ?", (url,)).fetchone()
        if not row:
            return []
        mbox_id = row["ROWID"]
        cutoff = int((datetime.now(tz=timezone.utc) - timedelta(hours=since_hours)).timestamp())
        rows = conn.execute(
            """
            SELECT m.ROWID AS id, m.date_sent, m.remote_id,
                   s.subject AS subject, a.address AS from_addr, a.comment AS from_name
            FROM messages m
            LEFT JOIN subjects s ON s.ROWID = m.subject
            LEFT JOIN addresses a ON a.ROWID = m.sender
            WHERE m.mailbox = ? AND m.date_sent >= ?
            ORDER BY m.date_sent DESC
            LIMIT 100
            """,
            (mbox_id, cutoff),
        ).fetchall()
    except Exception as exc:
        print(f"exchange query failed: {exc}", file=sys.stderr)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

    for r in rows:
        received = datetime.fromtimestamp(r["date_sent"], tz=timezone.utc)
        body_preview = ""
        emlx_path = _find_emlx(r["id"], r["remote_id"])
        if emlx_path:
            try:
                body_preview = _parse_emlx_body(emlx_path)
            except Exception:
                body_preview = ""
        cands.append(
            Candidate(
                source="exchange",
                message_id=f"gmu:{r['id']}",
                gmail_url=None,
                sender_name=r["from_name"] or r["from_addr"] or "",
                sender_email=(r["from_addr"] or "").lower(),
                subject=r["subject"] or "(no subject)",
                snippet=body_preview[:200],
                received=received,
                body_preview=body_preview,
            )
        )
    return cands


# ----------------------------------------------------------------------------
# Dedup via Reminders SQLite
# ----------------------------------------------------------------------------
def _load_existing_reminder_titles() -> set[str]:
    """Read titles of non-completed reminders in 'Sheldon Inbox' from every
    local Reminders store. Returns lowercased set for loose matching."""
    titles: set[str] = set()
    for db_path in REMINDERS_STORES_DIR.glob("Data-*.sqlite"):
        try:
            # Copy to sidestep WAL locking
            tmp = Path(tempfile.gettempdir()) / f"reminders_copy_{db_path.name}"
            shutil.copy(db_path, tmp)
            for suffix in ("-shm", "-wal"):
                src = Path(f"{db_path}{suffix}")
                if src.exists():
                    shutil.copy(src, f"{tmp}{suffix}")
            conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            list_row = conn.execute(
                "SELECT Z_PK FROM ZREMCDBASELIST "
                "WHERE ZNAME = ? "
                "AND (ZMARKEDFORDELETION = 0 OR ZMARKEDFORDELETION IS NULL)",
                (SHELDON_LIST_NAME,),
            ).fetchone()
            if not list_row:
                conn.close()
                continue
            list_pk = list_row["Z_PK"]
            rows = conn.execute(
                "SELECT ZTITLE FROM ZREMCDREMINDER "
                "WHERE ZLIST = ? "
                "AND (ZCOMPLETED = 0 OR ZCOMPLETED IS NULL) "
                "AND (ZMARKEDFORDELETION = 0 OR ZMARKEDFORDELETION IS NULL)",
                (list_pk,),
            ).fetchall()
            for row in rows:
                t = (row["ZTITLE"] or "").strip().lower()
                if t:
                    titles.add(t)
            conn.close()
        except Exception as exc:
            print(f"dedup scan failed for {db_path.name}: {exc}", file=sys.stderr)
            continue
    return titles


def _title_is_duplicate(title: str, existing: Iterable[str]) -> bool:
    """Loose dedup: normalized exact match OR >=85% token overlap."""
    norm = re.sub(r"\s+", " ", title.strip().lower())
    if not norm:
        return False
    tokens_new = set(re.findall(r"[a-z0-9]+", norm))
    if not tokens_new:
        return False
    for other in existing:
        o = re.sub(r"\s+", " ", other.strip().lower())
        if o == norm:
            return True
        tokens_old = set(re.findall(r"[a-z0-9]+", o))
        if not tokens_old:
            continue
        overlap = len(tokens_new & tokens_old) / max(len(tokens_new | tokens_old), 1)
        if overlap >= 0.85:
            return True
    return False


# ----------------------------------------------------------------------------
# AppleScript write
# ----------------------------------------------------------------------------
def _applescript_quote(s: str) -> str:
    """Escape for an AppleScript double-quoted string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _fmt_due_for_applescript(dt: datetime) -> str:
    # AppleScript's date literal parser accepts "M/D/YYYY H:MM:SS AM/PM"
    local = dt.astimezone()
    return local.strftime("%-m/%-d/%Y %-I:%M:%S %p")


def _create_reminder(title: str, notes: str, due: datetime, list_name: str) -> bool:
    script = (
        f'tell application "Reminders"\n'
        f'    tell list "{_applescript_quote(list_name)}"\n'
        f'        make new reminder with properties {{'
        f'name:"{_applescript_quote(title)}", '
        f'body:"{_applescript_quote(notes)}", '
        f'due date:date "{_fmt_due_for_applescript(due)}"'
        f'}}\n'
        f'    end tell\n'
        f'end tell\n'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        print(
            f"osascript failed for '{title}': {exc.stderr.strip()}",
            file=sys.stderr,
        )
        return False


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def _build_title(cand: Candidate) -> str:
    # Short action verb + person + subject fragment
    name = cand.sender_name.strip() or cand.sender_email
    # Simplify emails to "first last" when possible
    name = re.sub(r"\s*<.*>\s*$", "", name).strip().strip('"')
    subj = cand.subject.strip()
    # Collapse common "RE:"/"FWD:" markers
    subj = re.sub(r"^\s*(re|fwd|fw)\s*:\s*", "", subj, flags=re.IGNORECASE)
    subj = subj[:60].rstrip(" -:|")
    return f"{cand.action_verb} to {name} re: {subj}"


def _build_notes(cand: Candidate) -> str:
    summary = (cand.snippet or cand.body_preview[:200] or "").strip()
    summary = re.sub(r"\s+", " ", summary)[:240]
    lines = [
        f"From: {cand.sender_name} <{cand.sender_email}>",
        f"Received: {cand.received.astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        f"Why flagged: {cand.rationale}",
        "",
        summary,
        "",
    ]
    if cand.gmail_url:
        lines.append(f"Link: {cand.gmail_url}")
    else:
        lines.append("Link: Check GMU Outlook (https://outlook.cloud.microsoft/mail/)")
    return "\n".join(lines)


def run(
    since_hours: int = DEFAULT_SINCE_HOURS,
    dry_run: bool = False,
    verbose: bool = False,
    max_reminders: int = MAX_REMINDERS_PER_RUN,
) -> list[dict]:
    run_time = datetime.now(tz=timezone.utc)

    candidates: list[Candidate] = []
    candidates.extend(_load_gmail_candidates(since_hours, verbose=verbose))
    candidates.extend(_load_exchange_candidates(since_hours, verbose=verbose))
    if verbose:
        print(
            f"loaded {len(candidates)} raw candidates across all sources",
            file=sys.stderr,
        )

    # Classify
    qualifying: list[Candidate] = []
    for c in candidates:
        _classify(c)
        if c.priority < 99:
            c.inferred_due = _infer_due(c, run_time)
            qualifying.append(c)

    if verbose:
        print(f"{len(qualifying)} passed strict filter", file=sys.stderr)

    # Sort by priority, then newest first
    qualifying.sort(key=lambda c: (c.priority, -c.received.timestamp()))

    # Build planned reminders with dedup
    existing = _load_existing_reminder_titles() if not dry_run else set()
    # For dry-run we still read existing to show what would be skipped
    if dry_run:
        existing = _load_existing_reminder_titles()

    planned: list[dict] = []
    for cand in qualifying:
        if len(planned) >= max_reminders:
            break
        title = _build_title(cand)
        if _title_is_duplicate(title, existing):
            if verbose:
                print(f"dedup: skipping '{title}'", file=sys.stderr)
            continue
        notes = _build_notes(cand)
        entry = {
            "title": title,
            "notes": notes,
            "due": cand.inferred_due.astimezone().isoformat() if cand.inferred_due else None,
            "priority": cand.priority,
            "category": cand.category,
            "source": cand.source,
            "message_id": cand.message_id,
            "gmail_url": cand.gmail_url,
            "rationale": cand.rationale,
        }
        planned.append(entry)
        existing.add(title.lower())

    # Create (or don't)
    created: list[dict] = []
    if dry_run:
        print(
            f"[dry-run] would create {len(planned)} reminder(s):",
            file=sys.stderr,
        )
        for p in planned:
            print(f"  - [{p['category']}] {p['title']} (due {p['due']})", file=sys.stderr)
        return planned

    for p in planned:
        due = datetime.fromisoformat(p["due"]) if p["due"] else (run_time + timedelta(hours=24))
        ok = _create_reminder(p["title"], p["notes"], due, SHELDON_LIST_NAME)
        if ok:
            created.append(p)

    print(
        f"created {len(created)} reminder(s) in '{SHELDON_LIST_NAME}':",
        file=sys.stderr,
    )
    for c in created:
        print(f"  - [{c['category']}] {c['title']} (due {c['due']})", file=sys.stderr)

    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since-hours",
        type=int,
        default=DEFAULT_SINCE_HOURS,
        help="Look back this many hours (default 24).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and print what would be created without touching Reminders.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Extra logging on stderr.",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=MAX_REMINDERS_PER_RUN,
        help=f"Hard cap on reminders created per run (default {MAX_REMINDERS_PER_RUN}).",
    )
    args = parser.parse_args()

    try:
        result = run(
            since_hours=args.since_hours,
            dry_run=args.dry_run,
            verbose=args.verbose,
            max_reminders=args.max,
        )
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"extractor failed: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return 1

    # Emit machine-readable summary on stdout
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
