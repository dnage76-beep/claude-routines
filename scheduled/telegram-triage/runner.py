#!/usr/bin/env python3
"""Scheduled inbox-triage Telegram push.

Runs headless (no Claude Code needed). Pulls the last 24h across three inboxes
and sends a short, prioritized summary to Derek's Telegram DM via the Bot API.

Sources:
  - Gmail personal   (dnage76@gmail.com)   via gmail-multi tokens
  - Gmail secondary  (dereknagel05@gmail.com) via gmail-multi tokens
  - GMU Exchange     (dnagel@gmu.edu)       via Apple Mail Envelope Index

Output matches routines/daily-inbox-triage.md: Urgent / This week / FYI, capped.

Required env/files:
  - Gmail tokens at  <repo>/mcp-servers/gmail-multi/tokens/{personal,secondary}.json
  - Telegram token + chat_id resolved in this order:
      1. $TELEGRAM_BOT_TOKEN + $TELEGRAM_CHAT_ID
      2. config.json next to this file (gitignored)
      3. ~/.claude/channels/telegram/.env + first entry of access.json allowFrom
      4. macOS Keychain:  security find-generic-password -s sheldon-telegram-bot -w
                          security find-generic-password -s sheldon-telegram-chat -w
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
GMAIL_DIR = REPO_ROOT / "mcp-servers" / "gmail-multi"
TOKENS_DIR = GMAIL_DIR / "tokens"

LOG_DIR = Path.home() / "Library" / "Logs" / "sheldon-telegram-triage"
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR = Path.home() / ".sheldon" / "telegram-triage"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LAST_PUSH_STATE = STATE_DIR / "last-push.json"

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TELEGRAM_API = "https://api.telegram.org"

# Apple Mail paths (matches mcp-servers/mail-exchange/server.py)
MAIL_ROOT = Path.home() / "Library" / "Mail" / "V10"
ENVELOPE_DB = MAIL_ROOT / "MailData" / "Envelope Index"
EXCHANGE_ACCOUNT_UUID = "00EC10D3-DDC8-4213-93CE-8906B6CB949B"

# Triage heuristics. Derek's inner-circle — force UP to urgent.
URGENT_SENDERS = {
    "ssarver@gmu.edu",               # academic advisor
    "donald.osborn2@ngc.com",        # Northrop Grumman lead
    "tbooker@gmu.edu",               # Dynamics prof
    "nrogers1@gmu.edu",              # athletics support
    "vickihuttar@gmail.com",
    "dhuttar@gmail.com",
    "danielrnyk@yahoo.com",
    "tricianagel73@gmail.com",       # Mom
    "ptnagel@gmail.com",             # Dad
    "sgnagel18@gmail.com",            # Sarah
}
URGENT_KEYWORDS = [
    "interview", "deadline", "due today", "due tomorrow", "final notice",
    "action required", "past due", "payment", "urgent", "canvas",
    "rent", "lease", "grade posted", "missing assignment",
]
FYI_SENDERS_DOMAINS = {
    "mail.instagram.com", "linkedin.com", "noreply@", "no-reply@",
    "mailchimp", "notifications@github.com", "alerts@",
    "support@anthropic.com", "stripe.com", "news@", "newsletter",
}

MAX_PER_BUCKET = 3
MAX_TOTAL = 7

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_FILE = LOG_DIR / "runner.log"

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    sys.stderr.write(line)
    with _LOG_FILE.open("a") as f:
        f.write(line)

# ---------------------------------------------------------------------------
# Telegram token + chat_id resolution
# ---------------------------------------------------------------------------
def _resolve_telegram() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    cfg_path = SCRIPT_DIR / "config.json"
    if cfg_path.exists() and (not token or not chat_id):
        try:
            cfg = json.loads(cfg_path.read_text())
            token = token or cfg.get("telegram_bot_token")
            chat_id = chat_id or cfg.get("telegram_chat_id")
        except Exception as e:
            log(f"config.json parse error: {e}")

    # Fallback 3: reuse the Telegram plugin's existing credentials
    if not token:
        env_file = Path.home() / ".claude" / "channels" / "telegram" / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                m = re.match(r"^(\w+)=(.*)$", line)
                if m and m.group(1) == "TELEGRAM_BOT_TOKEN":
                    token = m.group(2).strip()
                    break
    if not chat_id:
        access = Path.home() / ".claude" / "channels" / "telegram" / "access.json"
        if access.exists():
            try:
                data = json.loads(access.read_text())
                allowed = data.get("allowFrom") or []
                if allowed:
                    chat_id = str(allowed[0])
            except Exception as e:
                log(f"access.json parse error: {e}")

    # Fallback 4: macOS keychain
    if not token:
        try:
            token = subprocess.check_output(
                ["security", "find-generic-password",
                 "-s", "sheldon-telegram-bot", "-w"],
                stderr=subprocess.DEVNULL, text=True,
            ).strip()
        except subprocess.CalledProcessError:
            pass
    if not chat_id:
        try:
            chat_id = subprocess.check_output(
                ["security", "find-generic-password",
                 "-s", "sheldon-telegram-chat", "-w"],
                stderr=subprocess.DEVNULL, text=True,
            ).strip()
        except subprocess.CalledProcessError:
            pass

    if not token or not chat_id:
        raise RuntimeError(
            "Missing Telegram token or chat_id. Set env, "
            "write scheduled/telegram-triage/config.json, "
            "add to ~/.claude/channels/telegram/.env, or store in keychain."
        )
    return token, chat_id

# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------
def _gmail_service(account: str):
    """Build a Gmail service using gmail-multi's tokens. Refresh if needed."""
    from google.auth.transport.requests import Request as _GReq
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = TOKENS_DIR / f"{account}.json"
    if not token_path.exists():
        raise RuntimeError(f"No token for {account} at {token_path}")
    creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(_GReq())
        token_path.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def fetch_gmail(account: str, since_hours: int) -> list[dict]:
    """Fetch last N hours from a Gmail account, drop promotions/social/newsletters."""
    try:
        svc = _gmail_service(account)
    except Exception as e:
        log(f"gmail[{account}] auth failed: {e}")
        return []

    after = (datetime.now(tz=timezone.utc) - timedelta(hours=since_hours))
    q = f"after:{after.strftime('%Y/%m/%d')} -category:promotions -category:social"

    try:
        resp = svc.users().messages().list(
            userId="me", q=q, maxResults=50
        ).execute()
    except Exception as e:
        log(f"gmail[{account}] list error: {e}")
        return []

    out: list[dict] = []
    for m in resp.get("messages", []) or []:
        try:
            msg = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date", "To"]
            ).execute()
            headers = msg.get("payload", {}).get("headers", [])
            out.append({
                "source": account,
                "id": m["id"],
                "thread_id": msg.get("threadId"),
                "from": _header(headers, "From"),
                "subject": _header(headers, "Subject") or "(no subject)",
                "snippet": msg.get("snippet", "")[:280],
                "date": _header(headers, "Date"),
                "labels": msg.get("labelIds", []),
            })
        except Exception as e:
            log(f"gmail[{account}] read {m['id']} failed: {e}")
    return out

# ---------------------------------------------------------------------------
# GMU Exchange via Apple Mail
# ---------------------------------------------------------------------------
def fetch_exchange(since_hours: int) -> list[dict]:
    if not ENVELOPE_DB.exists():
        log("no apple mail envelope index — skipping gmu")
        return []
    tmp = Path(tempfile.gettempdir()) / "sheldon_envelope_copy.sqlite"
    try:
        shutil.copy(ENVELOPE_DB, tmp)
        for suffix in ("-shm", "-wal"):
            src = Path(f"{ENVELOPE_DB}{suffix}")
            if src.exists():
                shutil.copy(src, f"{tmp}{suffix}")
    except Exception as e:
        log(f"envelope copy failed: {e}")
        return []

    try:
        conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        # Find the Inbox mailbox for the Exchange account
        url_prefix = f"ews://{EXCHANGE_ACCOUNT_UUID}/Inbox"
        row = conn.execute(
            "SELECT ROWID FROM mailboxes WHERE url = ?", (url_prefix,)
        ).fetchone()
        if not row:
            # Try URL-encoded form
            row = conn.execute(
                "SELECT ROWID FROM mailboxes "
                "WHERE url LIKE ? ORDER BY total_count DESC LIMIT 1",
                (f"ews://{EXCHANGE_ACCOUNT_UUID}/Inbox%",)
            ).fetchone()
        if not row:
            log("exchange inbox mailbox not found")
            return []
        mbox_id = row["ROWID"]
        cutoff = int((datetime.now(tz=timezone.utc) - timedelta(hours=since_hours)).timestamp())
        rows = conn.execute(
            """
            SELECT m.ROWID as id, m.date_sent, m.read, m.remote_id,
                   s.subject as subject,
                   a.address as from_addr, a.comment as from_name
            FROM messages m
            LEFT JOIN subjects s ON s.ROWID = m.subject
            LEFT JOIN addresses a ON a.ROWID = m.sender
            WHERE m.mailbox = ? AND m.date_sent >= ?
            ORDER BY m.date_sent DESC LIMIT 50
            """,
            (mbox_id, cutoff),
        ).fetchall()
    except Exception as e:
        log(f"exchange query error: {e}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return [
        {
            "source": "gmu",
            "id": str(r["id"]),
            "thread_id": None,
            "from": (r["from_name"] or r["from_addr"] or ""),
            "from_email": r["from_addr"] or "",
            "subject": r["subject"] or "(no subject)",
            "snippet": "",
            "date": datetime.fromtimestamp(r["date_sent"], tz=timezone.utc).isoformat()
                    if r["date_sent"] else "",
            "read": bool(r["read"]),
        }
        for r in rows
    ]

# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
@dataclass
class Item:
    source: str
    id: str
    frm: str
    subject: str
    snippet: str
    bucket: str = "this_week"
    score: int = 0


def _from_email(raw: str) -> str:
    m = re.search(r"[\w\.\-\+]+@[\w\.\-]+", raw or "")
    return m.group(0).lower() if m else ""


def _is_auto(frm_email: str, subject: str) -> bool:
    s = subject.lower()
    f = frm_email.lower()
    for needle in FYI_SENDERS_DOMAINS:
        if needle in f:
            return True
    if any(k in s for k in ("unsubscribe", "newsletter", "digest", "shipped", "receipt",
                            "confirmation number", "weekly update")):
        return True
    return False


def classify(raw: dict) -> Item:
    frm_email = _from_email(raw.get("from", "")) or raw.get("from_email", "").lower()
    subject = raw.get("subject", "") or ""
    snippet = raw.get("snippet", "") or ""
    lower_blob = f"{subject}\n{snippet}".lower()

    score = 0
    bucket = "this_week"

    if frm_email and frm_email in URGENT_SENDERS:
        score += 10
        bucket = "urgent"
    if frm_email.endswith("@gmu.edu") or frm_email.endswith("@ngc.com"):
        score += 4

    for kw in URGENT_KEYWORDS:
        if kw in lower_blob:
            score += 5
            if bucket != "urgent":
                bucket = "urgent"

    if _is_auto(frm_email, subject):
        score -= 4
        if bucket == "this_week":
            bucket = "fyi"

    return Item(
        source=raw["source"],
        id=str(raw["id"]),
        frm=raw.get("from", ""),
        subject=subject,
        snippet=snippet,
        bucket=bucket,
        score=score,
    )

# ---------------------------------------------------------------------------
# Summary formatting
# ---------------------------------------------------------------------------
def _short(s: str, n: int = 55) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "\u2026"


def _short_from(raw: str) -> str:
    # "Name <addr>" -> Name; else first part of email
    if not raw:
        return "?"
    m = re.match(r"\s*\"?([^\"<]+?)\"?\s*<", raw)
    if m:
        return _short(m.group(1).strip(), 30)
    m = re.search(r"[\w\.\-\+]+@[\w\.\-]+", raw)
    if m:
        return _short(m.group(0).split("@")[0], 30)
    return _short(raw, 30)


def build_message(items: list[Item], window_label: str) -> str:
    if not items:
        return f"Sheldon {window_label} triage\n\nInbox quiet. No action items across the three accounts."

    buckets = {"urgent": [], "this_week": [], "fyi": []}
    for it in items:
        buckets[it.bucket].append(it)
    for k in buckets:
        buckets[k].sort(key=lambda i: -i.score)
        buckets[k] = buckets[k][:MAX_PER_BUCKET]

    # Enforce total cap; drop from fyi -> this_week -> urgent
    total = sum(len(v) for v in buckets.values())
    for k in ("fyi", "this_week"):
        while total > MAX_TOTAL and buckets[k]:
            buckets[k].pop()
            total -= 1

    lines = [f"Sheldon {window_label} triage"]
    order = [("urgent", "Urgent"), ("this_week", "This week"), ("fyi", "FYI")]
    for key, label in order:
        if not buckets[key]:
            continue
        lines.append("")
        lines.append(label)
        for it in buckets[key]:
            tag = it.source
            frm = _short_from(it.frm)
            subj = _short(it.subject, 60)
            ref = f"{it.source}:{it.id}"
            lines.append(f"- [{tag}] {frm} -- {subj}  [{ref}]")

    lines.append("")
    lines.append("Reply with \"draft reply to [ref]\" and the next Sheldon session will pick it up.")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Telegram send
# ---------------------------------------------------------------------------
def _ssl_ctx() -> ssl.SSLContext:
    """Build an SSL context that works on Derek's mac.

    macOS system Python often lacks a usable trust store; prefer certifi
    if it's available in the same venv that has googleapiclient.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def send_telegram(token: str, chat_id: str, text: str) -> dict:
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20, context=_ssl_ctx()) as resp:
        body = resp.read().decode("utf-8")
    try:
        return json.loads(body)
    except Exception:
        return {"raw": body}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    args = sys.argv[1:]
    window = "morning"
    if args and args[0] in ("morning", "evening"):
        window = args[0]
    dry_run = "--dry-run" in args

    # Hours to scan: morning looks back 12h (covers overnight), evening looks
    # back 10h (catches end of day). These windows overlap only a little and
    # together cover the full 24h.
    since_hours = 12 if window == "morning" else 10

    log(f"start window={window} since_hours={since_hours} dry={dry_run}")

    items: list[Item] = []
    for acct in ("personal", "secondary"):
        raw = fetch_gmail(acct, since_hours)
        log(f"gmail[{acct}] -> {len(raw)} messages")
        items.extend(classify(r) for r in raw)

    gmu = fetch_exchange(since_hours)
    log(f"exchange[gmu] -> {len(gmu)} messages")
    items.extend(classify(r) for r in gmu)

    label = "morning" if window == "morning" else "evening"
    msg = build_message(items, label)

    # Persist the exact text + item refs so the next Claude Code session can
    # resolve "draft reply to personal:19abcdef" by looking at the last push.
    state = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "window": window,
        "items": [
            {
                "ref": f"{it.source}:{it.id}",
                "source": it.source,
                "id": it.id,
                "from": it.frm,
                "subject": it.subject,
                "bucket": it.bucket,
            }
            for it in items
        ],
        "text": msg,
    }
    LAST_PUSH_STATE.write_text(json.dumps(state, indent=2))

    if dry_run:
        print(msg)
        log("dry run - skipped send")
        return 0

    try:
        token, chat_id = _resolve_telegram()
    except Exception as e:
        log(f"telegram resolve failed: {e}")
        return 2

    try:
        result = send_telegram(token, chat_id, msg)
        ok = bool(result.get("ok"))
        mid = (result.get("result") or {}).get("message_id")
        log(f"telegram send ok={ok} message_id={mid}")
        if not ok:
            log(f"telegram response: {result}")
            return 3
    except Exception as e:
        log(f"telegram send error: {e}")
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
